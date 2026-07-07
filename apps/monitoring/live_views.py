"""
Jonli xona davomati — yangi ("live") sahifa.

Mavjud `room_attendance` sahifasidan farqi:
  - kelganlar o'xshashlik foizi bo'yicha kamayish tartibida saralanadi
  - har qatorda o'xshashlik foizi ko'rsatiladi
  - kameralar orasida tab bilan almashish (bir maktabdagi bir necha xona)
  - rasmga bosilganda lightbox (AI rasmi + asl rasm yonma-yon)

Mavjud kod (`views.py`, `room_attendance.html`) o'zgartirilmagan — bu alohida fayl.
"""
import os

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.cameras.models import Camera
from apps.integrations.models import ExternalStudent
from apps.attendance.models import LessonAttendance
from apps.attendance.services import ActiveScheduleService
from apps.monitoring.views import _get_front_photos, _fix_minio_url, _local


# Camera id -> asl video fayl yo'li (konteyner ichida). .env / settings orqali override.
_DEFAULT_VIDEO_MAP = {1: "/app/deepstream_data/sinf.mp4", 2: "/app/deepstream_data/11g.mp4"}
# Camera id -> DeepStream nvstreammux manba indeksi (MJPEG /mjpeg/<source>).
_DEFAULT_AI_SOURCE_MAP = {1: 0, 2: 1}


def _video_map() -> dict:
    return getattr(settings, "LIVE_VIDEO_MAP", _DEFAULT_VIDEO_MAP)


def _ai_source_for(camera_id: int) -> int:
    src_map = getattr(settings, "LIVE_AI_SOURCE_MAP", _DEFAULT_AI_SOURCE_MAP)
    return src_map.get(camera_id, camera_id - 1)


def live_room(request, camera_id):
    """Jonli davomat sahifasi (bitta kamera). Tab uchun boshqa kameralar ham beriladi."""
    camera = get_object_or_404(Camera, pk=camera_id)

    stream_url = (camera.stream_url or "").rstrip("/")
    if stream_url and not stream_url.endswith(".m3u8"):
        stream_url = stream_url + "/index.m3u8"

    nav_ids = sorted(_video_map().keys())
    nav_cameras = list(Camera.objects.filter(id__in=nav_ids).order_by("id"))

    return render(request, "monitoring/live_room.html", {
        "camera": camera,
        "camera_id": camera_id,
        "stream_url": stream_url,
        "nav_cameras": nav_cameras,
        "ai_source": _ai_source_for(camera_id),
    })


def original_video(request, camera_id):
    """Asl video faylni brauzerga stream qiladi (kameraga qarab boshqa fayl)."""
    path = _video_map().get(camera_id)
    if not path or not os.path.exists(path):
        raise Http404("Video fayl topilmadi")
    return FileResponse(open(path, "rb"), content_type="video/mp4")


def live_room_api(request, camera_id):
    """
    JSON: aktiv dars davomati (foiz bilan, saralangan) yoki bugungi jadval.
    Frontend har 3 sekundda so'raydi.
    """
    svc = ActiveScheduleService()
    now = timezone.now()

    classroom = svc.get_classroom_for_camera(camera_id)
    classroom_info = {
        "name": classroom.class_room_name if classroom else "",
        "org": classroom.organization.organization_name if classroom else "",
        "org_id": classroom.organization.organization_id if classroom else None,
    } if classroom else {}

    active_schedule = svc.get_for_camera(camera_id, now=now)
    if active_schedule:
        data = _build_live_payload(active_schedule)
        data["classroom"] = classroom_info
        return JsonResponse(data)

    day_schedules, sched_date = svc.get_day_schedules(camera_id)
    today_list = [
        {
            "id": s.id,
            "lesson_number": s.lesson_number,
            "class_name": s.class_obj.class_name if s.class_obj else "",
            "start_at": s.start_at.strftime("%H:%M"),
            "end_at": s.end_at.strftime("%H:%M"),
        }
        for s in day_schedules
    ]
    return JsonResponse({
        "no_schedule": True,
        "classroom": classroom_info,
        "schedule_date": str(sched_date) if sched_date else None,
        "today": today_list,
    })


def _build_live_payload(schedule) -> dict:
    all_students = list(
        ExternalStudent.objects
        .filter(class_obj=schedule.class_obj)
        .values("id", "pinfl", "full_name")
    )

    la_qs = (
        LessonAttendance.objects
        .filter(schedule=schedule)
        .select_related("recognition_event")
    )
    la_map = {la.student_id: la for la in la_qs}

    pinfls = [s["pinfl"] for s in all_students]
    front_photos = _get_front_photos(pinfls)

    arrived = []
    not_arrived = []

    for s in all_students:
        la = la_map.get(s["id"])
        front = front_photos.get(s["pinfl"])

        is_present = la and la.status in (
            LessonAttendance.STATUS_PRESENT, LessonAttendance.STATUS_LATE
        )
        if is_present:
            ev = la.recognition_event
            # similarity 0..1 -> foiz; yo'q bo'lsa None (saralashda oxiriga tushadi)
            sim = None
            if ev and ev.similarity is not None:
                sim = round(ev.similarity * 100, 1)
            arrived.append({
                "pinfl": s["pinfl"],
                "full_name": s["full_name"],
                "arrived_at": _local(la.arrived_at, "%H:%M"),
                "is_late": la.is_late,
                "similarity": sim,
                "recognition_image": _fix_minio_url(ev.image.url) if ev and ev.image else None,
                "front_photo": front,
            })
        else:
            # absent + review + wrong_room — hammasi "kelmaganlar"
            not_arrived.append({
                "pinfl": s["pinfl"],
                "full_name": s["full_name"],
                "front_photo": front,
            })

    # O'xshashlik bo'yicha kamayish tartibi; foizsizlar oxirida
    arrived.sort(key=lambda x: (x["similarity"] is not None, x["similarity"] or 0.0), reverse=True)

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
