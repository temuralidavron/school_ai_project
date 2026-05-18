"""
Davomat tizimining aniqligi va tezligi statistikasi.
Prezentatsiya uchun: timing, qarorlar taqsimoti, qamrov.

Ishlatish:
    python manage.py attendance_stats
    python manage.py attendance_stats --org-id 32
    python manage.py attendance_stats --org-id 32 --days 7
    python manage.py attendance_stats --date-from 2026-05-01 --date-to 2026-05-15
"""

import datetime
import statistics
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Max, Min, Q
from django.utils import timezone

from apps.attendance.models import LessonAttendance, RecognitionEvent
from apps.integrations.models import ExternalOrganization, ExternalSchedule, ExternalStudent


class Command(BaseCommand):
    help = "Davomat tizimining aniqligi va tezligi statistikasi (prezentatsiya uchun)"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, default=None, help="Tashkilot organization_id (ixtiyoriy)")
        parser.add_argument("--date-from", type=str, default=None, help="Boshlanish sanasi YYYY-MM-DD")
        parser.add_argument("--date-to", type=str, default=None, help="Tugash sanasi YYYY-MM-DD")
        parser.add_argument("--days", type=int, default=30, help="Oxirgi N kun (default: 30)")
        parser.add_argument("--no-coverage", action="store_true", help="Jadval qamrovini o'tkazib yuborish (sekin bo'lsa)")

    def handle(self, *args, **options):
        org_id = options["org_id"]
        days = options["days"]

        if options["date_from"]:
            date_from = datetime.date.fromisoformat(options["date_from"])
        else:
            date_from = timezone.now().date() - datetime.timedelta(days=days)

        if options["date_to"]:
            date_to = datetime.date.fromisoformat(options["date_to"])
        else:
            date_to = timezone.now().date()

        self.stdout.write("\n" + "=" * 65)
        self.stdout.write("  DAVOMAT TIZIMI — TAHLIL VA STATISTIKA")
        self.stdout.write("=" * 65)
        self.stdout.write(f"  Davr    : {date_from}  →  {date_to}")

        if org_id:
            org = ExternalOrganization.objects.filter(organization_id=org_id).first()
            name = org.organization_name if org else f"id={org_id}"
            self.stdout.write(f"  Maktab  : {name}")

        self.stdout.write("=" * 65 + "\n")

        self._recognition_stats(date_from, date_to, org_id)
        self._timing_stats(date_from, date_to, org_id)
        self._lesson_attendance_stats(date_from, date_to, org_id)

        if not options["no_coverage"]:
            self._schedule_coverage(date_from, date_to, org_id)

        self.stdout.write("=" * 65 + "\n")

    # ─── 1. YUZ TANISH QARORLARI ─────────────────────────────────────────────

    def _recognition_stats(self, date_from, date_to, org_id):
        self.stdout.write(self.style.HTTP_INFO("[ 1. YUZ TANISH QARORLARI ]"))

        qs = RecognitionEvent.objects.filter(
            recognized_at__date__gte=date_from,
            recognized_at__date__lte=date_to,
        )
        if org_id:
            qs = qs.filter(organization_id=org_id)

        total = qs.count()
        if total == 0:
            self.stdout.write("  Ma'lumot topilmadi\n")
            return

        counts = {
            row["decision"]: row["cnt"]
            for row in qs.values("decision").annotate(cnt=Count("id"))
        }
        accepted = counts.get("accepted", 0)
        review   = counts.get("review", 0)
        rejected = counts.get("rejected", 0)

        sim = qs.filter(decision="accepted", similarity__isnull=False).aggregate(
            avg=Avg("similarity"), mn=Min("similarity"), mx=Max("similarity")
        )

        self.stdout.write(f"  Jami tanish urinishlari : {total:,}")
        self.stdout.write(f"  ✓ Qabul qilindi         : {accepted:>6,}  ({_pct(accepted, total)}%)")
        self.stdout.write(f"  ? Ko'rib chiqish kerak  : {review:>6,}  ({_pct(review,   total)}%)")
        self.stdout.write(f"  ✗ Rad etildi            : {rejected:>6,}  ({_pct(rejected, total)}%)")

        if sim["avg"]:
            self.stdout.write(f"\n  O'xshashlik (accepted holatlar):")
            self.stdout.write(f"    O'rtacha  : {sim['avg'] * 100:.1f}%")
            self.stdout.write(f"    Minimum   : {sim['mn']  * 100:.1f}%")
            self.stdout.write(f"    Maximum   : {sim['mx']  * 100:.1f}%")

        if accepted > 0:
            buckets = [
                ("55–65%", 0.55, 0.65),
                ("65–75%", 0.65, 0.75),
                ("75–85%", 0.75, 0.85),
                ("85%+  ", 0.85, 1.01),
            ]
            self.stdout.write(f"\n  O'xshashlik taqsimoti (accepted):")
            for label, lo, hi in buckets:
                cnt = qs.filter(decision="accepted", similarity__gte=lo, similarity__lt=hi).count()
                bar = "█" * (cnt * 25 // accepted)
                self.stdout.write(f"    {label}: {bar:<26} {cnt}")

        self.stdout.write("")

    # ─── 2. DAVOMAT TEZLIGI ──────────────────────────────────────────────────

    def _timing_stats(self, date_from, date_to, org_id):
        self.stdout.write(self.style.HTTP_INFO("[ 2. DAVOMAT TEZLIGI  (dars boshlanganidan keyingi daqiqalar) ]"))

        qs = (
            LessonAttendance.objects
            .filter(
                schedule__date__gte=date_from,
                schedule__date__lte=date_to,
                status__in=["present", "late"],
                arrived_at__isnull=False,
            )
            .select_related("schedule")
        )
        if org_id:
            qs = qs.filter(schedule__organization__organization_id=org_id)

        deltas = []
        for la in qs.iterator(chunk_size=500):
            s = la.schedule
            tz = ZoneInfo(s.timezone or "Asia/Tashkent")
            lesson_start = datetime.datetime.combine(s.date, s.start_at, tzinfo=tz)
            delta = (la.arrived_at - lesson_start).total_seconds() / 60
            if -90 <= delta <= 240:
                deltas.append(delta)

        n = len(deltas)
        if n == 0:
            self.stdout.write("  Timing ma'lumotlari topilmadi\n")
            return

        deltas.sort()

        early         = sum(1 for d in deltas if d < 0)
        on_time       = sum(1 for d in deltas if 0 <= d <= 5)
        slightly_late = sum(1 for d in deltas if 5 < d <= 15)
        very_late     = sum(1 for d in deltas if d > 15)

        self.stdout.write(f"  Tahlil qilingan yozuvlar : {n:,}")
        self.stdout.write(f"\n  O'rtacha vaqt    : {statistics.mean(deltas):+.1f} daqiqa")
        self.stdout.write(f"  Mediana          : {statistics.median(deltas):+.1f} daqiqa")
        self.stdout.write(f"  P10 (erta kelar) : {_percentile(deltas, 10):+.1f} daqiqa")
        self.stdout.write(f"  P25              : {_percentile(deltas, 25):+.1f} daqiqa")
        self.stdout.write(f"  P75              : {_percentile(deltas, 75):+.1f} daqiqa")
        self.stdout.write(f"  P90 (kech kelar) : {_percentile(deltas, 90):+.1f} daqiqa")
        self.stdout.write(f"\n  Vaqt bo'yicha taqsimot:")
        self.stdout.write(f"    Darsdan oldin (< 0 daqiqa)  : {_bar(early,         n)} {early}  ({_pct(early,         n)}%)")
        self.stdout.write(f"    O'z vaqtida   (0–5 daqiqa)  : {_bar(on_time,       n)} {on_time}  ({_pct(on_time,       n)}%)")
        self.stdout.write(f"    Biroz kech    (5–15 daqiqa) : {_bar(slightly_late, n)} {slightly_late}  ({_pct(slightly_late, n)}%)")
        self.stdout.write(f"    Kech          (> 15 daqiqa) : {_bar(very_late,     n)} {very_late}  ({_pct(very_late,     n)}%)")
        self.stdout.write("")

    # ─── 3. DARS DAVOMATI HOLATLARI ──────────────────────────────────────────

    def _lesson_attendance_stats(self, date_from, date_to, org_id):
        self.stdout.write(self.style.HTTP_INFO("[ 3. DARS DAVOMATI HOLATLARI ]"))

        qs = LessonAttendance.objects.filter(
            schedule__date__gte=date_from,
            schedule__date__lte=date_to,
        )
        if org_id:
            qs = qs.filter(schedule__organization__organization_id=org_id)

        total = qs.count()
        if total == 0:
            self.stdout.write("  Ma'lumot topilmadi\n")
            return

        rows = list(qs.values("status").annotate(cnt=Count("id")).order_by("-cnt"))
        status_labels = {
            "present":    "✓ Keldi",
            "late":       "⏰ Kech keldi",
            "absent":     "✗ Kelmadi",
            "wrong_room": "⚠ Boshqa xona",
        }

        self.stdout.write(f"  Jami yozuvlar   : {total:,}")
        self.stdout.write(f"\n  Holat taqsimoti :")
        for row in rows:
            label = status_labels.get(row["status"], row["status"])
            cnt = row["cnt"]
            self.stdout.write(f"    {label:<22}: {_bar(cnt, total)} {cnt:>5}  ({_pct(cnt, total)}%)")

        arrived = sum(r["cnt"] for r in rows if r["status"] in ("present", "late"))
        self.stdout.write(f"\n  Davomat foizi (keldi + kech keldi) : {_pct(arrived, total)}%")
        self.stdout.write("")

    # ─── 4. JADVAL QAMROVI ───────────────────────────────────────────────────

    def _schedule_coverage(self, date_from, date_to, org_id):
        self.stdout.write(self.style.HTTP_INFO("[ 4. JADVAL QAMROVI (har dars uchun o'rtacha kelish %) ]"))

        schedules_qs = ExternalSchedule.objects.filter(
            date__gte=date_from,
            date__lte=date_to,
        ).select_related("class_obj")
        if org_id:
            schedules_qs = schedules_qs.filter(organization__organization_id=org_id)

        total_schedules = schedules_qs.count()
        if total_schedules == 0:
            self.stdout.write("  Jadval ma'lumotlari topilmadi\n")
            return

        schedules_with_records = (
            LessonAttendance.objects
            .filter(schedule__in=schedules_qs)
            .values("schedule_id")
            .distinct()
            .count()
        )

        # O'rtacha coverage — har bir dars uchun kelganlar / jami o'quvchilar
        coverages = []
        empty_schedules = 0

        for schedule in schedules_qs.iterator(chunk_size=200):
            total_students = ExternalStudent.objects.filter(class_obj=schedule.class_obj).count()
            if total_students == 0:
                empty_schedules += 1
                continue
            arrived = LessonAttendance.objects.filter(
                schedule=schedule, status__in=["present", "late"]
            ).count()
            coverages.append(arrived * 100 / total_students)

        if not coverages:
            self.stdout.write("  Sinf ma'lumotlari topilmadi\n")
            return

        avg_cov = sum(coverages) / len(coverages)
        n = len(coverages)

        self.stdout.write(f"  Jami darslar                 : {total_schedules:,}")
        self.stdout.write(f"  Yozuv bor darslar            : {schedules_with_records:,}  ({_pct(schedules_with_records, total_schedules)}%)")
        self.stdout.write(f"\n  O'rtacha kelish foizi        : {avg_cov:.1f}%")

        buckets = [
            ("0%     (hech kim kelmadi)", lambda c: c == 0),
            ("1–25%                    ", lambda c: 0 < c <= 25),
            ("26–50%                   ", lambda c: 25 < c <= 50),
            ("51–75%                   ", lambda c: 50 < c <= 75),
            ("76–99%                   ", lambda c: 75 < c < 100),
            ("100%   (hamma keldi)     ", lambda c: c == 100),
        ]
        self.stdout.write(f"\n  Darslar qamrovi taqsimoti:")
        for label, condition in buckets:
            cnt = sum(1 for c in coverages if condition(c))
            self.stdout.write(f"    {label}: {_bar(cnt, n)} {cnt}")

        self.stdout.write("")


# ─── Yordamchi funksiyalar ────────────────────────────────────────────────────

def _pct(part: int, total: int) -> int:
    if total == 0:
        return 0
    return round(part * 100 / total)


def _bar(count: int, total: int, width: int = 28) -> str:
    if total == 0:
        return " " * width
    filled = round(count * width / total)
    return ("█" * filled).ljust(width)


def _percentile(sorted_list: list, p: int) -> float:
    if not sorted_list:
        return 0.0
    idx = max(0, min(int(len(sorted_list) * p / 100), len(sorted_list) - 1))
    return sorted_list[idx]
