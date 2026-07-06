import datetime
import json
import time
from zoneinfo import ZoneInfo

from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.db.models.functions import TruncHour
from django.http import StreamingHttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

_TZ = ZoneInfo("Asia/Tashkent")


def _local(dt, fmt="%H:%M:%S"):
    """UTC datetime → Toshkent vaqt stringi."""
    if dt is None:
        return None
    return dt.astimezone(_TZ).strftime(fmt)

from apps.academics.models import Schedule
from apps.attendance.models import RecognitionEvent, LessonAttendance
from apps.cameras.models import Camera, AuditoriumCamera
from apps.integrations.models import (
    ExternalOrganization, ExternalClassroom, ExternalStudentPhoto, ExternalSchedule
)


def dashboard(request):
    organizations = ExternalOrganization.objects.order_by("organization_name")
    return render(request, "monitoring/dashboard.html", {"organizations": organizations})


def video_file_stream(request):
    """Local video faylni brauzerga stream qiladi."""
    import os
    from django.http import FileResponse, Http404
    path = "/app/deepstream_data/sinf.mp4"
    if not os.path.exists(path):
        raise Http404("Video fayl topilmadi")
    return FileResponse(open(path, "rb"), content_type="video/mp4")


def pipeline_stats_api(request):
    """Kafka consumer statistikasi — deepstream panel uchun."""
    from apps.attendance.models import TrackSession, LessonAttendance, RecognitionEvent
    from django.utils import timezone
    from datetime import timedelta

    now = timezone.now()
    since = now - timedelta(hours=3)

    accepted = RecognitionEvent.objects.filter(
        decision="accepted", recognized_at__gte=since
    ).count()
    rejected = RecognitionEvent.objects.filter(
        decision="rejected", recognized_at__gte=since
    ).count()
    total_tracks = TrackSession.objects.filter(
        camera_id=1, updated_at__gte=since
    ).count()

    return JsonResponse({
        "accepted": accepted,
        "rejected": rejected,
        "total": total_tracks,
        "skipped": max(0, total_tracks - accepted - rejected),
    })


# ─── LIVE ROOM ATTENDANCE ────────────────────────────────────────────────────

def room_attendance(request, camera_id):
    """Kamera xonasi uchun jonli davomat sahifasi."""
    camera = get_object_or_404(Camera, pk=camera_id)
    stream_url = (camera.stream_url or "").rstrip("/")
    if stream_url and not stream_url.endswith(".m3u8"):
        stream_url = stream_url + "/index.m3u8"
    return render(request, "monitoring/room_attendance.html", {
        "camera": camera,
        "camera_id": camera_id,
        "stream_url": stream_url,
    })


def mjpeg_stream(request, camera_id):
    """
    Annotatsiyalangan MJPEG oqimi — brauzer <img> orqali ko'rsatadi.
    AI threadi 0.4s da bir yangi kadr tayyorlaydi.
    Biz esa so'nggi kadrni ~15fps da yuboramiz (silliq video uchun).
    """
    from apps.monitoring.camera_manager import CameraFrameManager, _no_signal_jpeg

    manager = CameraFrameManager()
    manager.ensure_running(camera_id)

    boundary = b"--mjpegframe\r\nContent-Type: image/jpeg\r\n\r\n"
    no_sig   = _no_signal_jpeg()

    def frame_gen():
        try:
            while True:
                jpeg = manager.get_jpeg(camera_id) or no_sig
                yield boundary + jpeg + b"\r\n"
                time.sleep(0.067)   # ~15 fps
        except GeneratorExit:
            pass    # brauzer tab yopildi — to'xtatamiz

    resp = StreamingHttpResponse(
        frame_gen(),
        content_type="multipart/x-mixed-replace; boundary=mjpegframe",
    )
    resp["Cache-Control"]    = "no-cache, no-store, must-revalidate"
    resp["X-Accel-Buffering"] = "no"
    return resp


def room_attendance_api(request, camera_id):
    """
    JSON: kamera xonasi uchun jadval + davomat holati.
    - Hozir dars bo'lsa: aktiv darsning to'liq davomati
    - Dars bo'lmasa: bugungi (yoki so'nggi) barcha darslar ro'yxati
    JavaScript har 3 sekundda so'raydi.
    """
    from apps.attendance.services import ActiveScheduleService
    from zoneinfo import ZoneInfo

    svc = ActiveScheduleService()
    now = timezone.now()
    tz  = ZoneInfo("Asia/Tashkent")
    local_now = now.astimezone(tz)

    # Classroom ma'lumotlari (har doim)
    classroom = svc.get_classroom_for_camera(camera_id)
    classroom_info = {
        "name":   classroom.class_room_name if classroom else "",
        "org":    classroom.organization.organization_name if classroom else "",
        "org_id": classroom.organization.organization_id if classroom else None,
    } if classroom else {}

    # Hozirgi aktiv dars
    active_schedule = svc.get_for_camera(camera_id, now=now)

    if active_schedule:
        data = _build_attendance_payload(camera_id, active_schedule, now)
        data["classroom"] = classroom_info
        return JsonResponse(data)

    # Dars yo'q — kun jadvalini ko'rsatamiz
    day_schedules, sched_date = svc.get_day_schedules(camera_id, date=local_now.date())
    today_list = [
        {
            "id":            s.id,
            "lesson_number": s.lesson_number,
            "class_name":    s.class_obj.class_name if s.class_obj else "",
            "start_at":      s.start_at.strftime("%H:%M"),
            "end_at":        s.end_at.strftime("%H:%M"),
        }
        for s in day_schedules
    ]
    is_today = sched_date == local_now.date() if sched_date else False
    return JsonResponse({
        "no_schedule": True,
        "classroom": classroom_info,
        "schedule_date": str(sched_date) if sched_date else None,
        "is_today": is_today,
        "today": today_list,
    })


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _build_attendance_payload(camera_id: int, schedule: "ExternalSchedule", now) -> dict:
    from apps.integrations.models import ExternalStudent

    all_students = list(
        ExternalStudent.objects
        .filter(class_obj=schedule.class_obj)
        .values("id", "pinfl", "full_name")
    )
    student_map = {s["pinfl"]: s for s in all_students}

    # LessonAttendance yozuvlari
    la_qs = (
        LessonAttendance.objects
        .filter(schedule=schedule)
        .select_related("recognition_event", "student")
    )
    la_map: dict[int, LessonAttendance] = {la.student_id: la for la in la_qs}

    # Front fotolar
    pinfls = [s["pinfl"] for s in all_students]
    front_photos = _get_front_photos(pinfls)

    arrived = []
    not_arrived = []

    for s in all_students:
        la = la_map.get(s["id"])
        front = front_photos.get(s["pinfl"])
        if la and la.status in (LessonAttendance.STATUS_PRESENT, LessonAttendance.STATUS_LATE):
            ev = la.recognition_event
            arrived.append({
                "pinfl": s["pinfl"],
                "full_name": s["full_name"],
                "arrived_at": _local(la.arrived_at, "%H:%M"),
                "is_late": la.is_late,
                "status": la.status,
                "recognition_image": _fix_minio_url(ev.image.url) if ev and ev.image else None,
                "front_photo": front,
            })
        else:
            not_arrived.append({
                "pinfl": s["pinfl"],
                "full_name": s["full_name"],
                "front_photo": front,
            })

    return {
        "no_schedule": False,
        "schedule": {
            "id": schedule.id,
            "class_name": schedule.class_obj.class_name if schedule.class_obj else "",
            "lesson_number": schedule.lesson_number,
            "start_at": schedule.start_at.strftime("%H:%M"),
            "end_at": schedule.end_at.strftime("%H:%M"),
            "date": str(schedule.date),
        },
        "total": len(all_students),
        "arrived_count": len(arrived),
        "not_arrived_count": len(not_arrived),
        "arrived": arrived,
        "not_arrived": not_arrived,
    }


def _today_schedules_for_camera(camera_id: int, today) -> list:
    classroom = ExternalClassroom.objects.filter(camera_id=camera_id).first()
    if not classroom:
        return []
    qs = (
        ExternalSchedule.objects
        .filter(classroom=classroom, date=today)
        .select_related("class_obj")
        .order_by("start_at")
    )
    return [
        {
            "lesson_number": s.lesson_number,
            "class_name": s.class_obj.class_name if s.class_obj else "",
            "start_at": s.start_at.strftime("%H:%M"),
            "end_at": s.end_at.strftime("%H:%M"),
        }
        for s in qs
    ]




class MonitoringStatsAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        date_str = request.query_params.get("date")
        org_id = request.query_params.get("org")

        day = _parse_day(date_str)
        if day is None:
            return Response({"error": "date format: YYYY-MM-DD"}, status=400)

        qs = RecognitionEvent.objects.filter(recognized_at__date=day)
        if org_id:
            qs = qs.filter(organization_id=org_id)

        accepted = qs.filter(decision=RecognitionEvent.DECISION_ACCEPTED).count()
        review   = qs.filter(decision=RecognitionEvent.DECISION_REVIEW).count()
        rejected = qs.filter(decision=RecognitionEvent.DECISION_REJECTED).count()

        return Response({
            "date": str(day),
            "accepted": accepted,
            "review": review,
            "rejected": rejected,
            "total": accepted + review + rejected,
        })


class MonitoringLiveAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        date_str = request.query_params.get("date")
        org_id = request.query_params.get("org")
        limit = int(request.query_params.get("limit", 30))

        day = _parse_day(date_str)
        if day is None:
            return Response({"error": "date format: YYYY-MM-DD"}, status=400)

        qs = RecognitionEvent.objects.filter(
            recognized_at__date=day,
        ).select_related("camera").order_by("-recognized_at")

        if org_id:
            qs = qs.filter(organization_id=org_id)

        events = list(qs[:limit])
        pinfls = [e.pinfl for e in events if e.pinfl]
        front_photos = _get_front_photos(pinfls)

        results = []
        for e in events:
            results.append({
                "id": e.id,
                "full_name": e.full_name or "—",
                "pinfl": e.pinfl or "—",
                "camera": str(e.camera) if e.camera else "—",
                "recognized_at": _local(e.recognized_at, "%H:%M:%S"),
                "similarity": round(e.similarity * 100, 1) if e.similarity else None,
                "decision": e.decision,
                "image": _fix_minio_url(e.image.url) if e.image else None,
                "reference_image": front_photos.get(e.pinfl),
            })

        return Response(results)


class MonitoringHourlyAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        date_str = request.query_params.get("date")
        org_id = request.query_params.get("org")

        day = _parse_day(date_str)
        if day is None:
            return Response({"error": "date format: YYYY-MM-DD"}, status=400)

        qs = RecognitionEvent.objects.filter(recognized_at__date=day)
        if org_id:
            qs = qs.filter(organization_id=org_id)

        rows = (
            qs.annotate(hour=TruncHour("recognized_at"))
            .values("hour")
            .annotate(
                accepted=Count("id", filter=Q(decision=RecognitionEvent.DECISION_ACCEPTED)),
                review=Count("id", filter=Q(decision=RecognitionEvent.DECISION_REVIEW)),
                rejected=Count("id", filter=Q(decision=RecognitionEvent.DECISION_REJECTED)),
            )
            .order_by("hour")
        )

        labels, accepted_data, review_data, rejected_data = [], [], [], []
        for row in rows:
            labels.append(_local(row["hour"], "%H:00"))
            accepted_data.append(row["accepted"])
            review_data.append(row["review"])
            rejected_data.append(row["rejected"])

        return Response({
            "labels": labels,
            "accepted": accepted_data,
            "review": review_data,
            "rejected": rejected_data,
        })


class MonitoringReviewAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        date_str = request.query_params.get("date")
        org_id = request.query_params.get("org")

        day = _parse_day(date_str)
        if day is None:
            return Response({"error": "date format: YYYY-MM-DD"}, status=400)

        qs = RecognitionEvent.objects.filter(
            decision=RecognitionEvent.DECISION_REVIEW,
            recognized_at__date=day,
        ).select_related("camera").order_by("-recognized_at")

        if org_id:
            qs = qs.filter(organization_id=org_id)

        events = list(qs)
        pinfls = [e.pinfl for e in events if e.pinfl]
        front_photos = _get_front_photos(pinfls)

        results = []
        for e in events:
            results.append({
                "id": e.id,
                "full_name": e.full_name or "—",
                "pinfl": e.pinfl or "—",
                "camera": str(e.camera) if e.camera else "—",
                "recognized_at": _local(e.recognized_at, "%H:%M:%S"),
                "similarity": round(e.similarity * 100, 1) if e.similarity else None,
                "image": _fix_minio_url(e.image.url) if e.image else None,
                "reference_image": front_photos.get(e.pinfl),
            })

        return Response(results)


class MonitoringCamerasAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        org_id = request.query_params.get("org")

        qs = Camera.objects.filter(stream_url__isnull=False).exclude(stream_url="").order_by("name")
        if org_id:
            qs = qs.filter(organization_id=org_id)

        results = []
        for cam in qs:
            stream = cam.stream_url.rstrip("/")
            if not stream.endswith(".m3u8"):
                stream = stream + "/index.m3u8"
            results.append({
                "id": cam.id,
                "name": cam.name,
                "stream_url": stream,
                "organization_id": cam.organization_id,
                "is_active": cam.is_active_stream,
            })

        return Response(results)


class MonitoringCameraAttendanceAPIView(APIView):
    """
    Bitta kamera xonasining bugungi davomati:
    - O'qituvchi, fan, sinf (jadvaldan)
    - Kelganlar (accepted RecognitionEvent + asl front rasm)
    - Kelmaganlar (sinfda bor lekin kelmagan o'quvchilar)
    """
    permission_classes = [AllowAny]

    def get(self, request, camera_id):
        date_str = request.query_params.get("date")
        day = _parse_day(date_str)
        if day is None:
            return Response({"error": "date format: YYYY-MM-DD"}, status=400)

        try:
            camera = Camera.objects.get(pk=camera_id)
        except Camera.DoesNotExist:
            return Response({"error": "Kamera topilmadi"}, status=404)

        stream = (camera.stream_url or "").rstrip("/")
        if stream and not stream.endswith(".m3u8"):
            stream = stream + "/index.m3u8"

        # --- O'qituvchi va fan: Camera → AuditoriumCamera → Auditorium → Schedule ---
        schedule_info = _get_schedule_info(camera_id, day)

        # --- Sinf va o'quvchilar ro'yxati: Camera → ExternalClassroom → ExternalSchedule → ExternalClass ---
        all_students = _get_class_students(camera_id, day)

        # --- Kelganlar: bugun shu kamerada accepted hodisalar ---
        arrived_events = (
            RecognitionEvent.objects
            .filter(camera_id=camera_id, recognized_at__date=day, decision=RecognitionEvent.DECISION_ACCEPTED)
            .select_related("student")
            .order_by("recognized_at")
        )

        # pinfl → event mapping
        arrived_map = {}
        for ev in arrived_events:
            pinfl = ev.pinfl or (ev.student.pinfl if ev.student else None)
            if pinfl and pinfl not in arrived_map:
                arrived_map[pinfl] = ev

        # Front fotolar: sinfda bo'lgan o'quvchilar uchun
        all_pinfls = list(all_students.keys())
        front_photos = _get_front_photos(all_pinfls)

        arrived_list = []
        not_arrived_list = []

        for pinfl, student_info in all_students.items():
            ev = arrived_map.get(pinfl)
            front_url = front_photos.get(pinfl)

            if ev:
                arrived_list.append({
                    "pinfl": pinfl,
                    "full_name": student_info["full_name"],
                    "recognized_at": _local(ev.recognized_at, "%H:%M:%S"),
                    "similarity": round(ev.similarity * 100, 1) if ev.similarity else None,
                    "recognition_image": ev.image.url if ev.image else None,
                    "front_photo": front_url,
                })
            else:
                not_arrived_list.append({
                    "pinfl": pinfl,
                    "full_name": student_info["full_name"],
                    "front_photo": front_url,
                })

        # Sinfda yo'q lekin shu kameraga keldigan talabalar ham kelganlar ro'yxatiga qo'shish
        extra_pinfls = set(arrived_map.keys()) - set(all_students.keys())
        extra_front_photos = _get_front_photos(list(extra_pinfls))
        for pinfl in extra_pinfls:
            ev = arrived_map[pinfl]
            arrived_list.append({
                "pinfl": pinfl,
                "full_name": ev.full_name or "—",
                "recognized_at": _local(ev.recognized_at, "%H:%M:%S"),
                "similarity": round(ev.similarity * 100, 1) if ev.similarity else None,
                "recognition_image": ev.image.url if ev.image else None,
                "front_photo": extra_front_photos.get(pinfl),
            })

        arrived_list.sort(key=lambda x: x["recognized_at"])

        return Response({
            "camera_id": camera_id,
            "camera_name": camera.name,
            "stream_url": stream,
            "date": str(day),
            "schedule": schedule_info,
            "total_students": len(all_students),
            "arrived_count": len(arrived_list),
            "not_arrived_count": len(not_arrived_list),
            "arrived": arrived_list,
            "not_arrived": not_arrived_list,
        })


# ─── Yordamchi funksiyalar ───────────────────────────────────────────────────

def _parse_day(date_str):
    if date_str:
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            return None
    return timezone.now().date()


def _get_schedule_info(camera_id: int, day: datetime.date) -> dict:
    """Camera → AuditoriumCamera → Auditorium → academics.Schedule → o'qituvchi + fan"""
    aud_cam = AuditoriumCamera.objects.filter(camera_id=camera_id).select_related("auditorium").first()
    if not aud_cam:
        return {}

    # lesson_date BigIntegerField — Unix timestamp (soniyada yoki millisekundda)
    # Ikkala formatni ham sinab ko'ramiz
    day_start = int(datetime.datetime.combine(day, datetime.time.min).timestamp())
    day_end   = int(datetime.datetime.combine(day, datetime.time.max).timestamp())

    schedule = (
        Schedule.objects
        .filter(auditorium=aud_cam.auditorium)
        .filter(
            Q(lesson_date__gte=day_start, lesson_date__lte=day_end) |
            Q(lesson_date__gte=day_start * 1000, lesson_date__lte=day_end * 1000)
        )
        .select_related("employee", "subject", "group")
        .order_by("lesson_date")
        .first()
    )

    if not schedule:
        return {}

    return {
        "teacher": schedule.employee.full_name if schedule.employee else None,
        "subject": schedule.subject.name if schedule.subject else None,
        "group": schedule.group.name if schedule.group else None,
        "lesson_pair": schedule.lesson_pair,
    }


def _get_class_students(camera_id: int, day: datetime.date) -> dict:
    """Camera → ExternalClassroom → ExternalSchedule → ExternalClass → ExternalStudent"""
    classroom = ExternalClassroom.objects.filter(camera_id=camera_id).first()
    if not classroom:
        return {}

    ext_schedule = (
        classroom.schedules
        .filter(date=day)
        .select_related("class_obj")
        .first()
    )
    if not ext_schedule:
        return {}

    students = (
        ext_schedule.class_obj.students
        .all()
        .values("pinfl", "full_name")
    )

    return {s["pinfl"]: {"full_name": s["full_name"]} for s in students}


def _fix_minio_url(url: str) -> str:
    """Docker ichki minio:9000 → brauzer ko'ra oladigan localhost:9000."""
    if url:
        return url.replace("http://minio:9000", "http://localhost:9000")
    return url


def _get_front_photos(pinfls: list) -> dict:
    """pinfl → front foto URL"""
    if not pinfls:
        return {}

    photos = (
        ExternalStudentPhoto.objects
        .filter(student__pinfl__in=pinfls, photo_type="front")
        .select_related("student")
        .exclude(image="")
        .exclude(image=None)
    )

    result = {}
    for p in photos:
        if p.image:
            try:
                result[p.student.pinfl] = _fix_minio_url(p.image.url)
            except Exception:
                pass
    return result


# ─── DAVOMAT QIYOSI ──────────────────────────────────────────────────────────

def attendance_comparison(request):
    """Davomat rasmi vs Asl rasm qiyosi sahifasi."""
    organizations = ExternalOrganization.objects.order_by("organization_name")
    return render(request, "monitoring/attendance_comparison.html", {
        "organizations": organizations,
    })


class MonitoringComparisonAPIView(APIView):
    """
    GET /monitoring/api/comparison/?date=2026-05-05&org=<id>&decision=accepted&limit=50
    Har bir hodisa uchun: davomat rasmi + o'quvchining asl (front) rasmi
    """
    permission_classes = [AllowAny]

    def get(self, request):
        date_str  = request.query_params.get("date")
        org_id    = request.query_params.get("org")
        decision  = request.query_params.get("decision", "")
        limit     = min(int(request.query_params.get("limit", 50)), 200)

        day = _parse_day(date_str)
        if day is None:
            return Response({"error": "date format: YYYY-MM-DD"}, status=400)

        qs = (
            RecognitionEvent.objects
            .filter(recognized_at__date=day)
            .select_related("student", "camera")
            .annotate(
                decision_rank=Case(
                    When(decision="accepted", then=Value(0)),
                    When(decision="review",   then=Value(1)),
                    When(decision="rejected", then=Value(2)),
                    default=Value(3),
                    output_field=IntegerField(),
                )
            )
            .order_by("decision_rank", "-recognized_at")
        )
        if org_id:
            qs = qs.filter(organization_id=org_id)
        if decision in ("accepted", "review", "rejected"):
            qs = qs.filter(decision=decision)

        events = list(qs[:limit])

        pinfls = [e.pinfl for e in events if e.pinfl]
        front_photos = _get_front_photos(pinfls)

        results = []
        for e in events:
            results.append({
                "id":               e.id,
                "full_name":        e.full_name or "—",
                "pinfl":            e.pinfl or "—",
                "camera":           str(e.camera) if e.camera else "—",
                "recognized_at":    _local(e.recognized_at, "%Y-%m-%d %H:%M:%S"),
                "similarity":       round(e.similarity * 100, 1) if e.similarity else None,
                "decision":         e.decision,
                "attendance_image": _fix_minio_url(e.image.url) if e.image else None,
                "reference_image":  front_photos.get(e.pinfl),
            })

        return Response({
            "date":   str(day),
            "count":  len(results),
            "results": results,
        })
