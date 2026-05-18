"""
Barcha o'quvchilar uchun embedding yaratadi (to'liq pipeline).

Ishlatish:
    python manage.py build_all_embeddings
    python manage.py build_all_embeddings --org-id 12345
    python manage.py build_all_embeddings --batch-size 200 --dry-run

Qadamlar:
  1. EnrollmentPhoto yo'q fotolar uchun yaratiladi
  2. InsightFace bilan embedding generatsiya qilinadi
  3. Har bir talaba uchun primary embedding belgilanadi
"""

import time

from django.core.management.base import BaseCommand

from apps.face_data.models import EnrollmentPhoto, StudentEmbedding
from apps.face_data.services import EmbeddingGenerationService
from apps.integrations.models import ExternalOrganization, ExternalStudentPhoto


class Command(BaseCommand):
    help = "Barcha fotolar uchun to'liq embedding pipeline (EnrollmentPhoto + Embedding)"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, default=None)
        parser.add_argument("--batch-size", type=int, default=100,
                            help="Har bir iteratsiyadagi foto soni (default: 100)")
        parser.add_argument("--dry-run", action="store_true",
                            help="Haqiqatan yozmaydi, faqat hisobot")

    def handle(self, *args, **options):
        org_id = options["org_id"]
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]

        t_start = time.time()

        # 1-qadam: EnrollmentPhoto yo'qlarini yaratish
        created_ep = self._ensure_enrollment_photos(org_id, dry_run)
        self.stdout.write(f"[1] EnrollmentPhoto yaratildi: {created_ep} ta")

        if dry_run:
            self._print_dry_run_stats(org_id)
            return

        # 2-qadam: Embedding generatsiya
        svc = EmbeddingGenerationService()
        total_ok, total_fail = self._generate_all(svc, org_id, batch_size)

        # 3-qadam: Primary embedding belgilash
        primary_result = svc.mark_primary_embeddings(organization_id=org_id)
        self.stdout.write(f"[3] Primary embedding: {primary_result}")

        elapsed = time.time() - t_start
        total_emb = StudentEmbedding.objects.filter(is_active=True)
        if org_id:
            total_emb = total_emb.filter(student__organization__organization_id=org_id)

        self.stdout.write(self.style.SUCCESS(
            f"\nTugadi {elapsed:.0f}s ichida. "
            f"OK={total_ok} FAIL={total_fail} "
            f"Jami aktiv embedding: {total_emb.count()}"
        ))

    def _ensure_enrollment_photos(self, org_id, dry_run: bool) -> int:
        qs = ExternalStudentPhoto.objects.filter(
            enrollment_record__isnull=True
        ).exclude(image="").exclude(image=None).select_related("student")

        if org_id:
            qs = qs.filter(student__organization__organization_id=org_id)

        count = qs.count()
        self.stdout.write(f"  EnrollmentPhoto yo'q fotolar: {count} ta")

        if dry_run or count == 0:
            return 0

        from django.utils import timezone
        now = timezone.now()
        chunk_size = 1000
        created = 0

        photos_iter = qs.iterator(chunk_size=chunk_size)
        chunk = []
        for photo in photos_iter:
            chunk.append(EnrollmentPhoto(
                external_photo=photo,
                student=photo.student,
                status=EnrollmentPhoto.STATUS_VALID,
                created_at=now,
                updated_at=now,
            ))
            if len(chunk) >= chunk_size:
                result = EnrollmentPhoto.objects.bulk_create(chunk, ignore_conflicts=True)
                created += len(result)
                self.stdout.write(f"  EnrollmentPhoto yaratildi: {created}/{count}", ending="\r")
                self.stdout.flush()
                chunk = []

        if chunk:
            result = EnrollmentPhoto.objects.bulk_create(chunk, ignore_conflicts=True)
            created += len(result)

        self.stdout.write(f"  EnrollmentPhoto yaratildi: {created} ta          ")
        return created

    def _generate_all(self, svc: EmbeddingGenerationService, org_id, batch_size: int):
        already_embedded_ids = set(
            StudentEmbedding.objects.filter(is_active=True)
            .values_list("enrollment_photo_id", flat=True)
        )

        qs = EnrollmentPhoto.objects.select_related(
            "student", "student__organization", "external_photo"
        ).filter(status=EnrollmentPhoto.STATUS_VALID).exclude(id__in=already_embedded_ids)

        if org_id:
            qs = qs.filter(student__organization__organization_id=org_id)

        total_remaining = qs.count()
        self.stdout.write(f"[2] Embedding yaratilishi kerak: {total_remaining} ta foto")

        if total_remaining == 0:
            return 0, 0

        total_ok = 0
        total_fail = 0
        processed = 0

        while True:
            already_done = set(
                StudentEmbedding.objects.filter(is_active=True)
                .values_list("enrollment_photo_id", flat=True)
            )
            batch_qs = EnrollmentPhoto.objects.select_related(
                "student", "student__organization", "external_photo"
            ).filter(status=EnrollmentPhoto.STATUS_VALID).exclude(id__in=already_done)

            if org_id:
                batch_qs = batch_qs.filter(student__organization__organization_id=org_id)

            batch = list(batch_qs.order_by("id")[:batch_size])
            if not batch:
                break

            ok = fail = 0
            for ep in batch:
                try:
                    svc.process_one(ep)
                    ok += 1
                except Exception:
                    fail += 1

            total_ok += ok
            total_fail += fail
            processed += len(batch)

            pct = processed * 100 // total_remaining if total_remaining else 100
            self.stdout.write(
                f"  [{pct:3d}%] {processed}/{total_remaining} "
                f"ok={total_ok} fail={total_fail}",
                ending="\r",
            )
            self.stdout.flush()

        self.stdout.write("")
        return total_ok, total_fail

    def _print_dry_run_stats(self, org_id):
        qs = EnrollmentPhoto.objects.filter(status=EnrollmentPhoto.STATUS_VALID)
        if org_id:
            qs = qs.filter(student__organization__organization_id=org_id)

        need_emb = qs.exclude(
            id__in=StudentEmbedding.objects.values("enrollment_photo_id")
        ).count()

        from apps.integrations.models import ExternalStudent
        total_st = ExternalStudent.objects.all()
        if org_id:
            total_st = total_st.filter(organization__organization_id=org_id)

        with_emb = StudentEmbedding.objects.filter(is_active=True)
        if org_id:
            with_emb = with_emb.filter(student__organization__organization_id=org_id)
        with_emb = with_emb.values("student").distinct().count()

        self.stdout.write(f"\n--- DRY RUN HISOBOT ---")
        self.stdout.write(f"Jami talabalar: {total_st.count()}")
        self.stdout.write(f"Embeddingga ega: {with_emb}")
        self.stdout.write(f"Embedding yaratilishi kerak: {need_emb} ta foto")
        self.stdout.write("Haqiqiy ishga tushirish: --dry-run flagsiz")
