#!/usr/bin/env python3
"""
DeepStream 8.0 to'liq pipeline — B1 bosqichi: nvinfer PGIE (TensorRT, sm_120)
+ Python probe'da SCRFD tensor decode (C++ parser yo'q).

Arxitektura (B1):
  filesrc → qtdemux → h264parse → nvv4l2decoder → nvstreammux
  → nvinfer (det_10g TRT engine, output-tensor-meta=1)
  → [probe: pyds tensor meta → scrfd_decode → yuz soni log]
  → fakesink

Sinov mezoni: kadrda ~20 yuz (ORT versiyasi bilan teng).
"""
import argparse
import ctypes
import logging
import os
import sys

import numpy as np

import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

import pyds

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrfd_decode import decode, INPUT_SZ

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("ds3_main")

MUX_WIDTH  = int(os.getenv("MUX_WIDTH",  "1920"))
MUX_HEIGHT = int(os.getenv("MUX_HEIGHT", "1080"))
DET_THR    = float(os.getenv("DET_THRESHOLD", "0.35"))
NMS_THR    = float(os.getenv("NMS_THRESHOLD", "0.40"))
MIN_PX     = int(os.getenv("MIN_FACE_PX", "20"))
PGIE_CFG   = os.getenv("PGIE_CONFIG", "/ds3/configs/pgie_det10g.txt")

_state = {"frames": 0, "faces_total": 0, "min": 999, "max": 0}


# det_10g ONNX chiqish nomlari -> haqiqiy shakl. nvinfer birinchi o'lchamni
# batch deb qirqadi ([12800,1] -> [1]) — meta o'lchamiga ishonib bo'lmaydi,
# lekin host buffer TO'LIQ binding hajmida — nom bo'yicha o'qiymiz.
_DET10G_SHAPES = {
    "448": (12800, 1), "471": (3200, 1), "494": (800, 1),    # score s8/s16/s32
    "451": (12800, 4), "474": (3200, 4), "497": (800, 4),    # bbox
    "454": (12800, 10), "477": (3200, 10), "500": (800, 10), # kps
}
# Batched ONNX (add_batch_dim.py) nomlari: "_b" suffiks bilan
_DET10G_SHAPES.update({k + "_b": v for k, v in list(_DET10G_SHAPES.items())})


def _extract_layers(tensor_meta) -> list:
    """NvDsInferTensorMeta -> [(name, np.ndarray float32)] (host xotirada).
    MUHIM: get_nvds_LayerInfo ishlatiladi — u host buffer'ni to'ldiradi
    (output_layers_info() da buffer NULL bo'ladi)."""
    layers = []
    for i in range(tensor_meta.num_output_layers):
        linfo = pyds.get_nvds_LayerInfo(tensor_meta, i)
        if not linfo.buffer:
            continue
        name = linfo.layerName
        known = _DET10G_SHAPES.get(name)
        if known:
            shape = list(known)
        else:
            dims = linfo.inferDims
            shape = [dims.d[k] for k in range(dims.numDims)]
        n = int(np.prod(shape)) if shape else 0
        if n == 0:
            continue
        ptr = ctypes.cast(pyds.get_ptr(linfo.buffer),
                          ctypes.POINTER(ctypes.c_float))
        arr = np.ctypeslib.as_array(ptr, shape=(n,)).copy().reshape(shape)
        layers.append((name, arr))
    return layers


def _pgie_probe(pad, info, _udata):
    buf = info.get_buffer()
    if not buf:
        return Gst.PadProbeReturn.OK
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(buf))
    if not batch_meta:
        return Gst.PadProbeReturn.OK

    scale = INPUT_SZ / max(MUX_WIDTH, MUX_HEIGHT)

    l_frame = batch_meta.frame_meta_list
    while l_frame is not None:
        frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        l_user = frame_meta.frame_user_meta_list
        while l_user is not None:
            user_meta = pyds.NvDsUserMeta.cast(l_user.data)
            if (user_meta.base_meta.meta_type
                    == pyds.NvDsMetaType.NVDSINFER_TENSOR_OUTPUT_META):
                tmeta = pyds.NvDsInferTensorMeta.cast(user_meta.user_meta_data)
                layers = _extract_layers(tmeta)
                if _state["frames"] == 0:
                    for nm, a in layers:
                        log.info("LAYER %-12s shape=%-16s min=%.3f max=%.3f",
                                 nm, str(a.shape), float(a.min()), float(a.max()))
                dets = decode(layers, scale=scale,
                              score_thr=DET_THR, nms_thr=NMS_THR, min_px=MIN_PX)
                n = len(dets)
                _state["frames"] += 1
                _state["faces_total"] += n
                _state["min"] = min(_state["min"], n)
                _state["max"] = max(_state["max"], n)
                f = _state["frames"]
                if f <= 3 or f % 300 == 0:
                    avg = _state["faces_total"] / max(f, 1)
                    log.info("frame#%d → %d yuz (min=%d max=%d avg=%.1f)",
                             f, n, _state["min"], _state["max"], avg)
            try:
                l_user = l_user.next
            except StopIteration:
                break
        try:
            l_frame = l_frame.next
        except StopIteration:
            break
    return Gst.PadProbeReturn.OK


def _cb_demux_pad(demux, pad, parse):
    if "video" in (pad.get_name() or ""):
        sink = parse.get_static_pad("sink")
        if not sink.is_linked():
            pad.link(sink)


def _cb_decoder_pad(decoder, pad, ghost):
    if not ghost.get_target():
        ghost.set_target(pad)


def build_pipeline(video_path: str):
    Gst.init(None)
    pipeline = Gst.Pipeline()
    loop = GLib.MainLoop()

    # Manba: filesrc → qtdemux → h264parse → nvv4l2decoder (v2 pattern)
    src_bin = Gst.Bin.new("source-bin-0")
    filesrc = Gst.ElementFactory.make("filesrc")
    demux   = Gst.ElementFactory.make("qtdemux")
    parse   = Gst.ElementFactory.make("h264parse")
    decoder = Gst.ElementFactory.make("nvv4l2decoder")
    filesrc.set_property("location", video_path)
    for el in (filesrc, demux, parse, decoder):
        src_bin.add(el)
    filesrc.link(demux)
    demux.connect("pad-added", _cb_demux_pad, parse)
    parse.link(decoder)
    ghost = Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC)
    src_bin.add_pad(ghost)
    decoder.connect("pad-added", _cb_decoder_pad, ghost)
    static = decoder.get_static_pad("src")
    if static and not ghost.get_target():
        ghost.set_target(static)

    mux = Gst.ElementFactory.make("nvstreammux", "mux")
    mux.set_property("batch-size", 1)
    mux.set_property("width",  MUX_WIDTH)
    mux.set_property("height", MUX_HEIGHT)
    mux.set_property("batched-push-timeout", 4000000)
    mux.set_property("gpu-id", 0)

    pgie = Gst.ElementFactory.make("nvinfer", "pgie")
    pgie.set_property("config-file-path", PGIE_CFG)

    sink = Gst.ElementFactory.make("fakesink", "sink")
    sink.set_property("sync", False)

    for el in (src_bin, mux, pgie, sink):
        pipeline.add(el)

    src_bin.get_static_pad("src").link(mux.request_pad_simple("sink_0"))
    mux.link(pgie)
    pgie.link(sink)

    pgie.get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, _pgie_probe, None)

    bus = pipeline.get_bus()
    bus.add_signal_watch()

    def _bus(bus, msg):
        t = msg.type
        if t == Gst.MessageType.EOS:
            log.info("EOS — sinov tugadi")
            loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            log.error("GStreamer xato: %s — %s", err, dbg)
            loop.quit()
        return True

    bus.connect("message", _bus)
    return pipeline, loop


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--max-frames", type=int, default=0,
                   help="0=video oxirigacha; >0 bo'lsa shu kadrdan keyin to'xtaydi")
    args = p.parse_args()

    if not os.path.exists(args.video):
        log.error("Video topilmadi: %s", args.video)
        sys.exit(1)

    log.info("B1 sinovi: nvinfer TRT PGIE + Python tensor decode")
    log.info("  video=%s  pgie=%s  thr=%.2f", args.video, PGIE_CFG, DET_THR)

    pipeline, loop = build_pipeline(args.video)

    if args.max_frames > 0:
        def _check():
            if _state["frames"] >= args.max_frames:
                log.info("max-frames yetdi — to'xtatilmoqda")
                loop.quit()
                return False
            return True
        GLib.timeout_add(500, _check)

    pipeline.set_state(Gst.State.PLAYING)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.set_state(Gst.State.NULL)
        f = _state["frames"]
        log.info("=" * 50)
        log.info("YAKUN: kadr=%d  yuz min=%d max=%d avg=%.1f",
                 f, _state["min"], _state["max"],
                 _state["faces_total"] / max(f, 1))
        log.info("=" * 50)


if __name__ == "__main__":
    main()
