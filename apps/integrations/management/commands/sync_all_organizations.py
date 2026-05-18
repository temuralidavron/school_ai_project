from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.face_data.models import EnrollmentPhoto, StudentEmbedding
from apps.face_data.services import EmbeddingGenerationService
from apps.integrations.models import ExternalOrganization, ExternalStudent, ExternalStudentPhoto
from apps.integrations.services import SkudSyncService


class Command(BaseCommand):
    help = (
        "SKUD dan barcha tashkilotlar talabalarini yuklab, "
        "fotoları saqlaydi va embedding yaratadi."
    )

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, default=None,
                            help="Faqat bitta tashkilot ID")
        parser.add_argument("--skip-synced", action="store_true", default=False,
                            help="Allaqachon talabalari bor tashkilotlarni o'tkazib yuborish")
        parser.add_argument("--step", choices=["students", "photos", "embeddings", "all"],
                            default="all",
                            help="Faqat bitta qadam: students / photos / embeddings / all")
        parser.add_argument("--embed-limit", type=int, default=1000,
                            help="Har bir tashkilot uchun maksimal embedding")

    def handle(self, *args, **options):
        org_id = options["org_id"]
        skip_synced = options["skip_synced"]
        step = options["step"]
        embed_limit = options["embed_limit"]

        if org_id:
            orgs = list(ExternalOrganization.objects.filter(organization_id=org_id))
        else:
            orgs = list(ExternalOrganization.objects.all().order_by("organization_id"))

        self.stdout.write(f"Jami {len(orgs)} ta tashkilot")

        svc = SkudSyncService()

        # ---- 1-QADAM: Talabalarni saqlash ----
        if step in ("students", "all"):
            self.stdout.write("\n=== QADAM 1: Talabalarni SKUD dan olish ===")
            for org in orgs:
                student_count = ExternalStudent.objects.filter(organization=org).count()
                if skip_synced and student_count > 0:
                    self.stdout.write(f"  Skip [{org.organization_id}] {org.organization_name} ({student_count} talaba bor)")
                    continue

                try:
                    result = svc.sync_students(org.organization_id, download_photos=False)
                    self.stdout.write(
                        f"  OK   [{org.organization_id}] {org.organization_name}: "
                        f"{result['synced_students']} talaba"
                    )
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f"  FAIL [{org.organization_id}] {org.organization_name}: {e}"
                    ))

        # ---- 2-QADAM: Fotolarni yuklab olish ----
        if step in ("photos", "all"):
            self.stdout.write("\n=== QADAM 2: Fotolarni yuklab olish ===")
            for org in orgs:
                no_image = ExternalStudentPhoto.objects.filter(
                    student__organization=org
                ).filter(Q(image__isnull=True) | Q(image="")).count()

                if no_image == 0:
                    self.stdout.write(f"  Skip [{org.organization_id}] {org.organization_name} (barcha fotolar bor)")
                    continue

                try:
                    downloaded, failed = svc._download_photos_for_org(org.organization_id)
                    self.stdout.write(
                        f"  OK   [{org.organization_id}] {org.organization_name}: "
                        f"{downloaded} foto yuklandi, {len(failed)} xato"
                    )
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f"  FAIL [{org.organization_id}] {org.organization_name}: {e}"
                    ))

        # ---- 3-QADAM: Embedding yaratish ----
        if step in ("embeddings", "all"):
            self.stdout.write("\n=== QADAM 3: Embedding yaratish ===")
            emb_svc = EmbeddingGenerationService()

            for org in orgs:
                created_ep = self._ensure_enrollment_photos(org)
                if created_ep > 0:
                    self.stdout.write(f"  [{org.organization_id}] {org.organization_name}: {created_ep} yangi EnrollmentPhoto")

                ok, fail = self._generate_embeddings(org, emb_svc, embed_limit)
                if ok > 0 or fail > 0:
                    self.stdout.write(
                        f"  OK   [{org.organization_id}] {org.organization_name}: "
                        f"{ok} embedding yaratildi, {fail} muvaqqiyatsiz"
                    )

        total_emb = StudentEmbedding.objects.filter(is_active=True).count()
        self.stdout.write(self.style.SUCCESS(
            f"\nBajarildi. Jami aktiv embedding: {total_emb}"
        ))

    def _ensure_enrollment_photos(self, org) -> int:
        photos = ExternalStudentPhoto.objects.filter(
            student__organization=org
        ).select_related("student").exclude(image="").exclude(image=None)

        created = 0
        for photo in photos:
            _, was_created = EnrollmentPhoto.objects.get_or_create(
                external_photo=photo,
                defaults={
                    "student": photo.student,
                    "status": EnrollmentPhoto.STATUS_VALID,
                },
            )
            if was_created:
                created += 1
        return created

    def _generate_embeddings(self, org, svc: EmbeddingGenerationService, limit: int) -> tuple[int, int]:
        already_embedded = set(
            StudentEmbedding.objects.filter(is_active=True)
            .values_list("enrollment_photo_id", flat=True)
        )

        qs = list(
            EnrollmentPhoto.objects
            .select_related("student", "external_photo")
            .filter(student__organization=org, status=EnrollmentPhoto.STATUS_VALID)
            .exclude(id__in=already_embedded)
            .order_by("id")[:limit]
        )

        ok = fail = 0
        for ep in qs:
            try:
                svc.process_one(ep)
                ok += 1
            except Exception:
                fail += 1
        return ok, fail
