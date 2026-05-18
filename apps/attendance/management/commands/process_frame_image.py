from django.core.management.base import BaseCommand
from apps.attendance.services import LiveFrameProcessorService


class Command(BaseCommand):
    help = "Bitta frame/image ichidagi yuzlarni detect qilib recognition flow dan o'tkazadi"

    def add_arguments(self, parser):
        parser.add_argument("--image", type=str, required=True)
        parser.add_argument("--organization-id", type=int, required=True)
        parser.add_argument("--camera-id", type=int, default=None)
        parser.add_argument("--accept-threshold", type=float, default=0.70)
        parser.add_argument("--review-threshold", type=float, default=0.55)

    def handle(self, *args, **options):
        service = LiveFrameProcessorService()

        result = service.process_frame_image(
            image_path=options["image"],
            organization_id=options["organization_id"],
            camera_id=options["camera_id"],
            accept_threshold=options["accept_threshold"],
            review_threshold=options["review_threshold"],
        )

        self.stdout.write(self.style.SUCCESS("Frame processing tugadi"))
        self.stdout.write(f"frame_image: {result['frame_image']}")
        self.stdout.write(f"organization_id: {result['organization_id']}")
        self.stdout.write(f"camera_id: {result['camera_id']}")
        self.stdout.write(f"face_count: {result['face_count']}")
        self.stdout.write("------ RESULTS ------")

        for i, row in enumerate(result["results"], start=1):
            self.stdout.write(f"{i}. {row}")