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
import tempfile
import time

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

# /app/ds_data/track_names.json — pipeline MJPEG uchun ism ko'rsatadi
_NAMES_FILE = os.path.join(
    os.environ.get("DS_DATA_DIR", "/app/ds_data"),
    "track_names.json",
)
_track_names: dict[int, str] = {}   # {track_id: full_name}
_NAMES_MAX = 300                     # xotira nazorati


def _save_track_name(track_id: int, full_name: str, pinfl: str = "", score: float | None = None) -> None:
    """track_id → {name, pinfl, score} ni faylga yozadi (pipeline MJPEG vizualizatsiya uchun).
    score = o'xshashlik (0..1) → foizga aylantirilib rectangle'da ko'rsatiladi."""
    entry = {"name": full_name, "pinfl": pinfl}
    if score is not None:
        entry["score"] = round(float(score) * 100)
    _track_names[track_id] = entry
    if len(_track_names) > _NAMES_MAX:
        for k in list(_track_names)[:50]:
            _track_names.pop(k, None)
    try:
        os.makedirs(os.path.dirname(_NAMES_FILE), exist_ok=True)
        with open(_NAMES_FILE, "w", encoding="utf-8") as f:
            json.dump(_track_names, f, ensure_ascii=False)
    except OSError:
        pass


# camera_id -> organization_id (comparison sahifa org filtri uchun;
# busiz RecognitionEvent.organization_id=None bo'lib jadval bo'sh chiqadi)
_org_cache: dict = {}


def _org_for_camera(camera_id):
    if camera_id in _org_cache:
        return _org_cache[camera_id]
    org = None
    try:
        from apps.integrations.models import ExternalClassroom
        cr = (ExternalClassroom.objects.filter(camera_id=camera_id)
              .select_related("organization").first())
        if cr and cr.organization:
            org = cr.organization.organization_id
    except Exception:
        pass
    # None keshlanmaydi: consumer classroom sync'dan oldin ko'tarilgan bo'lsa
    # keyingi xabarda qayta uriniladi (aks holda restart'gacha None qolardi)
    if org is not None:
        _org_cache[camera_id] = org
    return org


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
        )

        bootstrap = options["bootstrap"]
        topic = options["topic"]
        group_id = options["group_id"]

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("  DeepStream Kafka Consumer (Phase 2: embedding)"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(f"  Kafka:     {bootstrap}")
        self.stdout.write(f"  Topic:     {topic}")
        self.stdout.write(f"  Group:     {group_id}")
        self.stdout.write(self.style.SUCCESS("=" * 60))

        recognition_service = RecognitionEventService()
        processor = LiveFrameProcessorService()

        # F2 L2: run-sarlavha — jurnal qatorlari qaysi konfiguratsiyada
        # yozilganini belgilaydi (busiz keyin tahlil qilib bo'lmaydi)
        from django.conf import settings as _settings
        from apps.attendance.sighting_log import log_run
        from apps.face_data import decision as _decision
        log_run(
            accept=getattr(_settings, "AI_ACCEPT_THRESHOLD", 0.55),
            review=getattr(_settings, "AI_REVIEW_THRESHOLD", 0.42),
            b5_margin=_decision.B5_ENABLED,
            b5=[_decision.FLOOR1, _decision.MARGIN1,
                _decision.FLOOR2, _decision.MARGIN2],
        )

        # Kafka ulanish (qayta urinish bilan)
        consumer = self._connect_kafka(bootstrap, topic, group_id)

        # Statistika
        stats = ConsumerStats()

        try:
            for msg in consumer:
                stats.total += 1
                try:
                    self._process_message(
                        msg.value, processor, recognition_service, stats
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
        self, data, processor, recognition_service, stats
    ):
        """
        DeepStream xabarini qayta ishlash (Phase 2: embedding to'g'ridan-to'g'ri).
        Format: {ts, frame_id, track_id, bbox, confidence, embedding, camera_id}
        """
        camera_id = data.get("camera_id")
        if camera_id is None:
            stats.skipped_no_camera += 1
            return

        # Phase 2: embedding to'g'ridan-to'g'ri DeepStream dan keladi
        embedding_list = data.get("embedding")
        if not embedding_list:
            # Phase 1 xabarlari (eski format) — o'tkazib yuboramiz
            stats.skipped_no_crop += 1
            return

        try:
            embedding = np.array(embedding_list, dtype=np.float32)
        except Exception:
            stats.decode_errors += 1
            return

        track_id   = data.get("track_id", -1)
        session_id = data.get("session_id", 0)  # har pipeline restart uchun unikal
        track_key = f"deepstream_cam{camera_id}_t{track_id}_s{session_id}"
        bbox_d = data.get("bbox", {})
        bbox = (
            int(bbox_d.get("x", 0)),
            int(bbox_d.get("y", 0)),
            int(bbox_d.get("x", 0) + bbox_d.get("w", 0)),
            int(bbox_d.get("y", 0) + bbox_d.get("h", 0)),
        )

        accept_threshold = getattr(settings, "AI_ACCEPT_THRESHOLD", 0.55)
        review_threshold = getattr(settings, "AI_REVIEW_THRESHOLD", 0.42)

        # SKUD push uchun face_crop (base64 JPEG) — pipeline dan keladi
        face_crop_b64 = data.get("face_crop")

        # face_crop ni vaqtinchalik fayl orqali berish — _push_to_skud thread race yo'q
        tmp_path = ""
        if face_crop_b64:
            try:
                jpg_bytes = base64.b64decode(face_crop_b64)
                tmp_fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
                with os.fdopen(tmp_fd, "wb") as f:
                    f.write(jpg_bytes)
            except Exception:
                tmp_path = ""

        try:
            result = recognition_service.recognize_track_and_record_by_embedding(
                track_key=track_key,
                image_path=tmp_path,
                query_embedding=embedding,
                organization_id=_org_for_camera(camera_id),
                camera_id=camera_id,
                bbox=bbox,
                accept_threshold=accept_threshold,
                review_threshold=review_threshold,
                save_base64=bool(tmp_path),
                frontal_frames_used=1,
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        status     = result.get("status", "")
        best_match = result.get("best_match") or {}
        best_score = best_match.get("best_score", 0) or 0

        # Rectangle da ism DARHOL ko'rinsin — review threshold dan yuqori bo'lsa yetarli
        if best_match and best_score >= review_threshold:
            _save_track_name(
                track_id,
                best_match.get("full_name", ""),
                str(best_match.get("pinfl", "") or ""),
                best_score,
            )

        if status == "recorded_and_locked":
            stats.accepted += 1
            logger.info(
                "DAVOMAT cam=%s %s pinfl=%s sim=%.3f",
                camera_id,
                best_match.get("full_name", ""),
                best_match.get("pinfl", ""),
                best_score,
            )
        elif status == "skipped_locked_after_search":
            stats.skipped_locked += 1
        elif status == "skipped_before_recognition":
            stats.skipped_before += 1
        elif status == "rejected":
            stats.rejected += 1
            if stats.rejected <= 5 or stats.rejected % 200 == 0:
                logger.warning(
                    "REJECTED cam=%s track=%s best_score=%.4f best_name=%s",
                    camera_id, track_id,
                    best_score or best_match.get("effective_score", 0),
                    best_match.get("full_name", "N/A"),
                )


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
