"""
SKUD API dagi tashkilotlar bilan local PostgreSQL ma'lumotlarini solishtiradi.

Ishlatish:
    python manage.py check_api_vs_local
    python manage.py check_api_vs_local --skip-students   # talabalar sonini API dan so'ramaydi (tez)
    python manage.py check_api_vs_local --org-id 123      # faqat bitta org
"""

from django.core.management.base import BaseCommand
from django.db.models import Count, Max, Q

from apps.face_data.models import EnrollmentPhoto, StudentEmbedding
from apps.integrations.models import (
    ExternalClass,
    ExternalOrganization,
    ExternalSchedule,
    ExternalStudent,
    ExternalStudentPhoto,
)
from apps.integrations.services import SkudClient


class Command(BaseCommand):
    help = "SKUD API vs local DB solishtirish"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-students",
            action="store_true",
            default=False,
            help="API dan talabalar sonini so'ramaydi (tezroq ishlaydi)",
        )
        parser.add_argument(
            "--org-id",
            type=int,
            default=None,
            help="Faqat bitta tashkilot ID ni tekshirish",
        )

    def handle(self, *args, **options):
        skip_students = options["skip_students"]
        filter_org_id = options["org_id"]

        client = SkudClient()

        self.stdout.write("SKUD API dan tashkilotlar ro'yxati olinmoqda...")
        try:
            api_orgs = client.get_organizations()
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"API xatosi: {exc}"))
            return

        if filter_org_id:
            api_orgs = [o for o in api_orgs if o.get("organizationId") == filter_org_id]

        self.stdout.write(
            self.style.SUCCESS(f"API da jami {len(api_orgs)} ta tashkilot topildi.\n")
        )

        # Local DB dan bir martalik statistika
        local_orgs_map = {
            o.organization_id: o
            for o in ExternalOrganization.objects.all()
        }

        # Org bo'yicha guruhlab olish (bitta query)
        class_counts = dict(
            ExternalClass.objects.values("organization__organization_id")
            .annotate(n=Count("id"))
            .values_list("organization__organization_id", "n")
        )
        student_counts = dict(
            ExternalStudent.objects.values("organization__organization_id")
            .annotate(n=Count("id"))
            .values_list("organization__organization_id", "n")
        )
        photo_total = dict(
            ExternalStudentPhoto.objects.values("student__organization__organization_id")
            .annotate(n=Count("id"))
            .values_list("student__organization__organization_id", "n")
        )
        photo_downloaded = dict(
            ExternalStudentPhoto.objects.filter(
                ~Q(image="") & Q(image__isnull=False)
            )
            .values("student__organization__organization_id")
            .annotate(n=Count("id"))
            .values_list("student__organization__organization_id", "n")
        )
        enrollment_counts = dict(
            EnrollmentPhoto.objects.values("student__organization__organization_id")
            .annotate(n=Count("id"))
            .values_list("student__organization__organization_id", "n")
        )
        embedding_counts = dict(
            StudentEmbedding.objects.filter(is_active=True)
            .values("enrollment_photo__student__organization__organization_id")
            .annotate(n=Count("id"))
            .values_list("enrollment_photo__student__organization__organization_id", "n")
        )
        schedule_last = dict(
            ExternalSchedule.objects.values("organization__organization_id")
            .annotate(last=Max("date"), n=Count("id"))
            .values_list("organization__organization_id", "last")
        )
        schedule_counts = dict(
            ExternalSchedule.objects.values("organization__organization_id")
            .annotate(n=Count("id"))
            .values_list("organization__organization_id", "n")
        )

        # ── Jadval sarlavhasi ─────────────────────────────────────────────
        col_w = 30
        self.stdout.write("=" * 110)
        self.stdout.write(
            f"{'Tashkilot':^{col_w}} | {'API':<8} | {'Local DB taqqoslash':^60}"
        )
        self.stdout.write("-" * 110)
        self.stdout.write(
            f"{'Nomi':<{col_w}} | {'Sinflar':>7} | "
            f"{'Sinf':>5}  {'Talaba':>7}  {'Foto':>8}  "
            f"{'Yuklangan':>10}  {'Emb':>6}  {'Jadval':>8}  {'Oxirgi sana':<12}  {'Holat'}"
        )
        self.stdout.write("=" * 110)

        not_in_local = []
        summary_rows = []

        for org_data in api_orgs:
            org_id   = org_data.get("organizationId")
            org_name = org_data.get("organizationName", "?")[:col_w]

            # API dan sinflar soni
            try:
                api_classes = client.get_classes(org_id)
                api_class_n = len(api_classes)
            except Exception as exc:
                api_class_n = f"ERR({exc.__class__.__name__})"

            # API dan talabalar (ixtiyoriy)
            if skip_students:
                api_student_n = "—"
            else:
                try:
                    api_students = client.get_students(org_id)
                    api_student_n = len(api_students)
                except Exception as exc:
                    api_student_n = f"ERR"

            # Local DB
            is_local     = org_id in local_orgs_map
            loc_classes  = class_counts.get(org_id, 0)
            loc_students = student_counts.get(org_id, 0)
            loc_photos   = photo_total.get(org_id, 0)
            loc_dl       = photo_downloaded.get(org_id, 0)
            loc_emb      = embedding_counts.get(org_id, 0)
            loc_sched    = schedule_counts.get(org_id, 0)
            last_date    = schedule_last.get(org_id, None)
            last_date_s  = str(last_date) if last_date else "—"

            if not is_local:
                not_in_local.append(f"  [{org_id}] {org_name}")
                status = self.style.ERROR("SINXRON EMAS")
            elif loc_students == 0:
                status = self.style.WARNING("Talaba yo'q")
            elif loc_emb == 0:
                status = self.style.WARNING("Embedding yo'q")
            elif loc_dl < loc_photos:
                status = self.style.WARNING("Foto to'liq emas")
            else:
                status = self.style.SUCCESS("OK")

            # Sinflar taqqoslash
            if isinstance(api_class_n, int) and is_local:
                class_diff = f"{loc_classes}/{api_class_n}"
            else:
                class_diff = f"{loc_classes}/?"

            row = (
                f"{org_name:<{col_w}} | {str(api_class_n):>7} | "
                f"{class_diff:>5}  {loc_students:>7}  {loc_photos:>8}  "
                f"{loc_dl:>10}  {loc_emb:>6}  {loc_sched:>8}  {last_date_s:<12}  {status}"
            )
            self.stdout.write(row)
            summary_rows.append({
                "org_id": org_id,
                "name": org_name,
                "api_class_n": api_class_n,
                "api_student_n": api_student_n,
                "loc_students": loc_students,
                "loc_emb": loc_emb,
                "is_local": is_local,
            })

        self.stdout.write("=" * 110)

        # ── Xulosa ───────────────────────────────────────────────────────
        total_api  = len(api_orgs)
        total_loc  = len([r for r in summary_rows if r["is_local"]])
        total_emb  = sum(r["loc_emb"] for r in summary_rows)
        total_std  = sum(r["loc_students"] for r in summary_rows)

        self.stdout.write(f"\n{'─'*50}")
        self.stdout.write(f"  API da tashkilotlar soni    : {total_api}")
        self.stdout.write(f"  Local DB da bor             : {total_loc}")
        self.stdout.write(f"  Local DB da YO'Q            : {total_api - total_loc}")
        self.stdout.write(f"  Jami talabalar (local)      : {total_std}")
        self.stdout.write(f"  Jami aktiv embedding        : {total_emb}")

        if not_in_local:
            self.stdout.write(self.style.ERROR("\nLocal DB da topilmagan tashkilotlar:"))
            for line in not_in_local:
                self.stdout.write(self.style.ERROR(line))

        if not skip_students:
            self.stdout.write(
                f"\n{'─'*50}\n"
                "  Ustun izoh:\n"
                "    Sinflar  → API sinflar soni\n"
                "    Sinf     → Local/API (local/API nisbati)\n"
                "    Talaba   → Local DB da talabalar soni\n"
                "    Foto     → ExternalStudentPhoto yozuvlari\n"
                "    Yuklangan→ Haqiqiy fayl yuklangan fotolar\n"
                "    Emb      → Aktiv StudentEmbedding soni\n"
                "    Jadval   → ExternalSchedule yozuvlari\n"
                "    Oxirgi   → Oxirgi jadval sanasi\n"
            )
        else:
            self.stdout.write(
                "\n  (Talabalar soni API dan so'ralmadi. "
                "--skip-students bayrog'i o'chirilgan edi.)"
            )
