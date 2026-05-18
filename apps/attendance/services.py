import base64
import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError

import cv2
import numpy as np
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from apps.attendance.models import AttendanceLock, LessonAttendance, RecognitionEvent, TrackSession
from apps.cameras.models import Camera
from apps.face_data.services import LessonEmbeddingCache, RecognitionSearchService, get_face_app, detect_faces

logger = logging.getLogger(__name__)

_ROI_CACHE: dict[int, object] = {}
_ROI_CACHE_TIME: dict[int, float] = {}
_ROI_CACHE_TTL = 60.0
_ROI_CACHE_LOCK = threading.Lock()

# Frontal frame accumulation — sinf xonasi uchun 1 ta yetarli (tezlik uchun)
_FRONTAL_STORE: dict[str, list] = {}
_FRONTAL_STORE_LOCK = threading.Lock()
_FRONTAL_STORE_TIMESTAMPS: dict[str, float] = {}
_FRONTAL_STORE_TTL = 60.0   # 60s ko'rinmagan track key o'chiriladi
# .env orqali sozlanadi (default = hozirgi xatti-harakat: 1)
try:
    from django.conf import settings as _dj_settings
    _MIN_FRONTAL_FRAMES = int(getattr(_dj_settings, "AI_MIN_FRONTAL_FRAMES", 1))
except Exception:
    _MIN_FRONTAL_FRAMES = 1
_MAX_FRONTAL_STORE = max(3, _MIN_FRONTAL_FRAMES)


# SKUD push uchun bounded pool — cheksiz daemon thread o'rniga (sinf kirganda
# thread bo'roni bo'lmaydi). Lazy yaratiladi.
_skud_push_pool = None
_skud_push_pool_lock = threading.Lock()


def _get_skud_push_pool() -> ThreadPoolExecutor:
    global _skud_push_pool
    if _skud_push_pool is None:
        with _skud_push_pool_lock:
            if _skud_push_pool is None:
                try:
                    from django.conf import settings as _s
                    workers = int(getattr(_s, "AI_SKUD_PUSH_WORKERS", 8))
                except Exception:
                    workers = 8
                _skud_push_pool = ThreadPoolExecutor(
                    max_workers=max(2, workers), thread_name_prefix="skud-push"
                )
    return _skud_push_pool


def _cleanup_frontal_store():
    """60 soniyadan eski frontal store entry'larini tozalaydi (memory leak prevention)."""
    now = time.monotonic()
    with _FRONTAL_STORE_LOCK:
        stale = [k for k, ts in _FRONTAL_STORE_TIMESTAMPS.items() if now - ts > _FRONTAL_STORE_TTL]
        for k in stale:
            _FRONTAL_STORE.pop(k, None)
            _FRONTAL_STORE_TIMESTAMPS.pop(k, None)
    return len(stale)

# Xona bo'yicha embedding keshi — dars davomida DB ga tegmaydi
# camera_id → (schedule_id, LessonEmbeddingCache)
_LESSON_CACHE: dict[int, tuple] = {}
_LESSON_CACHE_LOCK = threading.Lock()

# Aktiv darsni 30 sekundda bir marta tekshirish uchun kesh
# camera_id → (monotonic_time, schedule | None)
_SCHEDULE_CACHE: dict[int, tuple] = {}
_SCHEDULE_CACHE_TTL = 30.0
_SCHEDULE_CACHE_LOCK = threading.Lock()


def _get_cached_schedule(camera_id: int):
    """30 sekundda bir marta DB dan aktiv darsni oladi."""
    now = time.monotonic()
    with _SCHEDULE_CACHE_LOCK:
        entry = _SCHEDULE_CACHE.get(camera_id)
        if entry and (now - entry[0]) < _SCHEDULE_CACHE_TTL:
            return entry[1]

    from apps.integrations.models import ExternalClassroom, ExternalSchedule
    from zoneinfo import ZoneInfo as _ZoneInfo
    tz = _ZoneInfo("Asia/Tashkent")
    local_now = timezone.now().astimezone(tz)

    classroom = ExternalClassroom.objects.filter(camera_id=camera_id).first()
    schedule = None
    if classroom:
        schedule = (
            ExternalSchedule.objects
            .filter(
                classroom=classroom,
                date=local_now.date(),
                start_at__lte=local_now.time(),
                end_at__gte=local_now.time(),
            )
            .select_related("class_obj")
            .first()
        )

    with _SCHEDULE_CACHE_LOCK:
        _SCHEDULE_CACHE[camera_id] = (now, schedule)
    return schedule


def _get_lesson_embedding_cache(camera_id: int):
    """
    Kamera uchun joriy darsning LessonEmbeddingCache ni qaytaradi.
    Dars o'zgarganda yoki birinchi marta chaqirilganda RAM kesh yangilanadi.
    Aktiv dars yo'q bo'lsa (None, None) qaytaradi.
    """
    schedule = _get_cached_schedule(camera_id)

    if schedule is None:
        with _LESSON_CACHE_LOCK:
            _LESSON_CACHE.pop(camera_id, None)
        return None, None

    with _LESSON_CACHE_LOCK:
        entry = _LESSON_CACHE.get(camera_id)
        if entry and entry[0] == schedule.id:
            return schedule, entry[1]

    # Yangi dars — LessonEmbeddingCache dan tashqarida yaratamiz (og'ir operatsiya)
    cache = LessonEmbeddingCache(schedule)

    with _LESSON_CACHE_LOCK:
        # Boshqa thread avvalroq yaratmagan bo'lsa saqlaymiz
        entry = _LESSON_CACHE.get(camera_id)
        if not entry or entry[0] != schedule.id:
            _LESSON_CACHE[camera_id] = (schedule.id, cache)
            logger.info(
                "LessonEmbeddingCache yangilandi: cam=%s schedule_id=%s class_id=%s talabalar=%d",
                camera_id, schedule.id, schedule.class_obj_id, cache.size,
            )
        else:
            cache = entry[1]

    return schedule, cache


def _get_cached_roi(camera_id: int):
    from apps.cameras.models import CameraROI
    now = time.monotonic()
    with _ROI_CACHE_LOCK:
        if camera_id in _ROI_CACHE_TIME and (now - _ROI_CACHE_TIME[camera_id]) < _ROI_CACHE_TTL:
            return _ROI_CACHE[camera_id]
        # Vaqtni oldindan yangilash — boshqa threadlar DB ga parallel so'rov yubormaydi
        _ROI_CACHE_TIME[camera_id] = now
    roi = CameraROI.objects.filter(camera_id=camera_id).first()
    with _ROI_CACHE_LOCK:
        _ROI_CACHE[camera_id] = roi
    return roi


class ActiveScheduleService:
    """
    Kamera joylashgan xonada hozirgi vaqtdagi aktiv darsni topadi
    va o'quvchi davomat yozuvini yaratadi/yangilaydi.
    """

    def get_for_camera(self, camera_id: int, now=None):
        """
        Shu kamera xonasida HOZIR bo'layotgan darsni qaytaradi.
        Agar topilmasa — None.
        """
        from apps.integrations.models import ExternalClassroom, ExternalSchedule
        if now is None:
            now = timezone.now()

        classroom = ExternalClassroom.objects.filter(camera_id=camera_id).first()
        if not classroom:
            return None

        tz = ZoneInfo("Asia/Tashkent")
        local_now = now.astimezone(tz)

        return (
            ExternalSchedule.objects
            .filter(
                classroom=classroom,
                date=local_now.date(),
                start_at__lte=local_now.time(),
                end_at__gte=local_now.time(),
            )
            .select_related("class_obj")
            .first()
        )

    def get_classroom_for_camera(self, camera_id: int):
        """Camera bilan bog'liq ExternalClassroom ni qaytaradi."""
        from apps.integrations.models import ExternalClassroom
        return ExternalClassroom.objects.filter(camera_id=camera_id).select_related("organization").first()

    def get_day_schedules(self, camera_id: int, date=None):
        """
        Shu kamera xonasidagi BUGUNGI barcha darslar ro'yxati.
        Bugun bo'sh bo'lsa — eng yaqin o'tgan kunni qidiradi (7 kun orqaga).
        """
        from apps.integrations.models import ExternalClassroom, ExternalSchedule
        import datetime

        classroom = ExternalClassroom.objects.filter(camera_id=camera_id).first()
        if not classroom:
            return [], None

        if date is None:
            tz = ZoneInfo("Asia/Tashkent")
            date = timezone.now().astimezone(tz).date()

        # Avval bugunni sinab ko'ramiz
        qs = ExternalSchedule.objects.filter(
            classroom=classroom, date=date
        ).select_related("class_obj").order_by("start_at")

        if qs.exists():
            return list(qs), date

        # Bugun yo'q — oxirgi 7 kun ichidan eng so'nggi kunni topamiz
        fallback = (
            ExternalSchedule.objects
            .filter(classroom=classroom, date__lt=date)
            .order_by("-date")
            .values_list("date", flat=True)
            .first()
        )
        if fallback:
            qs2 = ExternalSchedule.objects.filter(
                classroom=classroom, date=fallback
            ).select_related("class_obj").order_by("start_at")
            return list(qs2), fallback

        return [], None

    def record_lesson_attendance(
        self,
        student_id: int,
        schedule,
        recognition_event,
        arrived_at,
        late_grace_minutes: int = 5,
    ):
        from apps.integrations.models import ExternalStudent

        student = (
            ExternalStudent.objects
            .filter(id=student_id)
            .select_related("class_obj")
            .first()
        )
        if not student:
            return None, False

        if not student.class_obj_id or student.class_obj_id != schedule.class_obj_id:
            is_late = False
            status = LessonAttendance.STATUS_WRONG_ROOM
        else:
            tz = ZoneInfo(schedule.timezone or "Asia/Tashkent")
            local_arrived = arrived_at.astimezone(tz).replace(tzinfo=None)
            grace_deadline = (
                datetime.combine(schedule.date, schedule.start_at)
                + timedelta(minutes=late_grace_minutes)
            )
            is_late = local_arrived > grace_deadline
            status = LessonAttendance.STATUS_LATE if is_late else LessonAttendance.STATUS_PRESENT

        # Mavjud yozuv bo'lsa faqat statusni yaxshilash mumkin (present > late > wrong_room)
        _priority = {
            LessonAttendance.STATUS_PRESENT:    3,
            LessonAttendance.STATUS_LATE:       2,
            LessonAttendance.STATUS_WRONG_ROOM: 1,
            LessonAttendance.STATUS_ABSENT:     0,
        }
        existing = LessonAttendance.objects.filter(
            schedule=schedule, student=student
        ).first()

        if existing:
            if _priority.get(status, 0) > _priority.get(existing.status, 0):
                existing.status = status
                existing.is_late = is_late
                existing.arrived_at = arrived_at
                existing.recognition_event = recognition_event
                existing.save(update_fields=["status", "is_late", "arrived_at",
                                             "recognition_event_id", "updated_at"])
            return existing, False

        obj = LessonAttendance.objects.create(
            schedule=schedule,
            student=student,
            recognition_event=recognition_event,
            arrived_at=arrived_at,
            is_late=is_late,
            status=status,
        )
        return obj, True

    def mark_absent_for_finished_lessons(self, organization_id=None):
        """
        Dars tugab, hali kelmaganlarni 'absent' qiladi.
        Cron yoki management command orqali chaqiriladi.
        """
        from apps.integrations.models import ExternalSchedule, ExternalStudent

        tz = ZoneInfo("Asia/Tashkent")
        now_local = timezone.now().astimezone(tz)

        qs = ExternalSchedule.objects.filter(
            date=now_local.date(),
            end_at__lt=now_local.time(),
        ).select_related("class_obj").prefetch_related("class_obj__students")

        if organization_id is not None:
            qs = qs.filter(organization__organization_id=organization_id)

        total_marked = 0
        with transaction.atomic():
            for schedule in qs:
                students = schedule.class_obj.students.all()
                existing_ids = set(
                    LessonAttendance.objects.filter(schedule=schedule)
                    .values_list("student_id", flat=True)
                )
                to_create = [
                    LessonAttendance(
                        schedule=schedule,
                        student=student,
                        status=LessonAttendance.STATUS_ABSENT,
                    )
                    for student in students
                    if student.id not in existing_ids
                ]
                if to_create:
                    LessonAttendance.objects.bulk_create(to_create, ignore_conflicts=True)
                    total_marked += len(to_create)

        return {"absent_marked": total_marked}


class AttendanceLockService:
    def __init__(self, lock_minutes: int = 45):
        self.lock_minutes = lock_minutes

    def get_active_lock(self, student_id: int, camera_id: int | None = None):
        now = timezone.now()
        qs = AttendanceLock.objects.filter(
            student_id=student_id,
            is_active=True,
            locked_until__gt=now,
        )
        if camera_id is not None:
            qs = qs.filter(camera_id=camera_id)
        return qs.order_by("-locked_until").first()

    def is_locked(self, student_id: int, camera_id: int | None = None) -> bool:
        return self.get_active_lock(student_id=student_id, camera_id=camera_id) is not None

    def create_lock(
        self,
        student_id: int,
        organization_id: int | None = None,
        camera_id: int | None = None,
        minutes: int | None = None,
        reason: str = "attendance_done",
    ):
        now = timezone.now()
        duration = minutes if minutes is not None else self.lock_minutes
        locked_until = now + timedelta(minutes=duration)
        try:
            with transaction.atomic():
                return AttendanceLock.objects.create(
                    student_id=student_id,
                    camera_id=camera_id,
                    organization_id=organization_id,
                    locked_from=now,
                    locked_until=locked_until,
                    is_active=True,
                    reason=reason,
                )
        except IntegrityError:
            # Ikki thread bir vaqtda lock yaratmoqchi bo'ldi — mavjudini qaytaramiz
            logger.debug(
                "AttendanceLock race: student_id=%s cam=%s — mavjud lock ishlatiladi",
                student_id, camera_id,
            )
            return self.get_active_lock(student_id=student_id, camera_id=camera_id)

    @transaction.atomic
    def deactivate_expired_locks(self):
        now = timezone.now()
        return AttendanceLock.objects.filter(
            is_active=True,
            locked_until__lte=now,
        ).update(is_active=False)


class RecognitionEventService:
    def __init__(self, lock_minutes: int = 45):
        self.lock_service = AttendanceLockService(lock_minutes=lock_minutes)
        self.search_service = RecognitionSearchService()

    def _maybe_record_review_attendance(self, best, camera_id, schedule, event, arrived_at):
        """
        review natija ham davomatga yozilsinmi — .env AI_REVIEW_RECORDS_ATTENDANCE.
        Default False → DARROV qaytadi, hech narsa qilmaydi (hozirgi xatti-harakat).
        Xato bo'lsa ham tanish oqimini buzmaydi (try/except).
        """
        from django.conf import settings
        if not getattr(settings, "AI_REVIEW_RECORDS_ATTENDANCE", False):
            return
        if camera_id is None or schedule is None or not best:
            return
        try:
            with transaction.atomic():
                ActiveScheduleService().record_lesson_attendance(
                    student_id=best["student_id"],
                    schedule=schedule,
                    recognition_event=event,
                    arrived_at=arrived_at,
                )
            logger.info(
                "REVIEW→DAVOMAT | student=%s sim=%.3f cam=%s",
                best.get("pinfl", ""), best.get("best_score", 0), camera_id,
            )
        except Exception as exc:
            logger.error(
                "REVIEW→DAVOMAT xatosi cam=%s student=%s: %s",
                camera_id, best.get("student_id"), exc,
            )

    def recognize_track_and_record_by_embedding(
            self,
            track_key: str,
            image_path: str,
            query_embedding,
            organization_id: int | None = None,
            camera_id: int | None = None,
            bbox: tuple[int, int, int, int] | None = None,
            accept_threshold: float = 0.70,
            review_threshold: float = 0.55,
            save_base64: bool = True,
            frontal_frames_used: int = 0,
    ):
        track_service = FaceTrackService(lock_minutes=self.lock_service.lock_minutes)

        # Track olish/yaratish alohida tranzaksiyada
        with transaction.atomic():
            track, _ = track_service.get_or_create_track(
                track_key=track_key,
                organization_id=organization_id,
                camera_id=camera_id,
                bbox=bbox,
                frontal_frames_used=frontal_frames_used,
            )
            should_skip, reason = track_service.should_skip_recognition(track)

        if should_skip:
            return {
                "status": "skipped_before_recognition",
                "reason": reason,
                "track_id": track.id,
                "track_key": track.track_key,
                "student_id": track.student_id,
            }

        # Qidiruv: aktiv dars bo'lsa RAM keshdan, aks holda pgvector dan
        _active_schedule = None
        if camera_id is not None:
            _active_schedule, emb_cache = _get_lesson_embedding_cache(camera_id)
            if emb_cache is not None and emb_cache.size > 0:
                result = emb_cache.decide_match(
                    query_embedding=query_embedding,
                    top_k=5,
                    accept_threshold=accept_threshold,
                    review_threshold=review_threshold,
                )
            else:
                result = self.search_service.decide_match_by_embedding(
                    query_embedding=query_embedding,
                    organization_id=organization_id,
                    top_k=5,
                    accept_threshold=accept_threshold,
                    review_threshold=review_threshold,
                )
        else:
            result = self.search_service.decide_match_by_embedding(
                query_embedding=query_embedding,
                organization_id=organization_id,
                top_k=5,
                accept_threshold=accept_threshold,
                review_threshold=review_threshold,
            )

        best = result["best_match"]
        decision = result["decision"]

        # ── 1. Mos talaba topilmadi ──────────────────────────────────────────────
        if best is None:
            logger.debug(
                "REJECTED (no match) | track=%s cam=%s",
                track_key, camera_id,
            )
            return {
                "status": "rejected",
                "decision": decision,
                "track_id": track.id,
                "track_key": track.track_key,
                "best_match": None,
            }

        # ── 2. Rejected — similarity < review_threshold ──────────────────────────
        # DB ga saqlamaymiz; track ga 30s cooldown qo'yamiz (bir yuzni har kadrda
        # qayta hisoblashdan saqlaydi)
        if decision == RecognitionEvent.DECISION_REJECTED:
            now = timezone.now()
            with transaction.atomic():
                track.last_seen_at = now
                track.recognized_at = now   # should_skip_recognition 30s ga bloklaydi
                track.last_score = best["best_score"]
                track.best_score = max(track.best_score or 0.0, best["best_score"])
                track.recognition_count += 1
                track.save(update_fields=[
                    "last_seen_at", "recognized_at", "last_score",
                    "best_score", "recognition_count", "updated_at",
                ])
            logger.debug(
                "REJECTED (below threshold, no save) | student=%s sim=%.3f track=%s",
                best["pinfl"], best["best_score"], track_key,
            )
            return {
                "status": "rejected",
                "decision": decision,
                "track_id": track.id,
                "track_key": track.track_key,
                "best_match": best,
            }

        # ── 3. Review — bitta yozuv (upsert) ────────────────────────────────────
        # Bir talaba, bir kamera, bugungi kun uchun faqat ENG YAXSHI natija saqlanadi.
        # Yangi urinish avvalgidan yaxshiroq bo'lsa — yozuv yangilanadi (create emas).
        if decision == RecognitionEvent.DECISION_REVIEW:
            now = timezone.now()
            today = now.date()
            image_base64 = self._to_base64(image_path) if save_base64 else None

            with transaction.atomic():
                existing = (
                    RecognitionEvent.objects
                    .filter(
                        student_id=best["student_id"],
                        camera_id=camera_id,
                        decision=RecognitionEvent.DECISION_REVIEW,
                        recognized_at__date=today,
                    )
                    .order_by("-similarity")
                    .first()
                )

                # Track har holda yangilanadi
                track.last_seen_at = now
                track.last_score = best["best_score"]
                track.best_score = max(track.best_score or 0.0, best["best_score"])
                track.recognition_count += 1

                if existing and best["best_score"] <= (existing.similarity or 0.0):
                    # Mavjud yozuv yaxshiroq yoki teng — yangi yozuv yaratmaymiz
                    track.save(update_fields=[
                        "last_seen_at", "last_score", "best_score",
                        "recognition_count", "updated_at",
                    ])
                    logger.debug(
                        "REVIEW (existing better) | student=%s new_sim=%.3f existing_sim=%.3f",
                        best["pinfl"], best["best_score"], existing.similarity,
                    )
                    self._maybe_record_review_attendance(
                        best, camera_id, _active_schedule, existing, now)
                    return {
                        "status": "review_exists",
                        "event_id": existing.id,
                        "track_id": track.id,
                        "track_key": track.track_key,
                        "decision": decision,
                        "best_match": best,
                    }

                if existing:
                    # Yangi natija yaxshiroq — mavjud yozuvni yangilaymiz
                    existing.similarity = best["best_score"]
                    existing.recognized_at = now
                    if image_base64:
                        existing.image_base64 = image_base64
                    existing.meta_json = {
                        "top_candidates": result["top_candidates"],
                        "accept_threshold": accept_threshold,
                        "review_threshold": review_threshold,
                        "track_key": track_key,
                    }
                    existing.save(update_fields=[
                        "similarity", "recognized_at", "image_base64",
                        "meta_json", "updated_at",
                    ])
                    event = existing
                    track_service.mark_track_recognized(
                        track=track,
                        student_id=best["student_id"],
                        score=best["best_score"],
                        meta_json={"event_id": existing.id, "decision": decision},
                    )
                    logger.info(
                        "REVIEW (updated) | student=%s sim=%.3f→%.3f event_id=%s",
                        best["pinfl"], existing.similarity, best["best_score"], existing.id,
                    )
                    self._maybe_record_review_attendance(
                        best, camera_id, _active_schedule, event, now)
                    return {
                        "status": "review_updated",
                        "event_id": existing.id,
                        "track_id": track.id,
                        "track_key": track.track_key,
                        "decision": decision,
                        "best_match": best,
                    }

                # Bugun birinchi review — yangi yozuv yaratamiz
                event = RecognitionEvent.objects.create(
                    student_id=best["student_id"],
                    camera_id=camera_id,
                    organization_id=organization_id,
                    full_name=best["full_name"],
                    pinfl=best["pinfl"],
                    recognized_at=now,
                    similarity=best["best_score"],
                    decision=decision,
                    source="ai",
                    model_name="buffalo_l",
                    image_base64=image_base64,
                    meta_json={
                        "top_candidates": result["top_candidates"],
                        "accept_threshold": accept_threshold,
                        "review_threshold": review_threshold,
                        "track_key": track_key,
                    },
                )
                track_service.mark_track_recognized(
                    track=track,
                    student_id=best["student_id"],
                    score=best["best_score"],
                    meta_json={"event_id": event.id, "decision": decision},
                )
                logger.info(
                    "REVIEW (new) | student=%s sim=%.3f event_id=%s track=%s",
                    best["pinfl"], best["best_score"], event.id, track_key,
                )
                self._maybe_record_review_attendance(
                    best, camera_id, _active_schedule, event, now)
                return {
                    "status": "review_recorded",
                    "event_id": event.id,
                    "track_id": track.id,
                    "track_key": track.track_key,
                    "decision": decision,
                    "best_match": best,
                }

        # ── 4. Accepted ──────────────────────────────────────────────────────────
        # Global lock tekshiruvi — birorta kamerada yozilgan bo'lsa o'tkazib yuboramiz
        if self.lock_service.is_locked(student_id=best["student_id"], camera_id=None):
            with transaction.atomic():
                track_service.mark_track_recognized(
                    track=track,
                    student_id=best["student_id"],
                    score=best["best_score"],
                    meta_json={"top_candidates": result["top_candidates"], "decision": decision},
                )
            logger.debug(
                "ACCEPTED (skipped, already locked) | student=%s sim=%.3f track=%s",
                best["pinfl"], best["best_score"], track_key,
            )
            return {
                "status": "skipped_locked_after_search",
                "track_id": track.id,
                "track_key": track.track_key,
                "decision": decision,
                "best_match": best,
            }

        now = timezone.now()
        today = now.date()
        image_base64 = self._to_base64(image_path) if save_base64 else None
        lock = None

        with transaction.atomic():
            event = RecognitionEvent.objects.create(
                student_id=best["student_id"],
                camera_id=camera_id,
                organization_id=organization_id,
                full_name=best["full_name"],
                pinfl=best["pinfl"],
                recognized_at=now,
                similarity=best["best_score"],
                decision=RecognitionEvent.DECISION_ACCEPTED,
                source="ai",
                model_name="buffalo_l",
                image_base64=image_base64,
                meta_json={
                    "top_candidates": result["top_candidates"],
                    "accept_threshold": accept_threshold,
                    "review_threshold": review_threshold,
                    "track_key": track_key,
                },
            )

            # Bugungi review yozuvlar endi keraksiz — o'chiriladi
            deleted_reviews, _ = RecognitionEvent.objects.filter(
                student_id=best["student_id"],
                camera_id=camera_id,
                decision=RecognitionEvent.DECISION_REVIEW,
                recognized_at__date=today,
            ).delete()
            if deleted_reviews:
                logger.debug(
                    "ACCEPTED: %d review yozuv o'chirildi | student=%s",
                    deleted_reviews, best["pinfl"],
                )

            track_service.mark_track_recognized(
                track=track,
                student_id=best["student_id"],
                score=best["best_score"],
                meta_json={"event_id": event.id, "decision": decision},
            )

            lock = self.lock_service.create_lock(
                student_id=best["student_id"],
                organization_id=organization_id,
                camera_id=camera_id,
                reason="attendance_done",
            )

            if camera_id is not None and _active_schedule is not None:
                try:
                    with transaction.atomic():
                        svc = ActiveScheduleService()
                        svc.record_lesson_attendance(
                            student_id=best["student_id"],
                            schedule=_active_schedule,
                            recognition_event=event,
                            arrived_at=now,
                        )
                except Exception as exc:
                    logger.error(
                        "LessonAttendance xatosi camera_id=%s student_id=%s: %s",
                        camera_id, best["student_id"], exc,
                    )

        logger.info(
            "ACCEPTED | student=%s sim=%.3f event_id=%s lock_id=%s track=%s",
            best["full_name"], best["best_score"], event.id, lock.id, track_key,
        )

        # Fayl saqlash tranzaksiyadan TASHQARIDA — DB fail bo'lsa fayl orphan bo'lmaydi
        file_obj = self._to_file(image_path, file_name=image_path.split("/")[-1])
        try:
            event.image.save(file_obj.name, file_obj, save=True)
        except Exception as exc:
            logger.error("Event image save xatosi event_id=%s: %s", event.id, exc)

        push_result = self._push_to_skud(event)
        return {
            "status": "recorded_and_locked",
            "event_id": event.id,
            "lock_id": lock.id,
            "track_id": track.id,
            "track_key": track.track_key,
            "decision": decision,
            "best_match": best,
            "skud_push": push_result,
        }

    def recognize_track_and_record(
        self,
        track_key: str,
        image_path: str,
        organization_id: int | None = None,
        camera_id: int | None = None,
        bbox: tuple[int, int, int, int] | None = None,
        accept_threshold: float = 0.70,
        review_threshold: float = 0.55,
        save_base64: bool = True,
    ):
        # Embedding bir marta chiqariladi, keyin by_embedding versiyasiga uzatiladi
        query_embedding = self.search_service._extract_embedding(image_path)
        return self.recognize_track_and_record_by_embedding(
            track_key=track_key,
            image_path=image_path,
            query_embedding=query_embedding,
            organization_id=organization_id,
            camera_id=camera_id,
            bbox=bbox,
            accept_threshold=accept_threshold,
            review_threshold=review_threshold,
            save_base64=save_base64,
        )

    def recognize_and_record(
        self,
        image_path: str,
        organization_id: int | None = None,
        camera_id: int | None = None,
        accept_threshold: float = 0.70,
        review_threshold: float = 0.55,
        save_base64: bool = True,
    ):
        result = self.search_service.decide_match(
            image_path=image_path,
            organization_id=organization_id,
            top_k=5,
            accept_threshold=accept_threshold,
            review_threshold=review_threshold,
        )

        best = result["best_match"]
        decision = result["decision"]

        if best and decision == "accepted":
            if self.lock_service.is_locked(student_id=best["student_id"], camera_id=None):
                return {"status": "skipped_locked", "decision": decision, "best_match": best}

        image_base64 = self._to_base64(image_path) if save_base64 else None
        now = timezone.now()
        lock = None

        with transaction.atomic():
            event = RecognitionEvent.objects.create(
                student_id=best["student_id"] if best else None,
                camera_id=camera_id,
                organization_id=organization_id,
                full_name=best["full_name"] if best else "",
                pinfl=best["pinfl"] if best else "",
                recognized_at=now,
                similarity=best["best_score"] if best else None,
                decision=decision,
                source="ai",
                model_name="buffalo_l",
                image_base64=image_base64,
                meta_json={
                    "top_candidates": result["top_candidates"],
                    "accept_threshold": accept_threshold,
                    "review_threshold": review_threshold,
                },
            )
            if best and decision == "accepted":
                lock = self.lock_service.create_lock(
                    student_id=best["student_id"],
                    organization_id=organization_id,
                    camera_id=camera_id,
                    reason="attendance_done",
                )

        file_obj = self._to_file(image_path, file_name=image_path.split("/")[-1])
        try:
            event.image.save(file_obj.name, file_obj, save=True)
        except Exception as exc:
            logger.error("Event image save xatosi event_id=%s: %s", event.id, exc)

        if best and decision == "accepted":
            return {
                "status": "recorded_and_locked",
                "event_id": event.id,
                "lock_id": lock.id,
                "decision": decision,
                "best_match": best,
            }

        return {"status": "recorded", "event_id": event.id, "decision": decision, "best_match": best}

    def _push_to_skud(self, event) -> dict:
        """SKUD ga yuborish fon threadida — kamera kadri bloklanmaydi."""
        event_id = event.id
        pinfl = event.pinfl

        def _do_push():
            from django.db.models import F
            try:
                from apps.integrations.services import SkudAttendancePushService
                result = SkudAttendancePushService().push_recognition_event(event)
                status = result.get("status")

                if status == "pushed":
                    RecognitionEvent.objects.filter(id=event_id).update(
                        skud_pushed_at=timezone.now(),
                        skud_push_error=None,
                        skud_push_attempts=F("skud_push_attempts") + 1,
                    )

                elif status == "skip_permanent":
                    # Qayta urinish kerak emas — "skip:" prefiksi bilan saqlaymiz
                    reason = f"skip:{result.get('reason', 'unknown')}"
                    RecognitionEvent.objects.filter(id=event_id).update(
                        skud_push_error=reason,
                        skud_push_attempts=F("skud_push_attempts") + 1,
                    )

                else:
                    # Vaqtincha xato — keyingi retry uchun qoladi (skip: prefiksi yo'q)
                    detail = result.get("detail", "")[:200]
                    error_msg = f"{result.get('reason', 'failed')}: {detail}".strip(": ")
                    RecognitionEvent.objects.filter(id=event_id).update(
                        skud_push_error=error_msg,
                        skud_push_attempts=F("skud_push_attempts") + 1,
                    )

            except Exception as exc:
                try:
                    from django.db.models import F as _F
                    RecognitionEvent.objects.filter(id=event_id).update(
                        skud_push_error=str(exc)[:200],
                        skud_push_attempts=_F("skud_push_attempts") + 1,
                    )
                except Exception:
                    pass
                logger.error("SKUD push xatosi: pinfl=%s event_id=%s: %s", pinfl, event_id, exc)

        _get_skud_push_pool().submit(_do_push)
        return {"status": "async_started", "event_id": event_id}

    def _to_base64(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"

    def _to_file(self, image_path: str, file_name: str):
        with open(image_path, "rb") as f:
            return ContentFile(f.read(), name=file_name)


class FaceTrackService:
    def __init__(
        self,
        lock_minutes: int = 45,
        re_recognize_seconds: int = 30,
        track_ttl_seconds: int = 120,
    ):
        self.lock_service = AttendanceLockService(lock_minutes=lock_minutes)
        self.re_recognize_seconds = re_recognize_seconds
        self.track_ttl_seconds = track_ttl_seconds

    def get_or_create_track(
        self,
        track_key: str,
        organization_id: int | None = None,
        camera_id: int | None = None,
        bbox: tuple[int, int, int, int] | None = None,
        frontal_frames_used: int = 0,
    ):
        now = timezone.now()
        camera_obj = None

        if camera_id is not None:
            camera_obj = Camera.objects.filter(id=camera_id).first()

        defaults = {
            "camera": camera_obj,
            "organization_id": organization_id,
            "first_seen_at": now,
            "last_seen_at": now,
            "status": TrackSession.STATUS_NEW,
            "is_active": True,
        }

        track, created = TrackSession.objects.get_or_create(
            track_key=track_key,
            defaults=defaults,
        )

        if created:
            logger.debug("TRACK new | key=%s cam=%s", track_key, camera_id)
        else:
            track.last_seen_at = now
            track.frame_count += 1
            track.status = TrackSession.STATUS_TRACKING if track.status == TrackSession.STATUS_NEW else track.status

        if frontal_frames_used > 0:
            track.frontal_count += frontal_frames_used

        if bbox:
            x1, y1, x2, y2 = bbox
            track.bbox_x1 = x1
            track.bbox_y1 = y1
            track.bbox_x2 = x2
            track.bbox_y2 = y2

        track.save()
        return track, created

    def should_skip_recognition(self, track: TrackSession):
        now = timezone.now()

        if not track.is_active:
            logger.debug("TRACK skip (inactive) | key=%s", track.track_key)
            return True, "inactive_track"

        if track.student_id:
            lock = self.lock_service.get_active_lock(
                student_id=track.student_id,
                camera_id=track.camera_id,
            )
            if lock:
                from django.conf import settings as _lk_s
                _skip_locked = getattr(_lk_s, "AI_SKIP_LOCKED_TRACK", True)
                track.last_seen_at = now
                if _skip_locked:
                    # Default: shu track qulflangan o'quvchiniki — o'tkazib yuboramiz
                    track.status = TrackSession.STATUS_SKIPPED_LOCKED
                    track.save(update_fields=["status", "last_seen_at", "updated_at"])
                    logger.debug(
                        "TRACK skip (locked) | key=%s student_id=%s until=%s",
                        track.track_key, track.student_id,
                        lock.locked_until.strftime("%H:%M:%S"),
                    )
                    return True, "student_locked"
                # AI_SKIP_LOCKED_TRACK=False (patrul): bir katakka boshqa o'quvchi
                # kelgan bo'lishi mumkin — qulflangan bo'lsa ham tanishni davom
                # ettiramiz (per-student AttendanceLock dublikatdan saqlaydi)
                track.save(update_fields=["last_seen_at", "updated_at"])

        if track.recognized_at:
            delta = (now - track.recognized_at).total_seconds()
            if delta < self.re_recognize_seconds:
                track.last_seen_at = now
                track.save(update_fields=["last_seen_at", "updated_at"])
                logger.debug(
                    "TRACK skip (cooldown %.0fs/%.0fs) | key=%s",
                    delta, self.re_recognize_seconds, track.track_key,
                )
                return True, "recently_recognized"

        return False, None

    def mark_track_recognized(
        self,
        track: TrackSession,
        student_id: int,
        score: float,
        meta_json: dict | None = None,
    ):
        now = timezone.now()
        track.student_id = student_id
        track.recognized_at = now
        track.last_seen_at = now
        track.last_score = score
        track.best_score = max(track.best_score or score, score)
        track.recognition_count += 1
        track.status = TrackSession.STATUS_RECOGNIZED
        if meta_json is not None:
            track.meta_json = meta_json
        track.save()
        return track

    def mark_track_lost(self, track: TrackSession):
        track.is_active = False
        track.status = TrackSession.STATUS_LOST
        track.save(update_fields=["is_active", "status", "updated_at"])
        return track

    def deactivate_stale_tracks(self):
        border = timezone.now() - timedelta(seconds=self.track_ttl_seconds)
        return TrackSession.objects.filter(
            is_active=True,
            last_seen_at__lt=border,
        ).update(is_active=False, status=TrackSession.STATUS_LOST)


# Sinf xonasi kamerasi uchun — .env orqali sozlanadi (default = hozirgi: 40°)
try:
    from django.conf import settings as _pose_settings
    _MAX_YAW_DEG = float(getattr(_pose_settings, "AI_MAX_YAW_DEG", 40.0))
    _MAX_PITCH_DEG = float(getattr(_pose_settings, "AI_MAX_PITCH_DEG", 40.0))
except Exception:
    _MAX_YAW_DEG = 40.0
    _MAX_PITCH_DEG = 40.0


class LiveFrameProcessorService:
    def __init__(self):
        self.recognition_service = RecognitionEventService()

    def _read_frame(self, image_path: str):
        if not image_path or not os.path.exists(image_path):
            raise ValueError(f"Frame image not found: {image_path}")
        frame = cv2.imread(image_path)
        if frame is None:
            raise ValueError("cv2.imread failed for frame")
        return frame

    def _make_track_key(
        self,
        camera_id: int | None,
        bbox: tuple[int, int, int, int],
        grid_size: int = 80,
    ):
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        gcx = (cx // grid_size) * grid_size
        gcy = (cy // grid_size) * grid_size
        raw = f"{camera_id}:{gcx}:{gcy}"
        digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]
        return f"cam{camera_id or 0}_track_{digest}"

    def _apply_roi(self, frame, camera_id: int | None):
        if camera_id is None:
            return frame, None
        roi = _get_cached_roi(camera_id)
        if not roi:
            return frame, None
        h, w = frame.shape[:2]
        x1 = max(0, roi.roi_x)
        y1 = max(0, roi.roi_y)
        x2 = min(w, roi.roi_x + roi.roi_width)
        y2 = min(h, roi.roi_y + roi.roi_height)
        if x2 <= x1 or y2 <= y1:
            return frame, None
        cropped = frame[y1:y2, x1:x2]
        if roi.frame_width and roi.frame_height:
            cropped = cv2.resize(
                cropped, (roi.frame_width, roi.frame_height), interpolation=cv2.INTER_CUBIC
            )
        return cropped, roi

    def _crop_face(self, frame, bbox, pad_ratio: float = 0.20):
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]
        bw = x2 - x1
        bh = y2 - y1
        pad_x = int(bw * pad_ratio)
        pad_y = int(bh * pad_ratio)
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)
        return frame[y1:y2, x1:x2]

    def _get_upscaled_embedding(self, frame, bbox, target_size: int = 256) -> np.ndarray | None:
        """Kichik yuz uchun: crop → upscale → InsightFace → sifatli embedding."""
        crop = self._crop_face(frame, bbox, pad_ratio=0.30)
        if crop.size == 0:
            return None
        h, w = crop.shape[:2]
        if w < target_size or h < target_size:
            scale = max(target_size / w, target_size / h)
            crop = cv2.resize(
                crop,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_CUBIC,
            )
        faces = detect_faces(crop)
        if not faces:
            return None
        best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        return best.embedding

    def _save_temp_crop(self, crop):
        import tempfile
        with tempfile.NamedTemporaryFile(
            suffix=f"_face_{timezone.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg",
            delete=False,
        ) as tmp:
            tmp_path = tmp.name
        if not cv2.imwrite(tmp_path, crop):
            raise ValueError("Failed to save temporary crop image")
        return tmp_path

    def _check_pose(self, face) -> tuple[bool, str]:
        """Yuz burchagi juda katta bo'lsa False qaytaradi — embedding sifatsiz bo'ladi."""
        if not hasattr(face, "pose") or face.pose is None:
            return True, ""
        pitch, yaw, roll = float(face.pose[0]), float(face.pose[1]), float(face.pose[2])
        if abs(yaw) > _MAX_YAW_DEG:
            return False, f"yaw={yaw:.1f}deg"
        if abs(pitch) > _MAX_PITCH_DEG:
            return False, f"pitch={pitch:.1f}deg"
        return True, ""

    def _is_sharp(self, crop, threshold: float = 40.0) -> bool:
        # Uzoqdagi kichik yuzlar uchun pastroq threshold (40 < 80)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        variance = cv2.Laplacian(gray, cv2.CV_64F).var()
        return variance >= threshold

    def _average_embeddings(self, embeddings: list) -> np.ndarray:
        """N ta frontal embedding o'rtachasi + L2 normalizatsiya.
        ArcFace uchun: bir necha sifatli frame birlashtirilsa accuracy oshadi."""
        arr = np.stack(embeddings, axis=0)
        mean = arr.mean(axis=0)
        norm = np.linalg.norm(mean)
        if norm > 0:
            mean = mean / norm
        return mean.astype(np.float32)

    def process_frame_image(
            self,
            image_path: str,
            organization_id: int | None = None,
            camera_id: int | None = None,
            accept_threshold: float | None = None,
            review_threshold: float | None = None,
            min_face_px: int = 30,
            max_dim: int | None = None,
    ):
        from django.conf import settings
        if accept_threshold is None:
            accept_threshold = getattr(settings, "AI_ACCEPT_THRESHOLD", 0.55)
        if review_threshold is None:
            review_threshold = getattr(settings, "AI_REVIEW_THRESHOLD", 0.42)
        if max_dim is None:
            max_dim = getattr(settings, "AI_FRAME_MAX_DIM", 640)
        frame = self._read_frame(image_path)
        frame, roi = self._apply_roi(frame, camera_id)

        # CPU yukini kamaytirish: det_size=(640,640) bilan mos, sifat yo'qolmaydi
        h, w = frame.shape[:2]
        if w > max_dim or h > max_dim:
            scale = min(max_dim / w, max_dim / h)
            frame = cv2.resize(
                frame,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA,
            )

        faces = detect_faces(frame)

        results = []

        for face in faces:
            bbox = face.bbox.astype(int).tolist()
            x1, y1, x2, y2 = bbox
            face_w = x2 - x1
            face_h = y2 - y1

            # 1. O'lcham tekshiruvi
            if face_w < min_face_px or face_h < min_face_px:
                results.append({
                    "status": "skipped_too_small",
                    "bbox": bbox,
                    "face_size": f"{face_w}x{face_h}",
                })
                continue

            # 2. Frontal poza tekshiruvi (qat'iy: yaw≤20°, pitch≤15°)
            # To'g'ridan-to'g'ri qaramagan yuzlar frontal_store ga qo'shilmaydi
            pose_ok, pose_reason = self._check_pose(face)
            if not pose_ok:
                results.append({
                    "status": "waiting_frontal",
                    "bbox": bbox,
                    "reason": pose_reason,
                    "face_size": f"{face_w}x{face_h}",
                })
                continue

            # 3. Loyqalik tekshiruvi
            face_crop = frame[y1:y2, x1:x2]
            if face_crop.size > 0 and not self._is_sharp(face_crop):
                results.append({
                    "status": "skipped_blurry",
                    "bbox": bbox,
                    "face_size": f"{face_w}x{face_h}",
                })
                continue

            # 4. Embedding olish — 160px dan kichik barcha yuzlar upscale qilinadi
            upscaled_emb = None
            if face_w < 160 or face_h < 160:
                upscaled_emb = self._get_upscaled_embedding(frame, (x1, y1, x2, y2))

            query_embedding = upscaled_emb if upscaled_emb is not None else face.embedding
            if query_embedding is None:
                results.append({"status": "error", "bbox": bbox, "error": "face.embedding is None"})
                continue

            query_embedding = query_embedding.astype(np.float32)
            track_key = self._make_track_key(camera_id=camera_id, bbox=(x1, y1, x2, y2))

            # 5. Frontal store ga qo'shish
            with _FRONTAL_STORE_LOCK:
                bucket = _FRONTAL_STORE.setdefault(track_key, [])
                if len(bucket) < _MAX_FRONTAL_STORE:
                    bucket.append(query_embedding)
                _FRONTAL_STORE_TIMESTAMPS[track_key] = time.monotonic()
                current_count = len(bucket)

            # Hali yetarli frontal frame yo'q — kutamiz
            if current_count < _MIN_FRONTAL_FRAMES:
                results.append({
                    "status": "collecting_frontal",
                    "bbox": bbox,
                    "face_size": f"{face_w}x{face_h}",
                    "frontal_count": current_count,
                    "needed": _MIN_FRONTAL_FRAMES,
                })
                continue

            # 6. Yetarli frontal frame to'plandi — o'rtacha embedding hisoblash
            with _FRONTAL_STORE_LOCK:
                stored = list(_FRONTAL_STORE.pop(track_key, []))
                _FRONTAL_STORE_TIMESTAMPS.pop(track_key, None)

            if not stored:
                results.append({
                    "status": "collecting_frontal",
                    "bbox": bbox,
                    "frontal_count": 0,
                    "needed": _MIN_FRONTAL_FRAMES,
                })
                continue

            averaged_embedding = self._average_embeddings(stored)

            crop = self._crop_face(frame, (x1, y1, x2, y2))
            if crop.size == 0:
                results.append({"status": "skipped_invalid_crop", "bbox": bbox})
                continue

            temp_crop_path = self._save_temp_crop(crop)
            try:
                rec_result = self.recognition_service.recognize_track_and_record_by_embedding(
                    track_key=track_key,
                    image_path=temp_crop_path,
                    query_embedding=averaged_embedding,
                    organization_id=organization_id,
                    camera_id=camera_id,
                    bbox=(x1, y1, x2, y2),
                    accept_threshold=accept_threshold,
                    review_threshold=review_threshold,
                    save_base64=getattr(settings, "AI_SAVE_EVENT_BASE64", True),
                    frontal_frames_used=len(stored),
                )
                rec_result["bbox"] = bbox
                rec_result["face_size"] = f"{face_w}x{face_h}"
                rec_result["frontal_frames_used"] = len(stored)
                results.append(rec_result)

            except Exception as e:
                results.append({"status": "error", "bbox": bbox, "error": str(e)})
            finally:
                if os.path.exists(temp_crop_path):
                    os.remove(temp_crop_path)

        return {
            "frame_image": image_path,
            "organization_id": organization_id,
            "camera_id": camera_id,
            "roi_applied": roi is not None,
            "face_count": len(faces),
            "results": results,
        }
