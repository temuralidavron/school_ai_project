"""
DeepStream Kafka consumer — MAVJUD services'larni qayta ishlatadi.

JARAYON:
    DeepStream container yuzni topadi, face crop'ni Kafka'ga yuboradi.
    Bu command Kafka'dan o'qib mavjud RecognitionEventService bilan
    davomat yozadi (oddiy stream pipeline'i bilan bir xil natija).

Ishga tushirish (Docker compose orqali avtomatik):
    python manage.py kafka_consumer

Sozlamalar (.env):
    KAFKA_BOOTSTRAP   — Kafka broker (default: kafka:9092)
    KAFKA_TOPIC       — Topic nomi (default: deepstream-faces)
    KAFKA_GROUP_ID    — Consumer guruh (default: attendance-consumer)
    USE_DEEPSTREAM    — True bo'lsa bu consumer ishlaydi
"""
import base64
import json
import logging
import os
import time
from typing import Optional

import cv2
import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "DeepStream face crop'larini Kafka'dan o'qib davomat yozadi"

    def add_arguments(self, parser):
        parser.add_argument(
            "--bootstrap",
            default=os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092"),
            help="Kafka broker manzili",
        )
        parser.add_argument(
            "--topic",
            default=os.environ.get("KAFKA_TOPIC", "deepstream-faces"),
            help="Kafka topic",
        )
        parser.add_argument(
            "--group-id",
            default=os.environ.get("KAFKA_GROUP_ID", "attendance-consumer"),
        )

    def handle(self, *args, **options):
        # Lazy imports — Django setup tugagandan keyin
        from kafka import KafkaConsumer

        from apps.attendance.services import (
            LiveFrameProcessorService,
            RecognitionEventService,
            _get_lesson_embedding_cache,
        )
        from apps.face_data.services import get_face_app

        bootstrap = options["bootstrap"]
        topic = options["topic"]
        group_id = options["group_id"]

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(
            self.style.SUCCESS(f"  DeepStream Kafka Consumer")
        )
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(f"  Kafka:     {bootstrap}")
        self.stdout.write(f"  Topic:     {topic}")
        self.stdout.write(f"  Group:     {group_id}")
        self.stdout.write(self.style.SUCCESS("=" * 60))

        # AI modelni avvaldan yuklash (birinchi xabarda kechikishni kamaytirish)
        logger.info("Pre-loading face app...")
        face_app = get_face_app()
        logger.info("Face app ready")

        recognition_service = RecognitionEventService()
        processor = LiveFrameProcessorService()

        # Kafka ulanish (qayta urinish bilan)
        consumer = self._connect_kafka(bootstrap, topic, group_id)

        # Statistika
        stats = ConsumerStats()

        try:
            for msg in consumer:
                stats.total += 1
                try:
                    self._process_message(
                        msg.value, face_app, processor, recognition_service, stats
                    )
                except Exception as e:
                    stats.errors += 1
                    logger.error("Process xato: %s", e, exc_info=True)

                if stats.total % 100 == 0:
                    stats.print_summary(self.stdout, self.style)

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nCtrl+C"))
        finally:
            consumer.close()
            stats.print_summary(self.stdout, self.style)

    def _connect_kafka(self, bootstrap, topic, group_id):
        from kafka import KafkaConsumer

        for attempt in range(30):
            try:
                consumer = KafkaConsumer(
                    topic,
                    bootstrap_servers=bootstrap,
                    group_id=group_id,
                    auto_offset_reset="latest",
                    enable_auto_commit=True,
                    value_deserializer=lambda v: json.loads(v.decode("utf-8")),
                    consumer_timeout_ms=1000 * 60 * 60,
                )
                self.stdout.write(self.style.SUCCESS("Kafka ulandi"))
                return consumer
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"Kafka kutilmoqda ({attempt + 1}/30): {e}")
                )
                time.sleep(2)
        raise RuntimeError("Kafka ga ulanib bo'lmadi")

    def _process_message(
        self, data, face_app, processor, recognition_service, stats
    ):
        """
        DeepStream xabarini qayta ishlash.
        Format: {ts, frame_id, track_id, bbox, confidence, face_crop_b64, camera_id}
        """
        camera_id = data.get("camera_id")
        if camera_id is None:
            stats.skipped_no_camera += 1
            return

        crop_b64 = data.get("face_crop_b64", "")
        if not crop_b64:
            stats.skipped_no_crop += 1
            return

        # Crop decode
        try:
            crop_bytes = base64.b64decode(crop_b64)
            crop_arr = np.frombuffer(crop_bytes, dtype=np.uint8)
            crop_bgr = cv2.imdecode(crop_arr, cv2.IMREAD_COLOR)
        except Exception:
            stats.decode_errors += 1
            return

        if crop_bgr is None or crop_bgr.size == 0:
            stats.decode_errors += 1
            return

        # Embedding chiqarish — MAVJUD modeldan
        faces = face_app.get(crop_bgr)
        if not faces:
            stats.no_face_in_crop += 1
            return

        best = max(
            faces,
            key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
        )
        embedding = best.embedding

        # Track key — DeepStream track_id ni ishlatamiz
        track_id = data.get("track_id", -1)
        frame_id = data.get("frame_id", -1)
        track_key = f"deepstream_cam{camera_id}_track{track_id}"

        # Crop ni vaqtinchalik faylga saqlash (RecognitionEventService talab qiladi)
        # NOTE: kelajakda numpy to'g'ridan-to'g'ri uzatish optimizatsiya qilinishi mumkin
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name
        cv2.imwrite(tmp_path, crop_bgr)

        try:
            # MAVJUD service'ni chaqiramiz — bir xil davomat yozish mantig'i
            accept_threshold = getattr(settings, "AI_ACCEPT_THRESHOLD", 0.55)
            review_threshold = getattr(settings, "AI_REVIEW_THRESHOLD", 0.42)

            result = recognition_service.recognize_track_and_record_by_embedding(
                track_key=track_key,
                image_path=tmp_path,
                query_embedding=embedding,
                organization_id=None,  # Camera'dan olinadi
                camera_id=camera_id,
                bbox=(
                    int(data.get("bbox", {}).get("x", 0)),
                    int(data.get("bbox", {}).get("y", 0)),
                    int(
                        data.get("bbox", {}).get("x", 0)
                        + data.get("bbox", {}).get("w", 0)
                    ),
                    int(
                        data.get("bbox", {}).get("y", 0)
                        + data.get("bbox", {}).get("h", 0)
                    ),
                ),
                accept_threshold=accept_threshold,
                review_threshold=review_threshold,
                save_base64=True,
                frontal_frames_used=1,
            )

            status = result.get("status", "")
            if status == "recorded_and_locked":
                stats.accepted += 1
                best_match = result.get("best_match", {})
                logger.info(
                    "DAVOMAT cam=%s %s sim=%.3f",
                    camera_id,
                    best_match.get("full_name", ""),
                    best_match.get("best_score", 0),
                )
            elif status == "skipped_locked_after_search":
                stats.skipped_locked += 1
            elif status == "skipped_before_recognition":
                stats.skipped_before += 1
            elif status == "rejected":
                stats.rejected += 1

        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


class ConsumerStats:
    def __init__(self):
        self.total = 0
        self.accepted = 0
        self.rejected = 0
        self.skipped_locked = 0
        self.skipped_before = 0
        self.skipped_no_camera = 0
        self.skipped_no_crop = 0
        self.no_face_in_crop = 0
        self.decode_errors = 0
        self.errors = 0
        self.start = time.time()

    def print_summary(self, stdout, style):
        elapsed = time.time() - self.start
        rate = self.total / elapsed if elapsed > 0 else 0
        stdout.write("")
        stdout.write(style.SUCCESS("-" * 60))
        stdout.write(style.SUCCESS(f"Stats ({elapsed:.0f}s, {rate:.1f} msg/s)"))
        stdout.write(style.SUCCESS("-" * 60))
        stdout.write(f"  total:           {self.total}")
        stdout.write(f"  accepted:        {self.accepted}")
        stdout.write(f"  rejected:        {self.rejected}")
        stdout.write(f"  skipped locked:  {self.skipped_locked}")
        stdout.write(f"  skipped before:  {self.skipped_before}")
        stdout.write(f"  no face in crop: {self.no_face_in_crop}")
        stdout.write(f"  decode errors:   {self.decode_errors}")
        stdout.write(f"  errors:          {self.errors}")
        stdout.write(style.SUCCESS("-" * 60))
