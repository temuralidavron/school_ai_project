from django.core.management.base import BaseCommand

from apps.face_data.models import EnrollmentPhoto, StudentEmbedding
from apps.face_data.services import EmbeddingGenerationService


FAILED_STATUSES = [
    EnrollmentPhoto.STATUS_NO_FACE,
    EnrollmentPhoto.STATUS_MULTI_FACE,
    EnrollmentPhoto.STATUS_BLURRY,
    EnrollmentPhoto.STATUS_TOO_SMALL,
    EnrollmentPhoto.STATUS_FAILED,
]


class Command(BaseCommand):
    help = (
        "Haar cascade bilan rad etilgan fotoları InsightFace bilan qayta ishlab "
        "embedding yaratishga urinadi."
    )

    def add_arguments(self, parser):
        parser.add_argument("--organization-id", type=int, default=None)
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--status", type=str, default=None,
                            help="Faqat bitta status: no_face, multi_face, blurry, too_small, failed")

    def handle(self, *args, **options):
        org_id = options["organization_id"]
        limit = options["limit"]

        statuses = [options["status"]] if options["status"] else FAILED_STATUSES

        qs = EnrollmentPhoto.objects.select_related(
            "student", "student__organization", "external_photo"
        ).filter(status__in=statuses)

        if org_id:
            qs = qs.filter(student__organization__organization_id=org_id)

        # Embedding allaqachon bor bo'lganlarni o'tkazib yuborish
        already_embedded = set(
            StudentEmbedding.objects.filter(is_active=True)
            .values_list("enrollment_photo_id", flat=True)
        )
        qs = qs.exclude(id__in=already_embedded).order_by("id")[:limit]

        records = list(qs)
        total = len(records)

        self.stdout.write(f"Qayta ishlash uchun: {total} ta foto "
                         f"(status: {', '.join(statuses)})")

        service = EmbeddingGenerationService()
        success = 0
        failed = 0

        for record in records:
            # Status ni vaqtincha valid ga o'zgartirish (process_one shartini o'tish)
            original_status = record.status
            record.status = EnrollmentPhoto.STATUS_VALID
            record.save(update_fields=["status"])

            try:
                emb = service.process_one(record)
                success += 1
                self.stdout.write(
                    f"  OK  {record.student.pinfl} "
                    f"({record.external_photo.photo_type}) "
                    f"[asl status: {original_status}]"
                )
            except Exception as e:
                failed += 1
                # Muvaffaqiyatsiz bo'lsa asl statusga qaytarish
                record.status = original_status
                record.save(update_fields=["status", "failure_reason"])
                self.stdout.write(
                    f"  FAIL {record.student.pinfl} "
                    f"({record.external_photo.photo_type}): {str(e)[:60]}"
                )

        self.stdout.write(self.style.SUCCESS(
            f"\nNatija: {success} ta embedding yaratildi, {failed} ta muvaqqiyatsiz"
        ))
        self.stdout.write(f"Jami DB dagi embedding: "
                         f"{StudentEmbedding.objects.filter(is_active=True).count()}")
