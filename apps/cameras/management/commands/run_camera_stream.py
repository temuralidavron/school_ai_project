import signal
import threading

from django.core.management.base import BaseCommand

from apps.cameras.models import Camera
from apps.cameras.services import CameraStreamService


class Command(BaseCommand):
    help = "Kamera HTTP/MJPEG stream dan yuz tanib davomat yozadi"

    def add_arguments(self, parser):
        parser.add_argument("--camera-id", type=int, default=None, help="Bitta kamera ID")
        parser.add_argument("--all", action="store_true", help="Barcha aktiv kameralar")
        parser.add_argument("--frame-interval", type=float, default=2.0, help="Frame orasidagi vaqt (soniya)")
        parser.add_argument("--accept-threshold", type=float, default=0.55)
        parser.add_argument("--review-threshold", type=float, default=0.42)

    def handle(self, *args, **options):
        if options["all"]:
            cameras = list(Camera.objects.filter(is_active_stream=True, stream_url__isnull=False).exclude(stream_url=""))
        elif options["camera_id"]:
            cameras = list(Camera.objects.filter(id=options["camera_id"], stream_url__isnull=False))
        else:
            self.stderr.write("--camera-id <N> yoki --all berish kerak")
            return

        if not cameras:
            self.stderr.write("Aktiv kamera topilmadi (stream_url bo'sh yoki is_active_stream=False)")
            return

        stop_event = threading.Event()

        def on_stop(sig, frame):
            self.stdout.write("\nTo'xtatilmoqda...")
            stop_event.set()

        signal.signal(signal.SIGINT, on_stop)
        signal.signal(signal.SIGTERM, on_stop)

        threads = []
        for cam in cameras:
            service = CameraStreamService(
                camera=cam,
                frame_interval=options["frame_interval"],
                accept_threshold=options["accept_threshold"],
                review_threshold=options["review_threshold"],
            )
            t = threading.Thread(
                target=service.run,
                args=(stop_event,),
                daemon=True,
                name=f"cam-{cam.id}",
            )
            t.start()
            threads.append(t)
            self.stdout.write(f"  Boshlandi: cam={cam.id} {cam.name} → {cam.stream_url}")

        self.stdout.write(self.style.SUCCESS(f"{len(threads)} ta kamera ishga tushdi. To'xtatish: Ctrl+C"))

        stop_event.wait()
        for t in threads:
            t.join(timeout=10)

        self.stdout.write(self.style.SUCCESS("Barcha kameralar to'xtatildi"))
