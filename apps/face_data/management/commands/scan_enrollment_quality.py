from django.core.management.base import BaseCommand

from apps.face_data.services import EnrollmentQualityService


class Command(BaseCommand):
    help = "Enrollment rasmlarini quality scan qiladi"

    def add_arguments(self, parser):
        parser.add_argument("--organization-id", type=int, default=None)
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        organization_id = options["organization_id"]
        limit = options["limit"]

        service = EnrollmentQualityService()

        batch_result = service.scan_batch(
            organization_id=organization_id,
            limit=limit,
        )
        summary = service.summary(organization_id=organization_id)

        self.stdout.write(self.style.SUCCESS("Quality scan tugadi"))
        self.stdout.write("------ BATCH RESULT ------")
        for key, value in batch_result.items():
            self.stdout.write(f"{key}: {value}")

        self.stdout.write("------ SUMMARY ------")
        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")