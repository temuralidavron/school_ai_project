"""
Video fayl asosida yuz tanish sinovi.
GStreamer / Docker / Kafka kerak emas.

Ishga tushirish:
    python3 test_video.py
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

import cv2
import numpy as np

MODELS_DIR  = os.path.expanduser("~/.insightface/models/buffalo_l")
VIDEO_PATH  = "deepstream/data/sinf.mp4"
GPU_ID      = 0  # host da CUDA yo'q → CPU ishlatiladi (Docker da GPU ishlatiladi)
FRAME_SKIP  = 15   # har 15-kadrni tekshir (≈ har yarim sekund 30fps da)
MAX_FRAMES  = 300  # 300 kadr tekshir, keyin to'xtat

DET_THR     = 0.45
MIN_FACE_PX = 20

from deepstream_v2.pipeline.det10g_runner       import Det10gRunner
from deepstream_v2.pipeline.landmark3d68_runner import Landmark3d68Runner
from deepstream_v2.pipeline.arcface_runner      import ArcFaceRunner
from deepstream_v2.pipeline.face_align          import align

def main():
    print("=" * 60)
    print("  Video sinov — yuz topish + embedding")
    print("=" * 60)

    # ── Modellar ──────────────────────────────────────────────────────────────
    det_path  = os.path.join(MODELS_DIR, "det_10g.onnx")
    lmk_path  = os.path.join(MODELS_DIR, "1k3d68.onnx")
    arc_path  = os.path.join(MODELS_DIR, "w600k_r50.onnx")

    for p in (det_path, lmk_path, arc_path):
        if not os.path.exists(p):
            print(f"[XATO] Model topilmadi: {p}")
            sys.exit(1)

    print("Modellar yuklanmoqda (GPU)...")
    t0 = time.time()
    detector = Det10gRunner(det_path,  gpu_id=GPU_ID)
    landmark = Landmark3d68Runner(lmk_path, gpu_id=GPU_ID)
    arcface  = ArcFaceRunner(arc_path,  gpu_id=GPU_ID)
    print(f"Modellar yuklandi: {time.time()-t0:.1f}s")

    # ── Video ─────────────────────────────────────────────────────────────────
    if not os.path.exists(VIDEO_PATH):
        print(f"[XATO] Video topilmadi: {VIDEO_PATH}")
        sys.exit(1)

    cap = cv2.VideoCapture(VIDEO_PATH)
    total_video = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps_video   = cap.get(cv2.CAP_PROP_FPS)
    print(f"Video: {VIDEO_PATH}")
    print(f"Jami kadr: {total_video} | FPS: {fps_video:.1f} | "
          f"Davomiyligi: {total_video/fps_video:.0f}s")
    print(f"Tekshiriladigan kadrlar: har {FRAME_SKIP}-chi, max {MAX_FRAMES} ta")
    print("-" * 60)

    # ── Statistika ────────────────────────────────────────────────────────────
    stats = {
        "frames_checked": 0,
        "frames_with_face": 0,
        "total_faces": 0,
        "max_faces_in_frame": 0,
        "inference_times": [],
    }

    frame_num = 0
    checked   = 0

    while checked < MAX_FRAMES:
        ret, frame = cap.read()
        if not ret:
            break
        frame_num += 1
        if frame_num % FRAME_SKIP != 0:
            continue

        checked += 1
        t_start = time.time()

        # ── Yuz topish ────────────────────────────────────────────────────────
        dets = detector.detect(frame, score_thr=DET_THR, min_px=MIN_FACE_PX)
        n_faces = len(dets)

        # ── Landmark + Embedding (topilgan yuzlar uchun) ─────────────────────
        embeddings = []
        if dets:
            crops = []
            for d in dets:
                kps5 = landmark.get_5pts(frame, d["bbox"])
                if kps5 is not None:
                    crops.append(align(frame, kps5))
                else:
                    crops.append(None)

            valid_crops = [c for c in crops if c is not None]
            if valid_crops:
                embeddings = arcface.get_embeddings(valid_crops)

        t_ms = (time.time() - t_start) * 1000

        # ── Statistika yangilash ──────────────────────────────────────────────
        stats["frames_checked"] += 1
        stats["inference_times"].append(t_ms)
        if n_faces > 0:
            stats["frames_with_face"] += 1
            stats["total_faces"] += n_faces
            if n_faces > stats["max_faces_in_frame"]:
                stats["max_faces_in_frame"] = n_faces

        # ── Progress ──────────────────────────────────────────────────────────
        if checked % 20 == 0 or n_faces > 0:
            emb_norm = float(np.linalg.norm(embeddings[0])) if len(embeddings) > 0 else 0
            print(
                f"Kadr #{frame_num:5d} | "
                f"Yuzlar: {n_faces} | "
                f"Embedding: {'ok (norm=%.3f)' % emb_norm if len(embeddings) > 0 else '-':20s} | "
                f"{t_ms:5.1f}ms"
            )

    cap.release()

    # ── Yakuniy natija ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  NATIJA")
    print("=" * 60)
    times = stats["inference_times"]
    print(f"Tekshirilgan kadrlar    : {stats['frames_checked']}")
    print(f"Yuz topilgan kadrlar    : {stats['frames_with_face']}")
    print(f"Jami topilgan yuzlar    : {stats['total_faces']}")
    print(f"Bir kadrda eng ko'p yuz : {stats['max_faces_in_frame']}")
    if times:
        print(f"O'rtacha inference vaqti: {sum(times)/len(times):.1f}ms")
        print(f"Eng tez / eng sekin     : {min(times):.1f}ms / {max(times):.1f}ms")

    if stats["frames_with_face"] > 0:
        pct = stats["frames_with_face"] / stats["frames_checked"] * 100
        print(f"\nYUZ TOPISH: {pct:.0f}% kadrlarda yuz bor")
        print("Holat: OK — pipeline ishlayapti")
    else:
        print("\nOGOHLANTIRISH: Hech bir kadrda yuz topilmadi")
        print("Tekshirish: DET_THRESHOLD ni pasaytiring yoki boshqa video ishlating")

    print("=" * 60)


if __name__ == "__main__":
    main()
