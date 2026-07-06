#!/usr/bin/env python3
"""
DeepStream 8.0 to'liq pipeline — B2 bosqichi: nvinfer PGIE + nvtracker (NvDCF).

Arxitektura:
  filesrc → qtdemux → h264parse → nvv4l2decoder → nvstreammux
  → nvinfer (det_10g TRT, output-tensor-meta=1)
  → [probe A: tensor decode → obj_meta qo'shish + kps saqlash]
  → nvtracker (NvDCF GPU)
  → [probe B: object_id (barqaror track) + kps bog'lash → statistika]
  → fakesink

B2 mezoni: unique track_id soni ≈ odam soni (IouTracker'dagi yuzlab sakrash yo'q).
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

MUX_WIDTH   = int(os.getenv("MUX_WIDTH",  "1920"))
MUX_HEIGHT  = int(os.getenv("MUX_HEIGHT", "1080"))
DET_THR     = float(os.getenv("DET_THRESHOLD", "0.35"))
NMS_THR     = float(os.getenv("NMS_THRESHOLD", "0.40"))
MIN_PX      = int(os.getenv("MIN_FACE_PX", "20"))
PGIE_CFG    = os.getenv("PGIE_CONFIG", "/ds3/configs/pgie_det10g.txt")
TRACKER_LIB = os.getenv("TRACKER_LIB",
                        "/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so")
TRACKER_CFG = os.getenv(
    "TRACKER_CONFIG",
    "/opt/nvidia/deepstream/deepstream/samples/configs/deepstream-app/config_tracker_NvDCF_perf.yml")

_state = {"frames": 0, "faces_total": 0, "min": 999, "max": 0,
          "track_ids": set(), "dbg_done": False}

# frame_num -> dets (kps'ni tracker'dan keyin bbox bo'yicha bog'lash uchun)
_kps_store: dict = {}
_KPS_STORE_MAX = 60

# det_10g ONNX chiqish nomlari -> haqiqiy shakl. nvinfer birinchi o'lchamni
# batch deb qirqadi — meta o'lchamiga ishonib bo'lmaydi, nom bo'yicha o'qiymiz.
_DET10G_SHAPES = {
    "448": (12800, 1), "471": (3200, 1), "494": (800, 1),
    "451": (12800, 4), "474": (3200, 4), "497": (800, 4),
    "454": (12800, 10), "477": (3200, 10), "500": (800, 10),
}
_DET10G_SHAPES.update({k + "_b": v for k, v in list(_DET10G_SHAPES.items())})


def _extract_layers(tensor_meta) -> list:
    """get_nvds_LayerInfo — host buffer'ni to'ldiradi (output_layers_info NULL)."""
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


def _add_obj_meta(batch_meta, frame_meta, det):
    """Decode qilingan yuzni nvtracker uchun obj_meta sifatida frame'ga qo'shadi."""
    x1, y1, x2, y2 = det["bbox"]
    obj = pyds.nvds_acquire_obj_meta_from_pool(batch_meta)
    obj.unique_component_id = 1
    obj.class_id = 0
    obj.confidence = det["score"]
    obj.obj_label = "face"
    r = obj.rect_params
    r.left = max(0.0, x1)
    r.top = max(0.0, y1)
    r.width = max(1.0, x2 - x1)
    r.height = max(1.0, y2 - y1)
    r.border_width = 0
    obj.object_id = 0xFFFFFFFFFFFFFFFF  # UNTRACKED — nvtracker o'zi beradi
    pyds.nvds_add_obj_meta_to_frame(frame_meta, obj, None)


def _pgie_probe(pad, info, _u):
    """Probe A: tensor decode → obj_meta + kps saqlash."""
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
                dets = decode(layers, scale=scale,
                              score_thr=DET_THR, nms_thr=NMS_THR, min_px=MIN_PX)
                for d in dets:
                    _add_obj_meta(batch_meta, frame_meta, d)
                # nvtracker inference bo'lmagan kadrlarni o'tkazib yubormasligi uchun
                try:
                    frame_meta.bInferDone = 1
                except Exception:
                    pass
                _state["probeA"] = _state.get("probeA", 0) + 1
                if _state["probeA"] <= 3 or _state["probeA"] % 300 == 0:
                    cnt = 0
                    lo = frame_meta.obj_meta_list
                    while lo is not None:
                        cnt += 1
                        try:
                            lo = lo.next
                        except StopIteration:
                            break
                    log.info("probeA#%d: %d det, obj_meta_list=%d (frame_num=%d)",
                             _state["probeA"], len(dets), cnt, frame_meta.frame_num)
                _kps_store[frame_meta.frame_num] = dets
                if len(_kps_store) > _KPS_STORE_MAX:
                    for k in sorted(_kps_store)[:-_KPS_STORE_MAX // 2]:
                        _kps_store.pop(k, None)
            try:
                l_user = l_user.next
            except StopIteration:
                break
        try:
            l_frame = l_frame.next
        except StopIteration:
            break
    return Gst.PadProbeReturn.OK


def _match_kps(dets, l, t, w, h):
    """Tracker bbox'iga eng yaqin detection kps'ini topadi (markaz masofasi)."""
    if not dets:
        return None
    cx, cy = l + w / 2, t + h / 2
    best, best_d = None, 1e18
    for d in dets:
        x1, y1, x2, y2 = d["bbox"]
        dx = (x1 + x2) / 2 - cx
        dy = (y1 + y2) / 2 - cy
        dist = dx * dx + dy * dy
        if dist < best_d:
            best_d, best = dist, d
    # markaz bbox kengligining yarmidan uzoq bo'lsa — mos emas
    if best is not None and best_d > (max(w, h) * 0.75) ** 2:
        return None
    return best


def _tracker_probe(pad, info, _u):
    """Probe B: barqaror object_id + kps bog'lash + statistika."""
    buf = info.get_buffer()
    if not buf:
        return Gst.PadProbeReturn.OK
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(buf))
    if not batch_meta:
        return Gst.PadProbeReturn.OK

    l_frame = batch_meta.frame_meta_list
    while l_frame is not None:
        frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        dets = _kps_store.get(frame_meta.frame_num, [])
        n = 0
        with_kps = 0
        l_obj = frame_meta.obj_meta_list
        while l_obj is not None:
            obj = pyds.NvDsObjectMeta.cast(l_obj.data)
            n += 1
            r = obj.rect_params
            _state["track_ids"].add(obj.object_id)
            if _match_kps(dets, r.left, r.top, r.width, r.height) is not None:
                with_kps += 1
            try:
                l_obj = l_obj.next
            except StopIteration:
                break

        _state["frames"] += 1
        _state["faces_total"] += n
        _state["min"] = min(_state["min"], n)
        _state["max"] = max(_state["max"], n)
        f = _state["frames"]
        if f <= 3 or f % 300 == 0:
            log.info("frame#%d → %d track (kps_bog=%d, unique_id=%d)",
                     f, n, with_kps, len(_state["track_ids"]))
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

    tracker = Gst.ElementFactory.make("nvtracker", "tracker")
    tracker.set_property("ll-lib-file", TRACKER_LIB)
    tracker.set_property("ll-config-file", TRACKER_CFG)
    tracker.set_property("tracker-width", 960)
    tracker.set_property("tracker-height", 544)
    tracker.set_property("gpu-id", 0)

    sink = Gst.ElementFactory.make("fakesink", "sink")
    sink.set_property("sync", False)

    for el in (src_bin, mux, pgie, tracker, sink):
        pipeline.add(el)

    src_bin.get_static_pad("src").link(mux.request_pad_simple("sink_0"))
    mux.link(pgie)
    pgie.link(tracker)
    tracker.link(sink)

    pgie.get_static_pad("src").add_probe(
        Gst.PadProbeType.BUFFER, _pgie_probe, None)
    tracker.get_static_pad("src").add_probe(
        Gst.PadProbeType.BUFFER, _tracker_probe, None)

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
    p.add_argument("--max-frames", type=int, default=0)
    args = p.parse_args()

    if not os.path.exists(args.video):
        log.error("Video topilmadi: %s", args.video)
        sys.exit(1)

    log.info("B2 sinovi: nvinfer PGIE + nvtracker NvDCF")
    log.info("  video=%s  tracker_cfg=%s", args.video, os.path.basename(TRACKER_CFG))

    pipeline, loop = build_pipeline(args.video)

    if args.max_frames > 0:
        def _check():
            if _state["frames"] >= args.max_frames:
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
        log.info("YAKUN: kadr=%d  track/kadr min=%d max=%d avg=%.1f",
                 f, _state["min"], _state["max"],
                 _state["faces_total"] / max(f, 1))
        log.info("UNIQUE TRACK ID: %d  (odam soni ~25-35 bo'lishi kerak, "
                 "yuzlab emas)", len(_state["track_ids"]))
        log.info("=" * 50)


if __name__ == "__main__":
    main()
