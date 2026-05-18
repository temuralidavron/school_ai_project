import base64
import logging
import ssl
import threading
import time
from datetime import date, datetime, timedelta, timezone as dt_timezone

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

_skud_token_cache: dict = {"token": None, "expires_at": None}
_skud_token_lock = threading.Lock()

from .models import (
    ExternalOrganization,
    ExternalClass,
    ExternalClassroom,
    ExternalStudent,
    ExternalStudentPhoto,
    ExternalSchedule,
)
from apps.cameras.models import Camera, SmartCamera, Auditorium, AuditoriumCamera


class TLSHttpAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
            ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        if hasattr(ssl, "OP_IGNORE_UNEXPECTED_EOF"):
            ctx.options |= ssl.OP_IGNORE_UNEXPECTED_EOF
        kwargs["ssl_context"] = ctx
        return super().proxy_manager_for(*args, **kwargs)


class SkudClient:
    def __init__(self):
        self.base_url = settings.SKUD_API_BASE_URL
        self.client_id = getattr(settings, "SKUD_CLIENT_ID", None)
        self.client_secret = getattr(settings, "SKUD_CLIENT_SECRET", None)
        self._static_token = getattr(settings, "SKUD_ACCESS_TOKEN", None)
        self.session = self._build_session()

    def _login(self) -> tuple[str, datetime]:
        url = f"{self.base_url}/api/SkudAuth/Login"
        response = self.session.post(
            url,
            json={"client_id": self.client_id, "client_secret": self.client_secret},
            timeout=(10, 30),
        )
        response.raise_for_status()
        data = response.json()
        token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        expires_at = datetime.now(dt_timezone.utc) + timedelta(seconds=expires_in - 60)
        return token, expires_at

    def _get_token(self) -> str:
        if not self.client_id or not self.client_secret:
            if not self._static_token:
                raise Exception("SKUD token sozlamalari topilmadi")
            return self._static_token

        with _skud_token_lock:
            now = datetime.now(dt_timezone.utc)
            if (
                _skud_token_cache["token"] is None
                or _skud_token_cache["expires_at"] is None
                or _skud_token_cache["expires_at"] <= now
            ):
                token, expires_at = self._login()
                _skud_token_cache["token"] = token
                _skud_token_cache["expires_at"] = expires_at
                logger.info("SKUD token yangilandi, amal qilish muddati: %s", expires_at)
            return _skud_token_cache["token"]

    def _build_session(self):
        session = requests.Session()

        retry = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=1.2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST"]),
            raise_on_status=False,
        )

        adapter = TLSHttpAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __del__(self):
        self.close()

    def get_headers(self):
        token = self._get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Connection": "close",
        }

    def get_organizations(self):
        url = f"{self.base_url}/api/skud-box/v1/organizations"
        response = self.session.get(url, headers=self.get_headers(), timeout=(20, 60))
        response.raise_for_status()
        return response.json().get("items", [])

    def get_classes(self, organization_id: int):
        url = f"{self.base_url}/api/skud-box/v1/classes"
        response = self.session.get(
            url,
            headers=self.get_headers(),
            params={"organizationId": organization_id},
            timeout=(20, 60),
        )
        response.raise_for_status()
        return response.json().get("items", [])

    def get_classrooms(self, organization_id: int):
        url = f"{self.base_url}/api/skud-box/v1/classrooms/face-cameras"
        response = self.session.get(
            url,
            headers=self.get_headers(),
            params={"organizationId": organization_id},
            timeout=(20, 60),
        )
        response.raise_for_status()
        return response.json().get("items", [])

    def get_students(self, organization_id: int):
        url = f"{self.base_url}/api/skud-box/v1/students"
        response = self.session.get(
            url,
            headers=self.get_headers(),
            params={"organizationId": organization_id},
            timeout=(20, 90),
        )
        response.raise_for_status()
        return response.json().get("items", [])

    def get_student_photo_base64(self, photo_id: str):
        url = f"{self.base_url}/api/skud-box/v1/students/photo/base64"
        response = self.session.get(
            url,
            headers=self.get_headers(),
            params={"photoId": photo_id},
            timeout=(20, 120),
        )
        response.raise_for_status()
        return response.json().get("imageBase64")

    def get_today_schedule(self, organization_id: int, target_date: str | None = None):
        if target_date is None:
            target_date = str(date.today())

        url = f"{self.base_url}/api/skud-box/v1/schedule/today"
        response = self.session.get(
            url,
            headers=self.get_headers(),
            params={"organizationId": organization_id, "date": target_date},
            timeout=(20, 60),
        )
        response.raise_for_status()
        return response.json()

    def push_attendance_evidence(
        self,
        classroom_id: int,
        pinfl: str,
        event_time_utc: str,
        face_photo_base64: str | None,
        organization_id: int,
    ) -> dict:
        """
        SKUD ga davomat yuboradi.
        Qaytaradi:
          {"ok": True}                          — muvaffaqiyatli yuborildi
          {"ok": True,  "duplicate": True}      — avval yuborilgan (409), normal
          {"ok": False, "permanent": True,  "reason": "...", "detail": "..."} — qayta urinish shart emas
          {"ok": False, "permanent": False, "reason": "...", "detail": "..."} — vaqtincha xato, qayta urinish kerak
        """
        url = f"{self.base_url}/api/skud-box/v1/attendance/evidence"
        payload = {
            "classRoomId": classroom_id,
            "pinfl": pinfl,
            "eventTimeUtc": event_time_utc,
            "facePhotoBase64": face_photo_base64 or "",
            "organizationId": organization_id,
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                headers=self.get_headers(),
                timeout=(20, 60),
            )
        except requests.exceptions.RequestException as exc:
            return {"ok": False, "permanent": False, "reason": "network_error", "detail": str(exc)}

        code = response.status_code
        body = ""
        try:
            body = response.text[:300]
        except Exception:
            pass

        logger.debug("SKUD API javob: status=%s pinfl=%s body=%s", code, pinfl, body)

        # Muvaffaqiyatli
        if code in (200, 201):
            data = {}
            try:
                data = response.json()
            except Exception:
                pass
            return {"ok": True, "data": data}

        # Takroriy yuborish — SKUD da allaqachon bor, bu xato emas
        if code == 409:
            logger.info("SKUD 409 (duplicate): pinfl=%s classroom=%s — davomatda bor", pinfl, classroom_id)
            return {"ok": True, "duplicate": True, "data": {}}

        # Doimiy xatolar — qayta urinish foydasiz
        if code == 400:
            logger.warning("SKUD 400 (bad_request): pinfl=%s | %s", pinfl, body)
            return {"ok": False, "permanent": True, "reason": "bad_request", "detail": body}

        if code == 404:
            logger.warning("SKUD 404 (not_found): pinfl=%s classroom=%s | %s", pinfl, classroom_id, body)
            return {"ok": False, "permanent": True, "reason": "not_found", "detail": body}

        if code == 403:
            logger.error("SKUD 403 (forbidden): pinfl=%s | %s", pinfl, body)
            return {"ok": False, "permanent": True, "reason": "forbidden", "detail": body}

        # Token muddati — qayta urinish mumkin (Retry sessiya oldindan yangilaydi)
        if code == 401:
            logger.warning("SKUD 401 (unauthorized) — token muammosi: %s", body)
            return {"ok": False, "permanent": False, "reason": "auth_error", "detail": body}

        # 429, 5xx — Retry sessiyasi allaqachon bir necha marta urinib ko'rgan
        logger.error("SKUD kutilmagan javob: status=%s pinfl=%s | %s", code, pinfl, body)
        return {"ok": False, "permanent": False, "reason": f"http_{code}", "detail": body}


class SkudSyncService:
    PHOTO_FIELD_MAP = {
        "frontPhotoId": "front",
        "upPhotoId": "up",
        "leftPhotoId": "left",
        "rightPhotoId": "right",
        "bottomPhotoId": "bottom",
    }


    def __init__(self):
        self.client = SkudClient()

    def _base64_to_file(self, image_base64: str, filename: str):
        if not image_base64:
            return None
        if "," in image_base64:
            _, encoded = image_base64.split(",", 1)
        else:
            encoded = image_base64
        image_bytes = base64.b64decode(encoded)
        return ContentFile(image_bytes, name=filename)

    @transaction.atomic
    def sync_organizations(self):
        t0 = time.monotonic()
        logger.info("SKUD sync: tashkilotlar yuklab olinmoqda...")
        items = self.client.get_organizations()
        results = []

        for item in items:
            obj, created = ExternalOrganization.objects.update_or_create(
                organization_id=item["organizationId"],
                defaults={
                    "organization_inn": item.get("organizationInn", ""),
                    "organization_name": item.get("organizationName", ""),
                },
            )
            results.append(obj.organization_id)
            logger.debug(
                "SKUD org %s: %s (%s)",
                item["organizationId"],
                item.get("organizationName", ""),
                "yangi" if created else "yangilandi",
            )

        elapsed = time.monotonic() - t0
        logger.info(
            "SKUD sync tashkilotlar: %d ta | %.1fs",
            len(results), elapsed,
        )
        return {"synced_organizations": len(results)}

    @transaction.atomic
    def sync_classes(self, organization_id: int):
        t0 = time.monotonic()
        logger.info("SKUD sync: sinflar yuklab olinmoqda (org=%s)...", organization_id)
        organization = ExternalOrganization.objects.get(organization_id=organization_id)
        items = self.client.get_classes(organization_id)

        for item in items:
            ExternalClass.objects.update_or_create(
                class_id=item["classId"],
                defaults={
                    "class_degree": item.get("classDegree"),
                    "class_name": item.get("className", ""),
                    "organization": organization,
                },
            )

        logger.info("SKUD sync sinflar: %d ta | org=%s | %.1fs", len(items), organization_id, time.monotonic() - t0)
        return {"synced_classes": len(items)}

    @transaction.atomic
    def sync_classrooms(self, organization_id: int):
        organization = ExternalOrganization.objects.get(organization_id=organization_id)
        items = self.client.get_classrooms(organization_id)

        for item in items:
            device_id = item.get("deviceId", "")
            camera = Camera.objects.filter(skud_device_id=device_id).first()
            smart_camera = SmartCamera.objects.filter(device_id=device_id).first()
            auditorium = smart_camera.auditorium if smart_camera else None

            existing = ExternalClassroom.objects.filter(class_room_id=item["classRoomId"]).first()
            # Qo'lda bog'langan camera ni qayta yozmaslik
            final_camera = camera if camera else (existing.camera if existing else None)

            ExternalClassroom.objects.update_or_create(
                class_room_id=item["classRoomId"],
                defaults={
                    "class_room_name": item.get("classRoomName", ""),
                    "device_id": device_id,
                    "organization": organization,
                    "camera": final_camera,
                    "smart_camera": smart_camera,
                    "auditorium": auditorium,
                },
            )

        aud_result = self.sync_auditorium_cameras(organization_id)
        return {"synced_classrooms": len(items), **aud_result}

    @transaction.atomic
    def sync_auditorium_cameras(self, organization_id: int):
        """
        ExternalClassroom.camera bor bo'lgan xonalar uchun:
        1. Auditorium yo'q bo'lsa — xona nomi bilan yaratadi
        2. AuditoriumCamera bog'liqligini yaratadi
        Bu monitoring panelda Schedule → o'qituvchi/fan ma'lumotini olish uchun kerak.
        """
        classrooms = ExternalClassroom.objects.filter(
            organization__organization_id=organization_id,
            camera__isnull=False,
        ).select_related("camera", "auditorium")

        created_auditoriums = 0
        created_links = 0

        for classroom in classrooms:
            camera = classroom.camera

            if not classroom.auditorium:
                auditorium, aud_created = Auditorium.objects.get_or_create(
                    name=classroom.class_room_name,
                    defaults={
                        "code": classroom.class_room_name,
                        "hemis_status": "active",
                    },
                )
                if aud_created:
                    created_auditoriums += 1
                classroom.auditorium = auditorium
                classroom.save(update_fields=["auditorium", "updated_at"])
            else:
                auditorium = classroom.auditorium

            _, link_created = AuditoriumCamera.objects.get_or_create(
                auditorium=auditorium,
                camera=camera,
            )
            if link_created:
                created_links += 1

        return {
            "created_auditoriums": created_auditoriums,
            "created_auditorium_camera_links": created_links,
        }

    def sync_students(self, organization_id: int, download_photos: bool = False):
        t0 = time.monotonic()
        logger.info("SKUD sync: talabalar yuklab olinmoqda (org=%s)...", organization_id)
        organization = ExternalOrganization.objects.get(organization_id=organization_id)
        items = self.client.get_students(organization_id)
        logger.info("SKUD: API dan %d ta talaba olindi, DB ga yozilmoqda...", len(items))

        # 1-qadam: talaba va foto metadatasini DB ga saqlash (transaction ichida)
        self._save_students_to_db(organization, items)
        logger.info("SKUD sync talabalar: %d ta DB ga yozildi | org=%s | %.1fs", len(items), organization_id, time.monotonic() - t0)

        downloaded = 0
        failed_photos = []

        # 2-qadam: foto yuklab olish (transaction tashqarisida, alohida)
        if download_photos:
            downloaded, failed_photos = self._download_photos_for_org(organization_id)

        return {
            "synced_students": len(items),
            "downloaded_photos": downloaded,
            "failed_photos_count": len(failed_photos),
            "failed_photos_preview": failed_photos[:10],
        }

    @transaction.atomic
    def _save_students_to_db(self, organization, items):
        for item in items:
            class_obj = ExternalClass.objects.filter(class_id=item.get("classId")).first()

            student, _ = ExternalStudent.objects.update_or_create(
                pinfl=item["pinfl"],
                defaults={
                    "full_name": item.get("fullName", ""),
                    "organization": organization,
                    "class_obj": class_obj,
                },
            )

            for remote_field, photo_type in self.PHOTO_FIELD_MAP.items():
                guid = item.get(remote_field)
                if not guid:
                    continue

                ExternalStudentPhoto.objects.update_or_create(
                    student=student,
                    photo_type=photo_type,
                    defaults={"photo_guid": guid},
                )

    def _download_photos_for_org(self, organization_id: int, workers: int = 10) -> tuple[int, list]:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        photos = list(
            ExternalStudentPhoto.objects.filter(
                student__organization__organization_id=organization_id,
            ).select_related("student").filter(
                Q(image__isnull=True) | Q(image="")
            )
        )

        total = len(photos)
        logger.info(
            "SKUD foto yuklab olish: %d ta rasm kutmoqda | org=%s | workers=%d",
            total, organization_id, workers,
        )

        if not total:
            logger.info("SKUD foto: yuklab olinadigan rasm yo'q, org=%s", organization_id)
            return 0, []

        counter_lock = threading.Lock()
        downloaded = 0
        failed = []
        t0 = time.monotonic()

        def _fetch_one(photo_obj):
            nonlocal downloaded
            try:
                image_base64 = self.client.get_student_photo_base64(photo_obj.photo_guid)
                file_obj = self._base64_to_file(
                    image_base64,
                    f"{photo_obj.student.pinfl}_{photo_obj.photo_type}.jpg",
                )
                if file_obj:
                    photo_obj.image.save(file_obj.name, file_obj, save=False)
                    photo_obj.image_base64 = image_base64
                    photo_obj.save()
                    with counter_lock:
                        downloaded += 1
                        if downloaded % 10 == 0:
                            pct = downloaded * 100 // total
                            logger.info(
                                "SKUD foto progress: %d/%d (%d%%) | %.0fs",
                                downloaded, total, pct, time.monotonic() - t0,
                            )
            except Exception as e:
                with counter_lock:
                    failed.append({
                        "pinfl": photo_obj.student.pinfl,
                        "photo_type": photo_obj.photo_type,
                        "error": str(e),
                    })
                logger.warning(
                    "SKUD foto yuklab olish xatosi: pinfl=%s type=%s guid=%s: %s",
                    photo_obj.student.pinfl, photo_obj.photo_type,
                    photo_obj.photo_guid, e,
                )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_fetch_one, p) for p in photos]
            for f in as_completed(futures):
                f.result()

        elapsed = time.monotonic() - t0
        logger.info(
            "SKUD foto yakunlandi: %d/%d yuklandi, %d xato | org=%s | %.1fs",
            downloaded, total, len(failed), organization_id, elapsed,
        )
        if failed:
            logger.warning(
                "SKUD foto muvaffaqiyatsiz (%d ta): %s",
                len(failed),
                [f"{f['pinfl']}/{f['photo_type']}: {f['error']}" for f in failed[:5]],
            )
        return downloaded, failed

    @transaction.atomic
    def sync_schedule(self, organization_id: int, target_date: str | None = None):
        t0 = time.monotonic()
        logger.info("SKUD sync: jadval yuklab olinmoqda (org=%s, sana=%s)...", organization_id, target_date or "bugun")
        organization = ExternalOrganization.objects.get(organization_id=organization_id)
        payload = self.client.get_today_schedule(organization_id, target_date=target_date)

        items = payload.get("items", [])
        schedule_timezone = payload.get("timezone", "Asia/Tashkent")  # 'timezone' modul nomini yopmaslik uchun
        schedule_date = payload.get("date")

        skipped = 0
        for item in items:
            class_obj = ExternalClass.objects.filter(class_id=item["classId"]).first()
            classroom = ExternalClassroom.objects.filter(class_room_id=item["classRoomId"]).first()

            if not class_obj or not classroom:
                logger.debug(
                    "SKUD jadval: sinf yoki xona topilmadi class_id=%s room_id=%s — o'tkazib yuborildi",
                    item.get("classId"), item.get("classRoomId"),
                )
                skipped += 1
                continue

            ExternalSchedule.objects.update_or_create(
                organization=organization,
                class_obj=class_obj,
                classroom=classroom,
                lesson_number=item["lessonNumber"],
                date=schedule_date,
                defaults={
                    "timezone": schedule_timezone,
                    "start_at": item["startAt"],
                    "end_at": item["endAt"],
                },
            )

        logger.info(
            "SKUD sync jadval: %d ta yozuv (o'tkazildi: %d) | org=%s | sana=%s | %.1fs",
            len(items) - skipped, skipped, organization_id, schedule_date, time.monotonic() - t0,
        )
        return {"synced_schedule_items": len(items) - skipped, "skipped_items": skipped}

    def sync_photos(self, organization_id: int, limit: int = 20, offset: int = 0):
        photos_qs = (
            ExternalStudentPhoto.objects
            .select_related("student", "student__organization")
            .filter(student__organization__organization_id=organization_id)
            .filter(Q(image__isnull=True) | Q(image=""))
            .order_by("id")
        )

        total_pending = photos_qs.count()
        photos = list(photos_qs[offset:offset + limit])

        downloaded = 0
        failed = []

        for photo_obj in photos:
            try:
                image_base64 = self.client.get_student_photo_base64(photo_obj.photo_guid)
                file_obj = self._base64_to_file(
                    image_base64,
                    f"{photo_obj.student.pinfl}_{photo_obj.photo_type}.jpg",
                )

                if file_obj:
                    photo_obj.image.save(file_obj.name, file_obj, save=False)
                    photo_obj.image_base64 = image_base64
                    photo_obj.save()
                    downloaded += 1

            except requests.exceptions.RequestException as e:
                failed.append({
                    "photo_guid": photo_obj.photo_guid,
                    "pinfl": photo_obj.student.pinfl,
                    "photo_type": photo_obj.photo_type,
                    "error": str(e),
                })
                continue

        return {
            "organization_id": organization_id,
            "total_pending_before_batch": total_pending,
            "batch_size": len(photos),
            "downloaded_photos": downloaded,
            "failed_photos_count": len(failed),
            "failed_photos_preview": failed[:10],
            "next_offset": offset + len(photos),
            "remaining_estimate": max(total_pending - (offset + len(photos)), 0),
        }

    def full_sync(self, organization_id: int, download_photos: bool = False, target_date: str | None = None):
        t0 = time.monotonic()
        logger.info("SKUD full sync boshlandi: org=%s foto=%s", organization_id, download_photos)
        data = {}
        data["classes"]    = self.sync_classes(organization_id)
        data["classrooms"] = self.sync_classrooms(organization_id)
        data["students"]   = self.sync_students(organization_id, download_photos=False)
        data["schedule"]   = self.sync_schedule(organization_id, target_date=target_date)

        if download_photos:
            data["photos"] = self.sync_photos(
                organization_id=organization_id,
                limit=20,
                offset=0,
            )

        logger.info("SKUD full sync yakunlandi: org=%s | %.1fs | %s", organization_id, time.monotonic() - t0, data)
        return data


class SkudAttendancePushService:
    """
    Mahalliy RecognitionEvent dan SKUD global tizimiga attendance yuboradi.
    Bir dars davomida (45 min) bitta talaba uchun 1 marta yuboriladi.
    """

    def __init__(self):
        self.client = SkudClient()

    def _find_classroom(self, camera_id: int | None) -> ExternalClassroom | None:
        if camera_id is None:
            return None
        return ExternalClassroom.objects.filter(camera_id=camera_id).first()

    def _format_event_time_utc(self, recognized_at) -> str:
        from zoneinfo import ZoneInfo
        utc_time = recognized_at.astimezone(ZoneInfo("UTC"))
        return utc_time.strftime("%Y-%m-%d %H:%M:%S.0000000")

    def push_recognition_event(self, recognition_event) -> dict:
        """
        RecognitionEvent obyektini SKUD ga yuboradi.
        Faqat decision=accepted bo'lganda chaqirilishi kerak.

        Qaytaradi:
          {"status": "pushed"}            — muvaffaqiyatli (yoki duplicate)
          {"status": "skip_permanent",    — qayta urinish kerak emas (student/xona yo'q)
           "reason": "..."}
          {"status": "failed",            — vaqtincha xato, qayta urinish kerak
           "reason": "..."}
        """
        student = recognition_event.student
        if not student:
            logger.warning("SKUD push: student yo'q event_id=%s", recognition_event.id)
            return {"status": "skip_permanent", "reason": "no_student"}

        classroom = self._find_classroom(recognition_event.camera_id)
        if not classroom:
            logger.warning(
                "SKUD push: camera_id=%s uchun classroom topilmadi | pinfl=%s event_id=%s",
                recognition_event.camera_id, recognition_event.pinfl, recognition_event.id,
            )
            return {"status": "skip_permanent", "reason": "no_classroom_for_camera"}

        org_id = recognition_event.organization_id or student.organization.organization_id
        event_time_utc = self._format_event_time_utc(recognition_event.recognized_at)

        logger.debug(
            "SKUD push urinish: pinfl=%s classroom_id=%s org=%s vaqt=%s event_id=%s",
            student.pinfl, classroom.class_room_id, org_id, event_time_utc, recognition_event.id,
        )

        result = self.client.push_attendance_evidence(
            classroom_id=classroom.class_room_id,
            pinfl=student.pinfl,
            event_time_utc=event_time_utc,
            face_photo_base64=recognition_event.image_base64,
            organization_id=org_id,
        )

        if result.get("ok"):
            duplicate = result.get("duplicate", False)
            logger.info(
                "SKUD push %s: pinfl=%s classroom_id=%s event_id=%s",
                "duplicate (OK)" if duplicate else "muvaffaqiyatli",
                student.pinfl, classroom.class_room_id, recognition_event.id,
            )
            return {
                "status": "pushed",
                "duplicate": duplicate,
                "classroom_id": classroom.class_room_id,
                "pinfl": student.pinfl,
                "event_time_utc": event_time_utc,
            }

        if result.get("permanent"):
            logger.warning(
                "SKUD push doimiy xato (qayta urinilmaydi): pinfl=%s reason=%s detail=%s event_id=%s",
                student.pinfl, result["reason"], result.get("detail", "")[:100], recognition_event.id,
            )
            return {
                "status": "skip_permanent",
                "reason": result["reason"],
                "detail": result.get("detail", ""),
            }

        logger.error(
            "SKUD push vaqtincha xato: pinfl=%s reason=%s event_id=%s",
            student.pinfl, result.get("reason"), recognition_event.id,
        )
        return {
            "status": "failed",
            "reason": result.get("reason", "unknown"),
            "detail": result.get("detail", ""),
        }

    def push_by_event_id(self, event_id: int) -> dict:
        from apps.attendance.models import RecognitionEvent
        from django.db.models import F
        try:
            event = RecognitionEvent.objects.select_related(
                "student", "student__organization"
            ).get(id=event_id)
        except RecognitionEvent.DoesNotExist:
            return {"status": "error", "reason": f"RecognitionEvent id={event_id} topilmadi"}

        if event.decision != RecognitionEvent.DECISION_ACCEPTED:
            return {"status": "skipped", "reason": f"decision={event.decision}, faqat accepted yuboriladi"}

        result = self.push_recognition_event(event)

        # Natijani DB ga yozamiz (qo'lda qayta push qilganda ham)
        if result.get("status") == "pushed":
            from django.utils import timezone as tz
            RecognitionEvent.objects.filter(id=event_id).update(
                skud_pushed_at=tz.now(),
                skud_push_error=None,
                skud_push_attempts=F("skud_push_attempts") + 1,
            )
        elif result.get("status") == "skip_permanent":
            RecognitionEvent.objects.filter(id=event_id).update(
                skud_push_error=f"skip:{result.get('reason')}",
                skud_push_attempts=F("skud_push_attempts") + 1,
            )
        else:
            detail = result.get("detail", "")[:200]
            RecognitionEvent.objects.filter(id=event_id).update(
                skud_push_error=f"{result.get('reason', 'failed')}: {detail}".strip(": "),
                skud_push_attempts=F("skud_push_attempts") + 1,
            )

        return result