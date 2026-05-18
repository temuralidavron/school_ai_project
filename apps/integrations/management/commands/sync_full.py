"""
To'liq SKUD sync zanjiri — bitta tashkilot uchun.

Zanjir: sinflar → xonalar (+kamera bog'lash) → talabalar → jadval

Bu `sync_all_organizations` dan farqi: u faqat talaba+rasm+embedding
qiladi. Bu esa sinf/xona/jadval ni ham oladi (davomat ishlashi uchun shart).

Ishlatish:
    python manage.py sync_full --org-id 16
    python manage.py sync_full --org-id 16 --date 2026-05-19
    python manage.py sync_full --org-id 16 --with-photos
"""
from django.core.management.base import BaseCommand

from apps.integrations.services import SkudSyncService


class Command(BaseCommand):
    help = "To'liq SKUD sync: sinf → xona → talaba → jadval (bitta org)"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, required=True,
                            help="Tashkilot ID (225-maktab = 16)")
        parser.add_argument("--date", type=str, default=None,
                            help="Jadval sanasi YYYY-MM-DD (default: bugun)")
        parser.add_argument("--with-photos", action="store_true",
                            help="Talaba rasmlarini ham yuklab oladi")

    def handle(self, *args, **options):
        org_id = options["org_id"]
        svc = SkudSyncService()

        self.stdout.write(f"To'liq sync boshlandi: org={org_id}")
        try:
            result = svc.full_sync(
                organization_id=org_id,
                download_photos=options["with_photos"],
                target_date=options["date"],
            )
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"FAIL: {e}"))
            return

        for step, data in result.items():
            self.stdout.write(f"  {step:12s}: {data}")

        self.stdout.write(self.style.SUCCESS(
            "\nTo'liq sync yakunlandi. "
            "Endi: kamera↔xona bog'lash → embedding → run_camera_stream"
        ))
