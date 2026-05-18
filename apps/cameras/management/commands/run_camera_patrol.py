"""
Kamera patrul (aylanish) threadlarini ishga tushiradi.

Stream bilan PARALLEL ishlaydi — alohida konteyner/process.
Rejim: Camera.patrol_mode yoki .env PATROL_MODE.

Ishlatish:
    python manage.py run_camera_patrol --all
    python manage.py run_camera_patrol --camera-id 5
    python manage.py run_camera_patrol --all --dry-run   # faqat rejimni ko'rsatadi
"""
import signal
import threading

from django.core.management.base import BaseCommand

from apps.cameras.models import Camera
from apps.cameras.patrol_service import PatrolService, get_patrol_strategy, resolve_patrol_mode


class Command(BaseCommand):
    help = "Kamera patrul threadlarini ishga tushiradi (stream bilan parallel)"

    def add_arguments(self, parser):
        parser.add_argument("--camera-id", type=int, default=None)
        parser.add_argument("--all", action="store_true", help="Barcha aktiv kameralar")
        parser.add_argument("--dry-run", action="store_true",
                            help="Ishga tushirmaydi, faqat har kamera rejimini ko'rsatadi")

    def handle(self, *args, **options):
        if options["all"]:
            cameras = list(Camera.objects.filter(is_active_stream=True))
        elif options["camera_id"]:
            cameras = list(Camera.objects.filter(id=options["camera_id"]))
        else:
            self.stderr.write("--camera-id <N> yoki --all kerak")
            return

        if not cameras:
            self.stderr.write("Aktiv kamera topilmadi")
            return

        # Dry-run: faqat rejimlarni ko'rsatish
        if options["dry_run"]:
            for cam in cameras:
                mode = resolve_patrol_mode(cam)
                strat = get_patrol_strategy(cam)
                n = len(strat.positions()) if strat else 0
                self.stdout.write(
                    f"  cam={cam.id} {cam.name}: rejim={mode} "
                    f"{'→ ' + str(n) + ' nuqta' if strat else '→ AYLANMAYDI'}"
                )
            return

        stop_event = threading.Event()

        def on_stop(sig, frame):
            self.stdout.write("\nPatrul to'xtatilmoqda...")
            stop_event.set()

        signal.signal(signal.SIGINT, on_stop)
        signal.signal(signal.SIGTERM, on_stop)

        threads = []
        for cam in cameras:
            strat = get_patrol_strategy(cam)
            if strat is None:
                self.stdout.write(f"  cam={cam.id} {cam.name}: patrul o'chiq — o'tkazildi")
                continue
            svc = PatrolService(cam)
            t = threading.Thread(
                target=svc.run,
                args=(stop_event,),
                daemon=True,
                name=f"patrol-{cam.id}",
            )
            t.start()
            threads.append(t)
            self.stdout.write(f"  Patrul: cam={cam.id} {cam.name} → rejim={strat.name}")

        if not threads:
            self.stderr.write("Hech qaysi kamerada patrul yoqilmagan")
            return

        self.stdout.write(self.style.SUCCESS(
            f"{len(threads)} ta kamera patrulda. To'xtatish: Ctrl+C"
        ))
        stop_event.wait()
        for t in threads:
            t.join(timeout=10)
        self.stdout.write(self.style.SUCCESS("Barcha patrullar to'xtatildi"))
