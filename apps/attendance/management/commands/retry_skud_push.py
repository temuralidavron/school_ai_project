import logging

from django.core.management.base import BaseCommand
from django.db.models import F
from django.utils import timezone

from apps.attendance.models import RecognitionEvent
from apps.integrations.services import SkudAttendancePushService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "SKUD ga yuborilmagan yoki vaqtincha xato bo'lgan davomatlarni qayta yuboradi"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, default=None, help="Faqat shu tashkilot")
        parser.add_argument("--limit", type=int, default=100, help="Bir marta qayta yuborish soni")
        parser.add_argument("--dry-run", action="store_true", help="Faqat ko'rsatadi, yubormaydi")
        parser.add_argument("--show-permanent", action="store_true", help="Doimiy skip larni ham ko'rsatish")

    def handle(self, *args, **options):
        org_id = options["org_id"]
        limit = options["limit"]
        dry_run = options["dry_run"]

        # Faqat vaqtincha xato bo'lganlar — "skip:" prefikslilari permanent, tegmaymiz
        qs = RecognitionEvent.objects.filter(
            decision=RecognitionEvent.DECISION_ACCEPTED,
            skud_pushed_at__isnull=True,
        ).exclude(
            skud_push_error__startswith="skip:"
        ).select_related("student", "student__organization").order_by("recognized_at")

        if org_id:
            qs = qs.filter(organization_id=org_id)

        total = qs.count()

        # Doimiy skiplar statistikasi
        permanent_count = RecognitionEvent.objects.filter(
            decision=RecognitionEvent.DECISION_ACCEPTED,
            skud_pushed_at__isnull=True,
            skud_push_error__startswith="skip:",
        )
        if org_id:
            permanent_count = permanent_count.filter(organization_id=org_id)
        permanent_count = permanent_count.count()

        self.stdout.write(
            f"Qayta yuborish kerak: {total} ta | Doimiy skip: {permanent_count} ta"
        )

        if options["show_permanent"]:
            for ev in RecognitionEvent.objects.filter(
                decision=RecognitionEvent.DECISION_ACCEPTED,
                skud_pushed_at__isnull=True,
                skud_push_error__startswith="skip:",
            ).order_by("recognized_at")[:20]:
                self.stdout.write(
                    self.style.WARNING(
                        f"  [skip] event_id={ev.id} pinfl={ev.pinfl} "
                        f"reason={ev.skud_push_error}"
                    )
                )

        if total == 0:
            self.stdout.write(self.style.SUCCESS("Yuborish kerak bo'lgan davomat yo'q."))
            return

        if dry_run:
            for ev in qs[:limit]:
                self.stdout.write(
                    f"  [dry-run] event_id={ev.id} pinfl={ev.pinfl} "
                    f"vaqt={ev.recognized_at:%Y-%m-%d %H:%M} "
                    f"urinish={ev.skud_push_attempts} "
                    f"xato={ev.skud_push_error or '—'}"
                )
            return

        service = SkudAttendancePushService()
        pushed = 0
        permanent_skipped = 0
        failed = 0

        for ev in qs[:limit]:
            result = service.push_recognition_event(ev)
            status = result.get("status")

            if status == "pushed":
                RecognitionEvent.objects.filter(id=ev.id).update(
                    skud_pushed_at=timezone.now(),
                    skud_push_error=None,
                    skud_push_attempts=F("skud_push_attempts") + 1,
                )
                pushed += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ event_id={ev.id} pinfl={ev.pinfl} "
                        f"{'(duplicate)' if result.get('duplicate') else ''}"
                    )
                )

            elif status == "skip_permanent":
                reason = f"skip:{result.get('reason', 'unknown')}"
                RecognitionEvent.objects.filter(id=ev.id).update(
                    skud_push_error=reason,
                    skud_push_attempts=F("skud_push_attempts") + 1,
                )
                permanent_skipped += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  — event_id={ev.id} pinfl={ev.pinfl} "
                        f"doimiy skip: {result.get('reason')}"
                    )
                )

            else:
                detail = result.get("detail", "")[:100]
                error_msg = f"{result.get('reason', 'failed')}: {detail}".strip(": ")
                RecognitionEvent.objects.filter(id=ev.id).update(
                    skud_push_error=error_msg,
                    skud_push_attempts=F("skud_push_attempts") + 1,
                )
                failed += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"  ✗ event_id={ev.id} pinfl={ev.pinfl} "
                        f"reason={result.get('reason')} detail={detail}"
                    )
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Yakunlandi: ✓ {pushed} ta yuborildi | "
                f"— {permanent_skipped} ta doimiy skip | "
                f"✗ {failed} ta vaqtincha xato"
            )
        )
        if failed:
            self.stdout.write("Vaqtincha xatolar keyingi ishga tushirishda qayta uriniladi.")
