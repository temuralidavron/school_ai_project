"""
Kameralarni TO'G'RIDAN-TO'G'RI SKUD API'dan o'rnatadi.

SKUD get_classrooms(org) → har xona uchun: classRoomName + deviceId (kamera IP).
stream_url shu IP'dan .env shablon bilan quriladi:

    CAMERA_STREAM_TEMPLATE  — masalan:
      rtsp://{user}:{password}@{ip}:554/Streaming/Channels/101   (Hikvision)
      rtsp://{user}:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=0  (Dahua)
      https://edu-api.devel.uz/cam{org}_{room}                   (edu-api proxy)
    CAMERA_USER, CAMERA_PASSWORD — kamera login/parol

skud_device_id = IP qilib qo'yiladi → sync_full kamerani xonaga AVTOMATIK bog'laydi.

Ishlatish:
    python manage.py setup_cameras_from_skud --org-id 16 --dry-run   # ko'rsatadi
    python manage.py setup_cameras_from_skud --org-id 16 --activate   # yozadi
"""
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.cameras.models import Camera
from apps.integrations.services import SkudClient


class Command(BaseCommand):
    help = "Kameralarni SKUD API deviceId (IP) dan o'rnatadi"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, required=True)
        parser.add_argument("--activate", action="store_true",
                            help="is_active_stream=True qiladi")
        parser.add_argument("--dry-run", action="store_true",
                            help="Yozmaydi, faqat quriladigan URL'larni ko'rsatadi")

    def _build_url(self, ip: str, org_id: int, room_id: int) -> str:
        tmpl = getattr(settings, "CAMERA_STREAM_TEMPLATE", "")
        if not tmpl:
            return ""
        return tmpl.format(
            ip=ip,
            user=getattr(settings, "CAMERA_USER", ""),
            password=getattr(settings, "CAMERA_PASSWORD", ""),
            org=org_id,
            room=room_id,
        )

    def handle(self, *args, **options):
        org_id = options["org_id"]
        tmpl = getattr(settings, "CAMERA_STREAM_TEMPLATE", "")
        if not tmpl:
            self.stderr.write(
                "CAMERA_STREAM_TEMPLATE .env da yo'q. Masalan:\n"
                "  CAMERA_STREAM_TEMPLATE=rtsp://{user}:{password}@{ip}:554/Streaming/Channels/101\n"
                "  CAMERA_USER=admin\n  CAMERA_PASSWORD=xxxxx"
            )
            return

        try:
            items = SkudClient().get_classrooms(org_id)
        except Exception as e:
            self.stderr.write(f"SKUD get_classrooms xato: {e}")
            return

        if not items:
            self.stderr.write(f"SKUD'da org={org_id} uchun xona yo'q")
            return

        items = sorted(items, key=lambda x: x.get("classRoomId", 0))
        created = updated = 0

        for it in items:
            room_id = it.get("classRoomId")
            name = it.get("classRoomName", f"room-{room_id}")
            ip = (it.get("deviceId") or "").strip()
            if not ip:
                self.stdout.write(f"  SKIP {name}: deviceId bo'sh")
                continue

            url = self._build_url(ip, org_id, room_id)
            if options["dry_run"]:
                # Parolni yashirib ko'rsatamiz
                safe = url.replace(getattr(settings, "CAMERA_PASSWORD", "") or "\0", "***") \
                    if getattr(settings, "CAMERA_PASSWORD", "") else url
                self.stdout.write(f"  {name:<10} ip={ip:<14} → {safe}")
                continue

            obj, was_created = Camera.objects.update_or_create(
                skud_device_id=ip,
                defaults={
                    "name": name,
                    "organization_id": org_id,
                    "stream_url": url,
                    "is_active_stream": options["activate"],
                    "ip_address": ip,
                    "username": "",
                    "password": "",
                },
            )
            if was_created:
                created += 1
                self.stdout.write(f"  + {name} id={obj.id} ip={ip}")
            else:
                updated += 1
                self.stdout.write(f"  ~ {name} id={obj.id} ip={ip}")

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING(
                "\nDRY-RUN — hech narsa yozilmadi. URL'lar to'g'ri bo'lsa "
                "--activate bilan qayta ishga tushiring."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nKamera: {created} yangi, {updated} yangilandi (org={org_id}).\n"
                f"Keyin: sync_full --org-id {org_id} (kamera↔xona bog'lanadi) "
                f"→ docker compose restart cameras"
            ))
