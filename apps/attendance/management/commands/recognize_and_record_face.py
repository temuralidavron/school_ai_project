from django.core.management.base import BaseCommand

from apps.attendance.services import RecognitionEventService


class Command(BaseCommand):
    help = "Rasmni recognize qiladi va recognition event yozadi"

    def add_arguments(self, parser):
        parser.add_argument("--image", type=str, required=True)
        parser.add_argument("--organization-id", type=int, required=True)
        parser.add_argument("--camera-id", type=int, default=None)
        parser.add_argument("--accept-threshold", type=float, default=0.70)
        parser.add_argument("--review-threshold", type=float, default=0.55)

    def handle(self, *args, **options):
        service = RecognitionEventService()

        result = service.recognize_and_record(
            image_path=options["image"],
            organization_id=options["organization_id"],
            camera_id=options["camera_id"],
            accept_threshold=options["accept_threshold"],
            review_threshold=options["review_threshold"],
        )

        self.stdout.write(self.style.SUCCESS("Recognition record tugadi"))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")