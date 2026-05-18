from django.core.management.base import BaseCommand

from apps.face_data.services import EnrollmentAuditService


class Command(BaseCommand):
    help = "Enrollment audit: EnrollmentPhoto yozuvlarini yaratadi va statistika chiqaradi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization-id",
            type=int,
            dest="organization_id",
            default=None,
            help="Faqat bitta organization uchun audit qilish",
        )

    def handle(self, *args, **options):
        organization_id = options["organization_id"]

        service = EnrollmentAuditService()

        created = service.ensure_enrollment_rows(organization_id=organization_id)
        summary = service.build_summary(organization_id=organization_id)

        self.stdout.write(self.style.SUCCESS("Enrollment audit tugadi."))
        self.stdout.write(f"Created enrollment rows: {created}")
        self.stdout.write("------ SUMMARY ------")

        for key, value in summary.items():
            self.stdout.write(f"{key}: {value}")