#!/usr/bin/env python3
"""
DeepStream POC — bitta video faylda yuz topish + tracking.

Bu birinchi bosqich:
  1. Video faylni o'qiydi (NVDEC bilan GPU da decode)
  2. nvinfer plugin orqali yuz topadi (PeopleNet yoki FaceDetectIR)
  3. nvtracker bilan ID beradi
  4. Har kadrning metadatasini Python da o'qiydi
  5. FPS, GPU, yuz soni statistikani chiqaradi

Keyingi bosqichlar (Phase 2/3):
  - buffalo_l ni TRT engine ga aylantirish va embedding chiqarish
  - Kafka producer qo'shish
  - Davomat yozish biznes-logikasi (Python consumer)
"""
import sys
import time
import os
import json
import base64
from pathlib import Path

import numpy as np
import cv2

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

import pyds  # type: ignore  # DeepStream Python bindings (container ichida)

# ─── Kafka producer (yo'q bo'lsa skip) ───────────────────────
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "")
KAFKA_TOPIC = os.environ.get("KAFKA_TOPIC", "deepstream-faces")

# Camera ID — Django bilan bog'lanish uchun
# Bitta DeepStream container faqat bitta kamerani boshqaradi (multi-camera Phase 4)
CAMERA_ID = int(os.environ.get("CAMERA_ID", "1"))

_kafka_producer = None
if KAFKA_BOOTSTRAP:
    try:
        from kafka import KafkaProducer
        for attempt in range(15):
            try:
                _kafka_producer = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP,
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    acks=1,
                    linger_ms=10,
                )
                print(f"✅  Kafka producer ulandi: {KAFKA_BOOTSTRAP}")
                break
            except Exception as e:
                print(f"⏳  Kafka kutilmoqda ({attempt+1}/15): {e}")
                time.sleep(2)
    except ImportError:
        print("⚠️  kafka-python o'rnatilmagan — Kafka producer off")


# ─────── KONFIGURATSIYA ───────
DEFAULT_INFER_CONFIG = "/workspace/configs/pgie_config_face.txt"
DEFAULT_TRACKER_CONFIG = "/workspace/configs/tracker_NvDCF.yml"

MUXER_WIDTH = int(os.environ.get("MUXER_WIDTH", 1920))
MUXER_HEIGHT = int(os.environ.get("MUXER_HEIGHT", 1080))
MUXER_BATCH_SIZE = int(os.environ.get("MUXER_BATCH_SIZE", 1))
MUXER_BATCHED_PUSH_TIMEOUT = 4000000  # mikrosekund (4 ms)

# Output
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/workspace/output")
SAVE_VIDEO = os.environ.get("SAVE_VIDEO", "true").lower() == "true"


# ─────── STATISTIKA ───────
class Stats:
    """Pipeline statistikasi — frame, FPS, GPU, yuz soni."""
    def __init__(self):
        self.frame_count = 0
        self.face_count_total = 0
        self.unique_tracks: set[int] = set()
        self.start_time = time.time()
        self.last_log_time = self.start_time
        self.last_log_frame = 0

    def add_frame(self, faces_in_frame: int, track_ids: list[int]):
        self.frame_count += 1
        self.face_count_total += faces_in_frame
        self.unique_tracks.update(track_ids)

    def maybe_log(self, log_every_n_frames: int = 30):
        if self.frame_count % log_every_n_frames != 0:
            return
        now = time.time()
        dt = now - self.last_log_time
        df = self.frame_count - self.last_log_frame
        instant_fps = df / dt if dt > 0 else 0
        avg_fps = self.frame_count / (now - self.start_time)
        print(
            f"[Frame {self.frame_count:>5}] "
            f"FPS: {instant_fps:>5.1f} (avg {avg_fps:>5.1f}) | "
            f"Yuzlar: {self.face_count_total:>5} | "
            f"Unique IDs: {len(self.unique_tracks):>3}",
            flush=True,
        )
        self.last_log_time = now
        self.last_log_frame = self.frame_count

    def final_report(self):
        elapsed = time.time() - self.start_time
        print("\n" + "=" * 60)
        print("📊  YAKUNIY HISOBOT")
        print("=" * 60)
        print(f"Jami kadrlar:        {self.frame_count}")
        print(f"Jami yuz aniqlandi:  {self.face_count_total}")
        print(f"Unique track ID:     {len(self.unique_tracks)}")
        print(f"Umumiy vaqt:         {elapsed:.1f} sekund")
        print(f"O'rtacha FPS:        {self.frame_count / elapsed:.1f}")
        print("=" * 60)


# ─────── FACE CROP UTILITY ───────
def _extract_face_crop_b64(gst_buffer, frame_meta, bbox) -> str:
    """
    Frame surface'idan yuz crop'ini olib base64 JPG ga aylantiradi.

    DeepStream'da NV12/RGBA buffer GPU memory'da turadi.
    pyds.get_nvds_buf_surface() bilan CPU ga ko'chiriladi.
    """
    try:
        n_frame = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)
        # n_frame shape: (height, width, 4) — RGBA
        frame_np = np.array(n_frame, copy=True, order='C')

        # RGBA → BGR (OpenCV format)
        frame_bgr = cv2.cvtColor(frame_np, cv2.COLOR_RGBA2BGR)

        # Bbox koordinata (padding qo'shamiz)
        h, w = frame_bgr.shape[:2]
        pad = 0.2
        x1 = max(0, int(bbox.left - bbox.width * pad))
        y1 = max(0, int(bbox.top - bbox.height * pad))
        x2 = min(w, int(bbox.left + bbox.width * (1 + pad)))
        y2 = min(h, int(bbox.top + bbox.height * (1 + pad)))

        crop = frame_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            return ""

        # JPG ga aylantirib base64
        ok, jpg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return ""
        return base64.b64encode(jpg.tobytes()).decode("ascii")

    except Exception as e:
        # Crop muvaffaqiyatsiz bo'lsa, bo'sh string qaytarib oqimni davom ettiramiz
        return ""


# ─────── METADATA CALLBACK ───────
def make_meta_callback(stats: Stats):
    """
    sink pad'iga ulanadigan probe — har kadrda chaqiriladi.
    DeepStream metadatasidan yuz koordinatalari va track ID ni o'qiydi.
    """
    def callback(pad, info, user_data):
        gst_buffer = info.get_buffer()
        if not gst_buffer:
            return Gst.PadProbeReturn.OK

        batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))
        if not batch_meta:
            return Gst.PadProbeReturn.OK

        l_frame = batch_meta.frame_meta_list
        while l_frame is not None:
            try:
                frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
            except StopIteration:
                break

            faces_in_frame = 0
            track_ids_in_frame: list[int] = []

            # Har bir topilgan obyekt (yuz) bo'yicha
            l_obj = frame_meta.obj_meta_list
            while l_obj is not None:
                try:
                    obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
                except StopIteration:
                    break

                faces_in_frame += 1
                track_id = int(obj_meta.object_id)
                track_ids_in_frame.append(track_id)

                # Bbox + Kafka publish (face crop bilan)
                if _kafka_producer is not None:
                    bbox = obj_meta.rect_params
                    # Frame surface'idan crop olish (GPU → CPU)
                    face_crop_b64 = _extract_face_crop_b64(
                        gst_buffer, frame_meta, bbox
                    )

                    msg = {
                        "ts": time.time(),
                        "camera_id": CAMERA_ID,
                        "frame_id": int(frame_meta.frame_num),
                        "track_id": track_id,
                        "bbox": {
                            "x": float(bbox.left),
                            "y": float(bbox.top),
                            "w": float(bbox.width),
                            "h": float(bbox.height),
                        },
                        "confidence": float(obj_meta.confidence),
                        "face_crop_b64": face_crop_b64,
                    }
                    try:
                        _kafka_producer.send(KAFKA_TOPIC, msg)
                    except Exception as e:
                        if frame_meta.frame_num % 100 == 0:
                            print(f"⚠️  Kafka send xato: {e}")

                try:
                    l_obj = l_obj.next
                except StopIteration:
                    break

            stats.add_frame(faces_in_frame, track_ids_in_frame)
            stats.maybe_log()

            try:
                l_frame = l_frame.next
            except StopIteration:
                break

        return Gst.PadProbeReturn.OK

    return callback


# ─────── PIPELINE QURISH ───────
def build_pipeline(video_path: str, infer_config: str,
                   tracker_config: str, save_output: bool) -> Gst.Pipeline:
    """
    Pipeline:
        filesrc → decodebin → nvstreammux → nvinfer (face)
        → nvtracker → nvvideoconvert → (nvdsosd) → sink
    """
    Gst.init(None)
    pipeline = Gst.Pipeline.new("face-pipeline")
    if not pipeline:
        raise RuntimeError("Pipeline yaratilmadi")

    # 1. Source
    source = Gst.ElementFactory.make("filesrc", "file-source")
    source.set_property("location", video_path)

    # 2. Decoder (NVDEC orqali GPU da)
    decoder = Gst.ElementFactory.make("decodebin", "decoder")

    # 3. Stream muxer (frame'larni batch qiladi)
    streammux = Gst.ElementFactory.make("nvstreammux", "stream-muxer")
    streammux.set_property("batch-size", MUXER_BATCH_SIZE)
    streammux.set_property("width", MUXER_WIDTH)
    streammux.set_property("height", MUXER_HEIGHT)
    streammux.set_property("batched-push-timeout", MUXER_BATCHED_PUSH_TIMEOUT)
    streammux.set_property("live-source", 0)

    # 4. Primary inference (yuz topish)
    pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
    pgie.set_property("config-file-path", infer_config)

    # 5. Tracker
    tracker = Gst.ElementFactory.make("nvtracker", "tracker")
    tracker.set_property("tracker-width", 640)
    tracker.set_property("tracker-height", 384)
    tracker.set_property("ll-lib-file",
                        "/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so")
    tracker.set_property("ll-config-file", tracker_config)

    # 6. Video converter (BBox chizish uchun NV12 → RGBA)
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "nvvidconv")

    # 7. OSD — BBox va text chizadi
    nvosd = Gst.ElementFactory.make("nvdsosd", "nvosd")

    # 8. Sink — fakesink (faqat statistika) yoki fayl
    if save_output:
        # → encoder → mp4 fayl
        nvvidconv2 = Gst.ElementFactory.make("nvvideoconvert", "nvvidconv-out")
        encoder = Gst.ElementFactory.make("nvv4l2h264enc", "encoder")
        encoder.set_property("bitrate", 4000000)
        parser = Gst.ElementFactory.make("h264parse", "parser")
        muxer = Gst.ElementFactory.make("qtmux", "muxer")
        sink = Gst.ElementFactory.make("filesink", "filesink")
        output_path = f"{OUTPUT_DIR}/output_{int(time.time())}.mp4"
        Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
        sink.set_property("location", output_path)
        sink.set_property("sync", 0)
        print(f"💾  Output: {output_path}")
    else:
        sink = Gst.ElementFactory.make("fakesink", "fakesink")
        sink.set_property("sync", 0)

    # Hammasini pipeline'ga qo'shish
    for el in [source, decoder, streammux, pgie, tracker, nvvidconv, nvosd]:
        if not el:
            raise RuntimeError(f"Element yaratilmadi")
        pipeline.add(el)

    if save_output:
        for el in [nvvidconv2, encoder, parser, muxer, sink]:
            pipeline.add(el)
    else:
        pipeline.add(sink)

    # Static linklar
    source.link(decoder)
    # decodebin pad'i dinamik — callback orqali ulanadi
    decoder.connect("pad-added", _on_decoder_pad_added, streammux)

    streammux.link(pgie)
    pgie.link(tracker)
    tracker.link(nvvidconv)
    nvvidconv.link(nvosd)

    if save_output:
        nvosd.link(nvvidconv2)
        nvvidconv2.link(encoder)
        encoder.link(parser)
        parser.link(muxer)
        muxer.link(sink)
    else:
        nvosd.link(sink)

    return pipeline, sink


def _on_decoder_pad_added(decoder, pad, streammux):
    """decodebin video pad'ini streammux'ga ulaydi."""
    caps = pad.get_current_caps()
    if not caps:
        caps = pad.query_caps(None)
    if not caps or not caps.get_size():
        return

    structure = caps.get_structure(0)
    name = structure.get_name()
    if not name.startswith("video"):
        return

    sinkpad = streammux.request_pad_simple("sink_0")
    if not sinkpad:
        print("⚠️  streammux sink pad olinmadi")
        return

    pad.link(sinkpad)


# ─────── MAIN ───────
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nFoydalanish:")
        print("  python3 main.py <video_path> [--no-save]")
        print("\nMisol:")
        print("  python3 main.py /workspace/data/test.mp4")
        sys.exit(1)

    video_path = sys.argv[1]
    save_output = "--no-save" not in sys.argv

    if not Path(video_path).exists():
        print(f"❌  Video topilmadi: {video_path}")
        sys.exit(1)

    infer_config = DEFAULT_INFER_CONFIG
    tracker_config = DEFAULT_TRACKER_CONFIG

    if not Path(infer_config).exists():
        print(f"❌  Infer config topilmadi: {infer_config}")
        sys.exit(1)

    print("=" * 60)
    print("🚀  DeepStream Face Detection POC")
    print("=" * 60)
    print(f"Video:           {video_path}")
    print(f"Infer config:    {infer_config}")
    print(f"Tracker config:  {tracker_config}")
    print(f"Save output:     {save_output}")
    print(f"Output dir:      {OUTPUT_DIR}")
    print("=" * 60)
    print()

    # Pipeline
    pipeline, sink_element = build_pipeline(
        video_path, infer_config, tracker_config, save_output
    )

    # Statistika callback
    stats = Stats()
    sink_pad = sink_element.get_static_pad("sink")
    if sink_pad:
        sink_pad.add_probe(Gst.PadProbeType.BUFFER,
                          make_meta_callback(stats), 0)

    # Bus message handler
    loop = GLib.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()

    def on_message(bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            print("\n✅  Video oxiriga yetdi (EOS)")
            stats.final_report()
            loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"\n❌  XATO: {err}")
            print(f"Debug: {debug}")
            loop.quit()
        elif t == Gst.MessageType.WARNING:
            warn, debug = message.parse_warning()
            print(f"⚠️   Ogohlantirish: {warn}")

    bus.connect("message", on_message)

    # Boshlanish
    pipeline.set_state(Gst.State.PLAYING)
    print("▶️   Pipeline ishga tushdi...\n")

    try:
        loop.run()
    except KeyboardInterrupt:
        print("\n⛔  Ctrl+C bosildi")
        stats.final_report()
    finally:
        pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    main()
