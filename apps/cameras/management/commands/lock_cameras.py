"""
Barcha aktiv PTZ kameralarni davomat pozitsiyasiga qulflaydi.

Ishlatish:
    python manage.py lock_cameras
    python manage.py lock_cameras --camera-id 5
    python manage.py lock_cameras --list-presets --camera-id 5
    python manage.py lock_cameras --save-preset --camera-id 5 --preset-name "Dars"
    python manage.py lock_cameras --get-rtsp --camera-id 5
"""

from django.core.management.base import BaseCommand
from apps.cameras.models import Camera
from apps.cameras.ptz_service import PtzService
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "PTZ kameralarni davomat pozitsiyasiga qulflaydi"

    def add_arguments(self, parser):
        parser.add_argument("--camera-id", type=int, default=None,
                            help="Faqat shu kamera ID (yo'q bo'lsa hammasi)")
        parser.add_argument("--list-presets", action="store_true",
                            help="Kameradagi barcha presetlarni ko'rsatadi")
        parser.add_argument("--save-preset", action="store_true",
                            help="Joriy pozitsiyani preset sifatida saqlaydi")
        parser.add_argument("--preset-token", type=str, default=None,
                            help="Preset token (saqlash yoki o'tish uchun)")
        parser.add_argument("--preset-name", type=str, default="Davomat",
                            help="Preset nomi (default: Davomat)")
        parser.add_argument("--get-rtsp", action="store_true",
                            help="ONVIF orqali RTSP URL larini ko'rsatadi")
        parser.add_argument("--get-status", action="store_true",
                            help="Joriy PTZ pozitsiyasini ko'rsatadi")

    def handle(self, *args, **options):
        cam_id = options["camera_id"]
        qs = Camera.objects.filter(is_active_stream=True)
        if cam_id:
            qs = qs.filter(id=cam_id)

        cameras = list(qs)
        if not cameras:
            self.stderr.write("Aktiv kamera topilmadi.")
            return

        for cam in cameras:
            self.stdout.write(f"\n[cam={cam.id}] {cam.name}  ip={cam.ip_address}")
            svc = PtzService(cam)

            try:
                if options["list_presets"]:
                    self._list_presets(svc, cam)

                elif options["save_preset"]:
                    self._save_preset(svc, cam, options)

                elif options["get_rtsp"]:
                    url = svc.get_rtsp_url()
                    self.stdout.write(f"  RTSP: {url}")

                elif options["get_status"]:
                    status = svc.get_status()
                    self.stdout.write(
                        f"  pan={status['pan']:.3f}  tilt={status['tilt']:.3f}  "
                        f"zoom={status['zoom']:.3f}  moving={status['moving']}"
                    )

                else:
                    self._lock_camera(svc, cam)

            except Exception as e:
                self.stderr.write(f"  [XATO] cam={cam.id}: {e}")

        self.stdout.write("\nTayor.")

    def _list_presets(self, svc: PtzService, cam: Camera):
        presets = svc.list_presets()
        if not presets:
            self.stdout.write("  Preset yo'q.")
        for p in presets:
            marker = " ← joriy" if p["token"] == cam.ptz_preset_token else ""
            self.stdout.write(f"  Preset token={p['token']}  name={p['name']}{marker}")

    def _save_preset(self, svc: PtzService, cam: Camera, options):
        token = options["preset_token"] or ""
        name = options["preset_name"]
        saved_token = svc.save_preset(token, name)
        cam.ptz_preset_token = saved_token
        cam.save(update_fields=["ptz_preset_token"])
        self.stdout.write(f"  Preset saqlandi: token={saved_token}  (DB yangilandi)")

    def _lock_camera(self, svc: PtzService, cam: Camera):
        if not cam.ptz_preset_token:
            self.stdout.write(
                "  ptz_preset_token yo'q — avval --save-preset yoki "
                "--preset-token bilan DB ni yangilang."
            )
            return
        ok = svc.lock_to_attendance_position()
        if ok:
            self.stdout.write(f"  ✓ Qulflandi → preset={cam.ptz_preset_token}")
        else:
            self.stdout.write("  Qulflanmadi (preset token yo'q)")
