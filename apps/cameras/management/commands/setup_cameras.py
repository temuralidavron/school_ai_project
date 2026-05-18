from django.core.management.base import BaseCommand

from apps.cameras.models import Camera

CAMERAS = [
    # organization 32 - xonalar
    {"name": "24-xona",  "stream_url": "https://edu-api.devel.uz/cam32_24", "organization_id": 32},
    {"name": "4-xona",   "stream_url": "https://edu-api.devel.uz/cam32_4",  "organization_id": 32},
    {"name": "17-xona",  "stream_url": "https://edu-api.devel.uz/cam32_17", "organization_id": 32},
    {"name": "16-xona",  "stream_url": "https://edu-api.devel.uz/cam32_16", "organization_id": 32},
    {"name": "23B-xona", "stream_url": "https://edu-api.devel.uz/cam32_23", "organization_id": 32},
    {"name": "20-xona",  "stream_url": "https://edu-api.devel.uz/cam32_20", "organization_id": 32},
    {"name": "13-xona",  "stream_url": "https://edu-api.devel.uz/cam32_13", "organization_id": 32},
    {"name": "18-xona",  "stream_url": "https://edu-api.devel.uz/cam32_18", "organization_id": 32},
    {"name": "7-xona",   "stream_url": "https://edu-api.devel.uz/cam32_7",  "organization_id": 32},
    {"name": "42-xona",  "stream_url": "https://edu-api.devel.uz/cam32_42", "organization_id": 32},
    {"name": "6-xona",   "stream_url": "https://edu-api.devel.uz/cam32_6",  "organization_id": 32},
    {"name": "30-xona",  "stream_url": "https://edu-api.devel.uz/cam32_30", "organization_id": 32},
    {"name": "14-xona",  "stream_url": "https://edu-api.devel.uz/cam32_14", "organization_id": 32},
    {"name": "41-xona",  "stream_url": "https://edu-api.devel.uz/cam32_41", "organization_id": 32},
    {"name": "26B-xona", "stream_url": "https://edu-api.devel.uz/cam32_26", "organization_id": 32},
    {"name": "9-xona",   "stream_url": "https://edu-api.devel.uz/cam32_9",  "organization_id": 32},
    {"name": "25B-xona", "stream_url": "https://edu-api.devel.uz/cam32_25", "organization_id": 32},
    {"name": "15-xona",  "stream_url": "https://edu-api.devel.uz/cam32_15", "organization_id": 32},
]


class Command(BaseCommand):
    help = "Kamera stream URL larini bazaga yozadi"

    def add_arguments(self, parser):
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Barcha kameralarda is_active_stream=True qiladi",
        )

    def handle(self, *args, **options):
        created = 0
        updated = 0

        for cam_data in CAMERAS:
            obj, was_created = Camera.objects.update_or_create(
                stream_url=cam_data["stream_url"],
                defaults={
                    "name": cam_data["name"],
                    "organization_id": cam_data["organization_id"],
                    "is_active_stream": options["activate"],
                    "ip_address": "",
                    "username": "",
                    "password": "",
                },
            )
            if was_created:
                created += 1
                self.stdout.write(f"  Yaratildi: {obj.name} id={obj.id}")
            else:
                updated += 1
                self.stdout.write(f"  Yangilandi: {obj.name} id={obj.id}")

        self.stdout.write(self.style.SUCCESS(
            f"Tayyor: {created} ta yaratildi, {updated} ta yangilandi"
        ))
        if not options["activate"]:
            self.stdout.write("Ishga tushirish uchun: --activate yoki admin paneldan is_active_stream=True qiling")
