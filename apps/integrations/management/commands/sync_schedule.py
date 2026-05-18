"""
Dars jadvalini SKUD dan sync qiladi.

Ishlatish:
    python manage.py sync_schedule                  # bugun, barcha tashkilot
    python manage.py sync_schedule --tomorrow        # ertaga (kechasi cron uchun)
    python manage.py sync_schedule --date 2026-05-20 # aniq sana
    python manage.py sync_schedule --org-id 16       # faqat 225-maktab
"""
import datetime

from django.core.management.base import BaseCommand

from apps.integrations.models import ExternalOrganization
from apps.integrations.services import SkudSyncService


class Command(BaseCommand):
    help = "Dars jadvalini SKUD dan sync qiladi (bugun/ertaga/aniq sana)"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, default=None,
                            help="Faqat bitta tashkilot (yo'q bo'lsa hammasi)")
        parser.add_argument("--date", type=str, default=None,
                            help="Aniq sana YYYY-MM-DD")
        parser.add_argument("--tomorrow", action="store_true",
                            help="Ertangi kun jadvali (kechasi cron uchun)")
        parser.add_argument("--today-and-tomorrow", action="store_true",
                            help="Ham bugun, ham ertaga (eng ishonchli)")

    def _resolve_dates(self, options) -> list[str]:
        if options["date"]:
            return [options["date"]]
        today = datetime.date.today()
        if options["today_and_tomorrow"]:
            return [today.isoformat(), (today + datetime.timedelta(days=1)).isoformat()]
        if options["tomorrow"]:
            return [(today + datetime.timedelta(days=1)).isoformat()]
        return [today.isoformat()]

    def handle(self, *args, **options):
        dates = self._resolve_dates(options)

        if options["org_id"]:
            orgs = list(ExternalOrganization.objects.filter(organization_id=options["org_id"]))
        else:
            orgs = list(ExternalOrganization.objects.all().order_by("organization_id"))

        if not orgs:
            self.stderr.write("Tashkilot topilmadi.")
            return

        svc = SkudSyncService()
        total = 0
        for target_date in dates:
            self.stdout.write(f"\n=== Sana: {target_date} ===")
            for org in orgs:
                try:
                    r = svc.sync_schedule(org.organization_id, target_date=target_date)
                    n = r.get("synced_schedule_items", 0)
                    total += n
                    self.stdout.write(
                        f"  OK   [{org.organization_id}] {org.organization_name}: {n} dars"
                    )
                except Exception as e:
                    self.stderr.write(
                        f"  FAIL [{org.organization_id}] {org.organization_name}: {e}"
                    )

        self.stdout.write(self.style.SUCCESS(f"\nJami {total} ta dars yozuvi sync qilindi."))
