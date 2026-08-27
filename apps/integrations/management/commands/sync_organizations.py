"""
SKUD dan tashkilotlar ro'yxatini yuklab oladi.

TOZA BAZADA ENG BIRINCHI ISHGA TUSHIRILADI: `sync_full` va
`sync_all_organizations` ikkalasi ham ExternalOrganization yozuvini talab qiladi,
u bo'lmasa "ExternalOrganization matching query does not exist" bilan yiqiladi.

Ishlatish:
    python manage.py sync_organizations
    python manage.py sync_organizations --check 59
"""
from django.core.management.base import BaseCommand

from apps.integrations.models import ExternalOrganization
from apps.integrations.services import SkudSyncService


class Command(BaseCommand):
    help = "SKUD dan tashkilotlar ro'yxatini sync qiladi (toza bazada birinchi qadam)"

    def add_arguments(self, parser):
        parser.add_argument("--check", type=int, default=None,
                            help="Sync dan keyin shu org_id borligini tekshiradi")
        # v3 (2026-08-27): /organizations endi regionId+districtId talab qiladi.
        # Berilsa faqat shu tuman sinxronlanadi (tez); berilmasa hamma
        # viloyat/tuman aylanib chiqiladi (~200 so'rov, 2-5 daqiqa).
        parser.add_argument("--region-id", type=int, default=None)
        parser.add_argument("--district-id", type=int, default=None)

    def handle(self, *args, **options):
        if options["region_id"] and options["district_id"]:
            self.stdout.write(
                f"SKUD dan tashkilotlar (region={options['region_id']}, "
                f"district={options['district_id']})...")
        else:
            self.stdout.write(
                "SKUD dan BARCHA tashkilotlar (v3: hamma tuman aylanadi, 2-5 daq)...")
        try:
            SkudSyncService().sync_organizations(
                options["region_id"], options["district_id"])
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"FAIL: {e}"))
            return

        total = ExternalOrganization.objects.count()
        self.stdout.write(self.style.SUCCESS(f"Bazada {total} ta tashkilot"))

        org_id = options["check"]
        if org_id is None:
            return

        org = ExternalOrganization.objects.filter(organization_id=org_id).first()
        if org:
            self.stdout.write(self.style.SUCCESS(
                f"  org_id={org_id}: {org.organization_name} (INN {org.organization_inn or '—'})"
            ))
        else:
            self.stderr.write(self.style.ERROR(
                f"  org_id={org_id} SKUD ro'yxatida YO'Q — org_id ni tekshiring"
            ))
