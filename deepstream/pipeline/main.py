#!/usr/bin/env python3
"""
Face detection + recognition pipeline — InsightFace buffalo_l + Kafka producer.

Oqim (Phase 2):
  video.mp4 → OpenCV kadr → InsightFace (det + recognition)
            → embedding (512 float) → Kafka
  Kafka → kafka_consumer (Django) → pgvector qidiruv → davomat yozuvi

Avvalgi (Phase 1) bilan farqi:
  - crop/JPEG yuborilmaydi (bandwidth kam, "no face" muammo yo'q)
  - embedding to'g'ridan-to'g'ri Kafka'ga → kafka_consumer qayta detect qilmaydi
"""
import json
import logging
import os
import sys
import time
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

KAFKA_BOOTSTRAP      = os.environ.get("KAFKA_BOOTSTRAP", "")
KAFKA_TOPIC          = os.environ.get("KAFKA_TOPIC", "deepstream-faces")
CAMERA_ID            = int(os.environ.get("CAMERA_ID", "1"))
FRAME_SKIP           = int(os.environ.get("FRAME_SKIP", "25"))
MIN_FACE_SIZE        = int(os.environ.get("MIN_FACE_SIZE", "40"))
MAX_TRACK_AGE        = int(os.environ.get("MAX_TRACK_AGE", "30"))
# Bir track uchun embedding qayta yuborishdan oldin kutish (soniya)
# Tanilgan track uchun GPU/Kafka behuda sarflanmaydi
TRACK_SEND_COOLDOWN  = int(os.environ.get("TRACK_SEND_COOLDOWN", "10"))
# Katta kadrda kichik yuzlarni aniqlash uchun yuqori det_size
DET_SIZE_FULL        = int(os.environ.get("DET_SIZE_FULL", "1280"))
DET_SIZE_CROP        = int(os.environ.get("DET_SIZE_CROP", "320"))


# ─── Kafka producer ───────────────────────────────────────────────────────────
def _make_producer():
    if not KAFKA_BOOTSTRAP:
        log.warning("KAFKA_BOOTSTRAP yo'q — Kafka off (faqat log)")
        return None
    try:
        from kafka import KafkaProducer
        for attempt in range(15):
            try:
                p = KafkaProducer(
                    bootstrap_servers=KAFKA_BOOTSTRAP,
                    value_serializer=lambda v: json.dumps(v).encode(),
                    acks=1,
                    linger_ms=10,
                )
                log.info("Kafka ulandi: %s", KAFKA_BOOTSTRAP)
                return p
            except Exception as e:
                log.warning("Kafka kutilmoqda (%d/15): %s", attempt + 1, e)
                time.sleep(2)
    except ImportError:
        log.warning("kafka-python o'rnatilmagan")
    return None


# ─── Centroid tracker ─────────────────────────────────────────────────────────
class CentroidTracker:
    """Yuz markazlari asosida oddiy track ID berish."""

    def __init__(self, max_age: int = MAX_TRACK_AGE):
        self.next_id = 0
        self.max_age = max_age
        self._objects: OrderedDict[int, tuple[int, int]] = OrderedDict()
        self._ages: dict[int, int] = {}

    def update(self, bboxes: list[tuple]) -> list[int]:
        """bboxes: [(x1,y1,x2,y2),...] → track_ids (bir xil tartibda)"""
        # Ko'rinmaganlarni qartaytirish
        for oid in list(self._ages):
            self._ages[oid] += 1
            if self._ages[oid] > self.max_age:
                del self._objects[oid]
                del self._ages[oid]

        if not bboxes:
            return []

        centroids = [((x1 + x2) // 2, (y1 + y2) // 2) for x1, y1, x2, y2 in bboxes]

        if not self._objects:
            ids = []
            for c in centroids:
                self._objects[self.next_id] = c
                self._ages[self.next_id] = 0
                ids.append(self.next_id)
                self.next_id += 1
            return ids

        obj_ids = list(self._objects.keys())
        obj_cents = list(self._objects.values())

        # Masofalar matritsasi
        D = np.hypot(
            np.array([c[0] for c in obj_cents])[:, None] - np.array([c[0] for c in centroids]),
            np.array([c[1] for c in obj_cents])[:, None] - np.array([c[1] for c in centroids]),
        )

        assigned_bbox: dict[int, int] = {}  # bbox_idx → obj_id
        used_rows, used_cols = set(), set()

        for _ in range(min(len(obj_ids), len(centroids))):
            if D.size == 0:
                break
            r, c = np.unravel_index(D.argmin(), D.shape)
            if D[r, c] > 160:  # 160 pikseldan uzoq — yangi ID
                break
            if r in used_rows or c in used_cols:
                D[r, :] = 1e9
                D[:, c] = 1e9
                continue
            obj_id = obj_ids[r]
            self._objects[obj_id] = centroids[c]
            self._ages[obj_id] = 0
            assigned_bbox[c] = obj_id
            used_rows.add(r)
            used_cols.add(c)
            D[r, :] = 1e9
            D[:, c] = 1e9

        # Yangi yuzlar uchun yangi ID
        for i, c in enumerate(centroids):
            if i not in assigned_bbox:
                self._objects[self.next_id] = c
                self._ages[self.next_id] = 0
                assigned_bbox[i] = self.next_id
                self.next_id += 1

        return [assigned_bbox.get(i, -1) for i in range(len(bboxes))]


# ─── Statistika ───────────────────────────────────────────────────────────────
class Stats:
    def __init__(self):
        self.frames = self.processed = self.faces = self.sent = 0
        self.start = time.time()
        self._last_t = self.start
        self._last_p = 0

    def frame(self, processed: bool, faces: int, sent: int):
        self.frames += 1
        if processed:
            self.processed += 1
        self.faces += faces
        self.sent += sent
        if self.processed % 30 == 0 and processed:
            now = time.time()
            fps = (self.processed - self._last_p) / max(now - self._last_t, 0.001)
            log.info("Frame %5d (processed %4d) | FPS %.1f | Yuz %4d | Kafka %4d",
                     self.frames, self.processed, fps, self.faces, self.sent)
            self._last_t, self._last_p = now, self.processed

    def final(self):
        elapsed = time.time() - self.start
        log.info("=" * 55)
        log.info("YAKUNIY HISOBOT")
        log.info("  Jami kadrlar:    %d", self.frames)
        log.info("  Ishlangan:       %d", self.processed)
        log.info("  Yuz topildi:     %d", self.faces)
        log.info("  Kafka yuborildi: %d", self.sent)
        log.info("  Umumiy vaqt:     %.1f s", elapsed)
        log.info("  O'rtacha FPS:    %.1f", self.processed / max(elapsed, 1))
        log.info("=" * 55)


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Foydalanish: python3 main.py <video_path>")
        sys.exit(1)

    video_path = sys.argv[1]
    if not Path(video_path).exists():
        log.error("Video topilmadi: %s", video_path)
        sys.exit(1)

    log.info("=" * 55)
    log.info("Face Detection Pipeline")
    log.info("  Video:      %s", video_path)
    log.info("  Camera ID:  %d", CAMERA_ID)
    log.info("  Kafka:      %s", KAFKA_BOOTSTRAP or "off")
    log.info("  Frame skip: %d", FRAME_SKIP)
    log.info("=" * 55)

    from insightface.app import FaceAnalysis
    _providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]

    # Katta kadrda kichik yuzlarni topish — yuqori det_size
    log.info("InsightFace detector yuklanmoqda (det_size=%d)...", DET_SIZE_FULL)
    detector = FaceAnalysis(
        name="buffalo_l",
        allowed_modules=["detection"],
        providers=_providers,
    )
    detector.prepare(ctx_id=0, det_size=(DET_SIZE_FULL, DET_SIZE_FULL))

    # Crop ustida embedding — kichikroq det_size yetarli (yuz katta bo'ladi)
    log.info("InsightFace recognizer yuklanmoqda (det_size=%d)...", DET_SIZE_CROP)
    recognizer = FaceAnalysis(
        name="buffalo_l",
        allowed_modules=["detection", "recognition"],
        providers=_providers,
    )
    recognizer.prepare(ctx_id=0, det_size=(DET_SIZE_CROP, DET_SIZE_CROP))
    log.info("InsightFace tayyor: detector(%d) + recognizer(%d)", DET_SIZE_FULL, DET_SIZE_CROP)

    producer = _make_producer()
    tracker = CentroidTracker()
    stats = Stats()
    # Track uchun oxirgi yuborish vaqti — qayta yuborishdan oldin TRACK_SEND_COOLDOWN soniya kutamiz
    track_last_sent: dict[int, float] = {}

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log.error("Video ochilmadi")
        sys.exit(1)

    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps_v = cap.get(cv2.CAP_PROP_FPS) or 25.0
    log.info("Video: %.1f FPS, %d kadr (~%.0f daqiqa)", fps_v, total, total / fps_v / 60)

    frame_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            frame_idx += 1
            if frame_idx % FRAME_SKIP != 0:
                stats.frame(processed=False, faces=0, sent=0)
                continue

            # Katta kadrda yuz topish — yuqori det_size bilan
            faces = detector.get(frame)
            h_img, w_img = frame.shape[:2]
            now_ts = time.time()

            bboxes = []
            valid_faces = []
            for f in faces:
                x1, y1, x2, y2 = f.bbox.astype(int)
                if (x2 - x1) < MIN_FACE_SIZE or (y2 - y1) < MIN_FACE_SIZE:
                    continue
                bboxes.append((x1, y1, x2, y2))
                valid_faces.append(f)

            track_ids = tracker.update(bboxes)
            sent = 0

            for i, (x1, y1, x2, y2) in enumerate(bboxes):
                tid = track_ids[i] if i < len(track_ids) else -1

                # Cooldown: bu track yaqinda yuborilgan bo'lsa o'tkazib yuboramiz
                # (tanilgan yoki rad etilgan bo'lsin — GPU/Kafka tejaymiz)
                if now_ts - track_last_sent.get(tid, 0) < TRACK_SEND_COOLDOWN:
                    continue

                # Yuz crop — katta padding alignment uchun yaxshiroq
                px = int((x2 - x1) * 0.6)
                py = int((y2 - y1) * 0.6)
                crop = frame[
                    max(0, y1 - py):min(h_img, y2 + py),
                    max(0, x1 - px):min(w_img, x2 + px),
                ]
                if crop.size == 0:
                    continue

                # Crop ustida recognition — embedding olish
                crop_faces = recognizer.get(crop)
                if not crop_faces:
                    continue

                best_face = max(
                    crop_faces,
                    key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
                )
                if best_face.embedding is None:
                    continue

                msg = {
                    "ts": time.time(),
                    "camera_id": CAMERA_ID,
                    "frame_id": frame_idx,
                    "track_id": tid,
                    "bbox": {
                        "x": float(x1), "y": float(y1),
                        "w": float(x2 - x1), "h": float(y2 - y1),
                    },
                    "confidence": float(face.det_score),
                    "embedding": best_face.embedding.tolist(),
                }

                if producer:
                    try:
                        producer.send(KAFKA_TOPIC, msg)
                        sent += 1
                        track_last_sent[tid] = now_ts
                    except Exception as e:
                        if frame_idx % 500 == 0:
                            log.warning("Kafka xato: %s", e)

            stats.frame(processed=True, faces=len(bboxes), sent=sent)

    except KeyboardInterrupt:
        log.info("To'xtatildi (Ctrl+C)")
    finally:
        cap.release()
        if producer:
            producer.flush()
            log.info("Kafka producer yopildi")
        stats.final()


if __name__ == "__main__":
    main()
