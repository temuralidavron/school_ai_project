#!/usr/bin/env python3
"""
Haqiqiy NVIDIA DeepStream yuz tanish pipeline.

Ishga tushirish:
  python3 main.py --video /data/sinf.mp4
  python3 main.py --rtsp rtsp://cam1 rtsp://cam2 ... --camera-ids 1 2 ...

Arxitektura:
  nvurisrcbin(N) → nvstreammux → nvinfer PGIE(det_10g.engine)
                                → [det_probe]
                               → nvtracker(NvDCF)
                                → [recog_probe → ArcFace → Kafka]
                               → fakesink
"""
import argparse
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ds_main")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DeepStream yuz davomat pipeline")
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("--video",  metavar="PATH", help="Video fayl yo'li")
    grp.add_argument("--rtsp",   nargs="+", metavar="URL", help="RTSP URL(lar)")
    p.add_argument("--camera-ids", nargs="+", type=int, metavar="ID",
                   help="Har manba uchun camera_id (tartibda)")
    return p.parse_args()


def main():
    args = parse_args()

    # ── Manbalar ──────────────────────────────────────────────────────────────
    if args.video:
        if not os.path.exists(args.video):
            log.error("Video topilmadi: %s", args.video)
            sys.exit(1)
        sources = [f"file://{os.path.abspath(args.video)}"]
    else:
        sources = args.rtsp

    camera_ids_list = args.camera_ids or list(range(1, len(sources) + 1))
    if len(camera_ids_list) != len(sources):
        log.error("--camera-ids soni manba soniga teng bo'lishi kerak")
        sys.exit(1)
    camera_id_map = {i: cid for i, cid in enumerate(camera_ids_list)}

    log.info("=" * 60)
    log.info("DeepStream Face Attendance Pipeline")
    log.info("  Manbalar (%d): %s", len(sources), sources)
    log.info("  Kamera IDlar: %s", camera_id_map)
    log.info("=" * 60)

    # ── Modellar yuklash ──────────────────────────────────────────────────────
    from pipeline.config import MODELS_DIR, GPU_ID, KAFKA_BOOTSTRAP, KAFKA_TOPIC
    from pipeline.det10g_runner       import Det10gRunner
    from pipeline.arcface_runner      import ArcFaceRunner
    from pipeline.landmark3d68_runner import Landmark3d68Runner
    from pipeline.kafka_client        import KafkaClient

    det_model      = os.path.join(MODELS_DIR, "buffalo_l", "det_10g.onnx")
    arcface_model  = os.path.join(MODELS_DIR, "buffalo_l", "w600k_r50.onnx")
    landmark_model = os.path.join(MODELS_DIR, "buffalo_l", "1k3d68.onnx")

    for path in (det_model, arcface_model, landmark_model):
        if not os.path.exists(path):
            log.error("Model topilmadi: %s", path)
            sys.exit(1)

    log.info("Modellar yuklanmoqda (GPU %d)...", GPU_ID)
    detector  = Det10gRunner(det_model,       gpu_id=GPU_ID)
    landmark  = Landmark3d68Runner(landmark_model, gpu_id=GPU_ID)
    arcface   = ArcFaceRunner(arcface_model,   gpu_id=GPU_ID)
    kafka     = KafkaClient(KAFKA_BOOTSTRAP, KAFKA_TOPIC)

    probe_data = {
        "detector":   detector,
        "landmark":   landmark,
        "arcface":    arcface,
        "kafka":      kafka,
        "camera_ids": camera_id_map,
        "trackers":   {},  # source_id → IouTracker (appsink_proc da yaratiladi)
    }

    # ── Pipeline ──────────────────────────────────────────────────────────────
    from pipeline.pipeline_builder import build
    # Video fayl: EOS'da loop. RTSP: EOS bo'lmaydi, loop kerak emas.
    pipeline, loop = build(sources, probe_data, loop_video=bool(args.video))

    # ── MJPEG server ──────────────────────────────────────────────────────────
    from pipeline.mjpeg_server import start as mjpeg_start
    mjpeg_start(port=8554)

    import gi; gi.require_version("Gst", "1.0")
    from gi.repository import Gst as _Gst
    pipeline.set_state(_Gst.State.PLAYING)

    log.info("Pipeline ishga tushdi — Ctrl+C bilan to'xtating")
    log.info("Vizual stream: http://localhost:8554/mjpeg")

    try:
        loop.run()
    except KeyboardInterrupt:
        log.info("To'xtatildi")
    finally:
        pipeline.set_state(_Gst.State.NULL)
        kafka.flush()
        log.info("Yopildi")


if __name__ == "__main__":
    main()
