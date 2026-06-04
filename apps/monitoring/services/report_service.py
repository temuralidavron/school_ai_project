"""
Davomat hisobot matnini DB dan tayyorlaydi (Telegram bot uchun).

MUHIM: Bu servis FAQAT O'QIYDI (SELECT). Davomat pipeline'ga (cameras/web)
umuman tegmaydi — hech narsa yozmaydi, GPU ishlatmaydi. Light, indexed,
aggregated query'lar.

Funksiyalar:
    generate_lesson_report(schedule)   — bitta dars hisoboti (kelgan/kech/kelmagan)
    generate_daily_report(date, org)   — kunlik umumiy hisobot
    find_unsent_finished_lessons(org)  — tugagan, botga yuborilmagan darslar
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Tashkent")


def _class_label(class_obj) -> str:
    """ExternalClass → "9-A" ko'rinishi."""
    if not class_obj:
        return "—"
    deg = class_obj.class_degree
    name = class_obj.class_name or ""
    return f"{deg}-{name}" if deg else name


def _esc(text: str) -> str:
    """Telegram HTML uchun maxsus belgilarni qochiradi."""
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_lesson_report(schedule) -> str:
    """
    Bitta dars uchun to'liq hisobot matni (Telegram HTML).
    Kelganlar + kech kelganlar + kelmaganlar ro'yxati.
    """
    from apps.attendance.models import LessonAttendance
    from apps.integrations.models import ExternalStudent

    cls = _class_label(schedule.class_obj)
    start = schedule.start_at.strftime("%H:%M") if schedule.start_at else "?"
    end = schedule.end_at.strftime("%H:%M") if schedule.end_at else "?"

    # Sinfdagi jami o'quvchilar (kutilgan)
    total = ExternalStudent.objects.filter(class_obj=schedule.class_obj).count()

    # Davomat yozuvlari (bitta query, status bo'yicha)
    records = list(
        LessonAttendance.objects
        .filter(schedule=schedule)
        .select_related("student")
        .only("status", "is_late", "arrived_at", "student__full_name")
    )

    present, late, absent = [], [], []
    for r in records:
        name = r.student.full_name if r.student else "—"
        if r.status == LessonAttendance.STATUS_PRESENT:
            present.append(name)
        elif r.status == LessonAttendance.STATUS_LATE:
            t = r.arrived_at.astimezone(_TZ).strftime("%H:%M") if r.arrived_at else ""
            late.append(f"{name} ({t})")
        elif r.status == LessonAttendance.STATUS_ABSENT:
            absent.append(name)

    came = len(present) + len(late)
    pct = round(came * 100 / total) if total else 0

    lines = [
        f"📚 <b>{_esc(cls)}</b> — {schedule.lesson_number}-dars",
        f"🕐 {start}-{end}",
        f"📊 Keldi: <b>{came}/{total}</b> ({pct}%)",
        "",
    ]

    if present:
        lines.append(f"✅ <b>Kelganlar ({len(present)}):</b>")
        lines.extend(f"  • {_esc(n)}" for n in sorted(present))
        lines.append("")

    if late:
        lines.append(f"⏰ <b>Kech kelganlar ({len(late)}):</b>")
        lines.extend(f"  • {_esc(n)}" for n in late)
        lines.append("")

    if absent:
        lines.append(f"❌ <b>Kelmaganlar ({len(absent)}):</b>")
        lines.extend(f"  • {_esc(n)}" for n in sorted(absent))

    return "\n".join(lines).strip()


def generate_daily_report(report_date=None, organization_id: int = None) -> str:
    """
    Kun yakuni — barcha darslar bo'yicha umumiy statistika (sinf+dars foizi).
    """
    from django.db.models import Count, Q
    from apps.attendance.models import LessonAttendance
    from apps.integrations.models import ExternalSchedule, ExternalStudent

    if report_date is None:
        report_date = timezone.now().astimezone(_TZ).date()

    qs = ExternalSchedule.objects.filter(date=report_date).select_related("class_obj").order_by("start_at")
    if organization_id is not None:
        qs = qs.filter(organization__organization_id=organization_id)

    schedules = list(qs)
    if not schedules:
        return f"📅 <b>{report_date}</b>\nBugun dars topilmadi."

    lines = [f"📅 <b>Kunlik hisobot — {report_date}</b>", ""]
    total_came = total_exp = 0

    for s in schedules:
        total = ExternalStudent.objects.filter(class_obj=s.class_obj).count()
        if not total:
            continue
        agg = LessonAttendance.objects.filter(schedule=s).aggregate(
            came=Count("id", filter=~Q(status=LessonAttendance.STATUS_ABSENT))
        )
        came = agg["came"] or 0
        pct = round(came * 100 / total)
        cls = _class_label(s.class_obj)
        start = s.start_at.strftime("%H:%M") if s.start_at else "?"
        bar = "🟢" if pct >= 70 else ("🟡" if pct >= 40 else "🔴")
        lines.append(f"{bar} {start} {_esc(cls)} #{s.lesson_number}: {came}/{total} ({pct}%)")
        total_came += came
        total_exp += total

    if total_exp:
        overall = round(total_came * 100 / total_exp)
        lines.append("")
        lines.append(f"📊 <b>UMUMIY: {total_came}/{total_exp} ({overall}%)</b>")

    return "\n".join(lines)


def find_unsent_finished_lessons(organization_id: int = None) -> list:
    """
    Bugun tugagan, lekin botga hali yuborilmagan darslar ro'yxati.
    (end_at o'tgan + BotSentReport'da yo'q)
    """
    from apps.integrations.models import ExternalSchedule
    from apps.monitoring.models import BotSentReport

    now_local = timezone.now().astimezone(_TZ)
    today = now_local.date()
    now_time = now_local.time()

    qs = ExternalSchedule.objects.filter(
        date=today,
        end_at__lt=now_time,                 # tugagan
    ).select_related("class_obj")
    if organization_id is not None:
        qs = qs.filter(organization__organization_id=organization_id)

    sent_ids = set(
        BotSentReport.objects
        .filter(report_type=BotSentReport.TYPE_LESSON, schedule__date=today)
        .values_list("schedule_id", flat=True)
    )

    return [s for s in qs if s.id not in sent_ids]
