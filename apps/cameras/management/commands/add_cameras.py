"""
Kameralarni CSV fayldan bazaga qo'shadi (istalgan tashkilot uchun).

setup_cameras (org 32 hardcoded) ga TEGMAYDI — bu generic, qo'shimcha.

CSV format (sarlavhasiz, ; yoki , bilan):
    name;stream_url;skud_device_id
Misol (skud_device_id ixtiyoriy):
    24-xona;https://edu-api.devel.uz/cam16_24;10.144.1.24
    4-xona;https://edu-api.devel.uz/cam16_4;

Ishlatish:
    python manage.py add_cameras --org-id 16 --csv deploy/cameras_225.csv
    python manage.py add_cameras --org-id 16 --csv deploy/cameras_225.csv --activate
    python manage.py add_cameras --org-id 16 --csv deploy/cameras_225.csv --link-by-room
"""
import csv

from django.core.management.base import BaseCommand

from apps.cameras.models import Camera


class Command(BaseCommand):
    help = "Kameralarni CSV dan qo'shadi (generic, har org uchun)"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, required=True)
        parser.add_argument("--csv", type=str, required=True,
                            help="CSV yo'li: name;stream_url;skud_device_id")
        parser.add_argument("--activate", action="store_true",
                            help="is_active_stream=True qiladi")
        parser.add_argument("--link-by-room", action="store_true",
                            help="stream_url dagi xona raqamini ExternalClassroom "
                                 "class_room_name bilan solishtirib bog'laydi")

    def _parse_rows(self, path: str) -> list[dict]:
        rows = []
        with open(path, encoding="utf-8") as f:
            sample = f.read(1024)
            f.seek(0)
            delim = ";" if sample.count(";") >= sample.count(",") else ","
            for raw in csv.reader(f, delimiter=delim):
                if not raw or not raw[0].strip() or raw[0].strip().startswith("#"):
                    continue
                name = raw[0].strip()
                url = raw[1].strip() if len(raw) > 1 else ""
                dev = raw[2].strip() if len(raw) > 2 else ""
                if not url:
                    continue
                rows.append({"name": name, "stream_url": url, "skud_device_id": dev})
        return rows

    def handle(self, *args, **options):
        rows = self._parse_rows(options["csv"])
        if not rows:
            self.stderr.write("CSV bo'sh yoki noto'g'ri format")
            return

        org_id = options["org_id"]
        created = updated = 0
        cams = []

        for r in rows:
            defaults = {
                "name": r["name"],
                "organization_id": org_id,
                "is_active_stream": options["activate"],
                "ip_address": "",
                "username": "",
                "password": "",
            }
            if r["skud_device_id"]:
                defaults["skud_device_id"] = r["skud_device_id"]

            obj, was_created = Camera.objects.update_or_create(
                stream_url=r["stream_url"],
                defaults=defaults,
            )
            cams.append(obj)
            if was_created:
                created += 1
                self.stdout.write(f"  + {obj.name} id={obj.id}")
            else:
                updated += 1
                self.stdout.write(f"  ~ {obj.name} id={obj.id}")

        self.stdout.write(self.style.SUCCESS(
            f"\nKamera: {created} yangi, {updated} yangilandi (org={org_id})"
        ))

        if options["link_by_room"]:
            self._link_by_room(cams, org_id)

    def _link_by_room(self, cams: list, org_id: int):
        """stream_url oxiridagi xona tokeni ↔ ExternalClassroom.class_room_name."""
        from apps.integrations.models import ExternalClassroom

        self.stdout.write("\nKamera ↔ xona bog'lash (room nomi bo'yicha)...")
        classrooms = list(ExternalClassroom.objects.filter(
            organization__organization_id=org_id
        ))
        linked = 0
        for cam in cams:
            # "24-xona" → "24"
            token = cam.name.split("-")[0].strip().lower()
            match = None
            for cr in classrooms:
                cn = (cr.class_room_name or "").strip().lower()
                if cn == cam.name.strip().lower() or cn.split("-")[0].strip() == token:
                    match = cr
                    break
            if match and match.camera_id != cam.id:
                match.camera = cam
                match.save(update_fields=["camera", "updated_at"])
                linked += 1
                self.stdout.write(f"  {cam.name} → xona '{match.class_room_name}'")
        self.stdout.write(self.style.SUCCESS(
            f"Bog'landi: {linked} ta. (Bog'lanmaganlarni admin'dan qo'lda tekshiring)"
        ))
