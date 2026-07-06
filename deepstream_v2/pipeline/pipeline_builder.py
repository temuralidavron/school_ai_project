"""
NVIDIA DeepStream GStreamer pipeline — RTX 5080 (sm_120) uchun moslashtirilgan.

TRT 10.3 RTX 5080'ni qo'llab-quvvatlamaydi (sm_120), shuning uchun:
  - nvinfer, nvtracker: olib tashlandi
  - Barcha inference: onnxruntime-gpu (Python, appsink callback'da)
  - Frame extraction: CPU path (nvvideoconvert NV12→BGR, Gst.Buffer.map)

Arxitektura:
  nvv4l2decoder(N) → nvstreammux
  → nvvideoconvert (NV12 NVMM → BGR CPU)
  → appsink
    → Det10gRunner (SCRFD, GPU ORT)
    → IouTracker (pure Python)
    → ArcFaceRunner (GPU ORT) → Kafka
    → MJPEG (OpenCV draw + push)
"""
import logging

import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

from pipeline.config import (
    GPU_ID, MUX_WIDTH, MUX_HEIGHT, MUX_TIMEOUT_US,
)

log = logging.getLogger(__name__)


def _create_source_bin(index: int, uri: str) -> Gst.Bin:
    """
    Explicit element: filesrc/rtspsrc → h264parse → nvv4l2decoder.
    uridecodebin CPU decoder tanlash muammosini chetlaydi.
    """
    nbin = Gst.Bin.new(f"source-bin-{index}")

    parse   = Gst.ElementFactory.make("h264parse",     f"parse-{index}")
    decoder = Gst.ElementFactory.make("nvv4l2decoder", f"nvdec-{index}")

    if uri.startswith("rtsp://"):
        src   = Gst.ElementFactory.make("rtspsrc",      f"rtspsrc-{index}")
        depay = Gst.ElementFactory.make("rtph264depay", f"depay-{index}")
        src.set_property("location", uri)
        src.set_property("latency",  0)
        for el in (src, depay, parse, decoder):
            nbin.add(el)
        depay.link(parse)
        parse.link(decoder)
        src.connect("pad-added", _cb_rtspsrc_pad, depay)
    else:
        path    = uri.replace("file://", "")
        filesrc = Gst.ElementFactory.make("filesrc", f"filesrc-{index}")
        demux   = Gst.ElementFactory.make("qtdemux",  f"demux-{index}")
        filesrc.set_property("location", path)
        for el in (filesrc, demux, parse, decoder):
            nbin.add(el)
        filesrc.link(demux)
        demux.connect("pad-added", _cb_demux_pad, parse)
        parse.link(decoder)

    ghost = Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC)
    nbin.add_pad(ghost)
    decoder.connect("pad-added", _cb_decoder_pad, ghost)

    static = decoder.get_static_pad("src")
    if static and not ghost.get_target():
        ghost.set_target(static)

    return nbin


def _cb_demux_pad(demux, pad, h264parse):
    if "video" not in pad.get_name():
        return
    sink = h264parse.get_static_pad("sink")
    if not sink.is_linked():
        pad.link(sink)


def _cb_rtspsrc_pad(rtspsrc, pad, depay):
    if "video" not in (pad.get_name() or ""):
        return
    sink = depay.get_static_pad("sink")
    if not sink.is_linked():
        pad.link(sink)


def _cb_decoder_pad(decoder, pad, ghost):
    if not ghost.get_target():
        ghost.set_target(pad)


def build(sources: list[str], probe_data: dict,
          loop_video: bool = True) -> tuple[Gst.Pipeline, GLib.MainLoop]:
    """
    sources:    URI ro'yxati
    probe_data: {"detector": Det10gRunner, "arcface": ArcFaceRunner,
                 "kafka": KafkaClient, "camera_ids": dict}
    loop_video: True — video fayl tugagach qayta boshlaydi (RTSP uchun False)
    """
    Gst.init(None)
    pipeline = Gst.Pipeline()
    loop     = GLib.MainLoop()

    # ── nvstreammux ───────────────────────────────────────────────────────────
    streammux = Gst.ElementFactory.make("nvstreammux", "stream-muxer")
    streammux.set_property("batch-size",           len(sources))
    streammux.set_property("width",                MUX_WIDTH)
    streammux.set_property("height",               MUX_HEIGHT)
    streammux.set_property("batched-push-timeout", MUX_TIMEOUT_US)
    streammux.set_property("gpu-id",               GPU_ID)
    is_rtsp = any(u.startswith("rtsp://") for u in sources)
    streammux.set_property("live-source", 1 if is_rtsp else 0)

    # ── nvvideoconvert: NV12 NVMM → BGR CPU ──────────────────────────────────
    converter = Gst.ElementFactory.make("nvvideoconvert", "converter")

    caps_bgr = Gst.ElementFactory.make("capsfilter", "caps-bgr")
    caps_bgr.set_property("caps",
        Gst.Caps.from_string("video/x-raw, format=BGRx"))

    # ── appsink — Python inference ────────────────────────────────────────────
    appsink = Gst.ElementFactory.make("appsink", "appsink")
    appsink.set_property("emit-signals", True)
    appsink.set_property("sync",         False)
    appsink.set_property("drop",         True)
    appsink.set_property("max-buffers",  2)

    for el in (streammux, converter, caps_bgr, appsink):
        pipeline.add(el)

    # ── Manbalar ──────────────────────────────────────────────────────────────
    for i, uri in enumerate(sources):
        src_bin = _create_source_bin(i, uri)
        pipeline.add(src_bin)
        mux_pad = streammux.get_request_pad(f"sink_{i}")
        src_pad = src_bin.get_static_pad("src")
        src_pad.link(mux_pad)

    # ── Ulash ─────────────────────────────────────────────────────────────────
    streammux.link(converter)
    converter.link(caps_bgr)
    caps_bgr.link(appsink)

    # ── Appsink callback — barcha inference va Kafka ──────────────────────────
    from pipeline.probes.appsink_proc import make_appsink_callback
    appsink.connect("new-sample", make_appsink_callback(probe_data))

    # ── Bus hodisalari ────────────────────────────────────────────────────────
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", _bus_call, loop, pipeline, loop_video)

    log.info("Pipeline qurildi: %d manba (nvstreammux, CPU appsink path)", len(sources))
    return pipeline, loop


def _bus_call(bus, message, loop, pipeline, loop_video):
    t = message.type
    if t == Gst.MessageType.EOS:
        if loop_video:
            log.info("EOS — video qayta boshlanmoqda (loop)...")
            pipeline.seek_simple(
                Gst.Format.TIME,
                Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                0,
            )
        else:
            log.info("EOS — pipeline tugadi")
            loop.quit()
    elif t == Gst.MessageType.WARNING:
        err, dbg = message.parse_warning()
        log.warning("GStreamer: %s — %s", err, dbg)
    elif t == Gst.MessageType.ERROR:
        err, dbg = message.parse_error()
        log.error("GStreamer xato: %s — %s", err, dbg)
        loop.quit()
    return True
