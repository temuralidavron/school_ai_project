from django.core.management.base import BaseCommand
from collections import defaultdict

from apps.face_data.models import EnrollmentPhoto, StudentEmbedding
from apps.face_data.services import RecognitionSearchService


class Command(BaseCommand):
    help = "Embedded rasmlar bo'yicha offline recognition accuracy ni tekshiradi (self-matchsiz)"

    def add_arguments(self, parser):
        parser.add_argument("--organization-id", type=int, required=True)
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--top-k", type=int, default=5)
        parser.add_argument(
            "--exclude-student",
            action="store_true",
            help="Agar berilsa, query studentning barcha embeddinglari searchdan chiqariladi",
        )

    def handle(self, *args, **options):
        organization_id = options["organization_id"]
        limit = options["limit"]
        top_k = options["top_k"]
        exclude_student = options["exclude_student"]

        qs = (
            EnrollmentPhoto.objects
            .select_related("student", "external_photo")
            .filter(
                student__organization__organization_id=organization_id,
                status=EnrollmentPhoto.STATUS_EMBEDDED,
            )
            .order_by("id")[:limit]
        )

        records = list(qs)
        if not records:
            self.stdout.write(self.style.WARNING("Test uchun embedded rasm topilmadi"))
            return

        service = RecognitionSearchService()

        total = 0
        top1_correct = 0
        top3_correct = 0
        errors = 0

        photo_type_stats = defaultdict(lambda: {"total": 0, "top1": 0, "top3": 0})

        self.stdout.write("------ RESULTS ------")

        for rec in records:
            total += 1
            photo_type = rec.external_photo.photo_type
            photo_type_stats[photo_type]["total"] += 1

            try:
                exclude_ids = list(
                    StudentEmbedding.objects.filter(enrollment_photo=rec).values_list("id", flat=True)
                )

                result = service.search(
                    image_path=rec.external_photo.image.path,
                    organization_id=organization_id,
                    top_k=top_k,
                    exclude_embedding_ids=exclude_ids,
                    exclude_student_id=rec.student_id if exclude_student else None,
                )
                rows = result["results"]

                expected_pinfl = rec.student.pinfl
                predicted_top1 = rows[0]["pinfl"] if rows else None
                top3_pinfls = [r["pinfl"] for r in rows[:3]]

                is_top1 = predicted_top1 == expected_pinfl
                is_top3 = expected_pinfl in top3_pinfls

                if is_top1:
                    top1_correct += 1
                    photo_type_stats[photo_type]["top1"] += 1

                if is_top3:
                    top3_correct += 1
                    photo_type_stats[photo_type]["top3"] += 1

                self.stdout.write(
                    f"PINFL={expected_pinfl} | type={photo_type} | "
                    f"top1={predicted_top1} | "
                    f"top1_ok={is_top1} | top3_ok={is_top3} | "
                    f"score={(rows[0]['best_score'] if rows else 'N/A')}"
                )

            except Exception as e:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"PINFL={rec.student.pinfl} | type={photo_type} | ERROR={e}"
                    )
                )

        self.stdout.write("\n------ SUMMARY ------")
        self.stdout.write(f"organization_id: {organization_id}")
        self.stdout.write(f"tested: {total}")
        self.stdout.write(f"errors: {errors}")
        self.stdout.write(f"top1_correct: {top1_correct}")
        self.stdout.write(f"top3_correct: {top3_correct}")
        self.stdout.write(f"top1_accuracy: {round((top1_correct / total) * 100, 2) if total else 0}%")
        self.stdout.write(f"top3_accuracy: {round((top3_correct / total) * 100, 2) if total else 0}%")
        self.stdout.write(f"exclude_student_mode: {exclude_student}")

        self.stdout.write("\n------ PHOTO TYPE STATS ------")
        for photo_type, stats in photo_type_stats.items():
            total_type = stats["total"]
            top1_acc = round((stats["top1"] / total_type) * 100, 2) if total_type else 0
            top3_acc = round((stats["top3"] / total_type) * 100, 2) if total_type else 0

            self.stdout.write(
                f"{photo_type}: total={total_type}, "
                f"top1={stats['top1']} ({top1_acc}%), "
                f"top3={stats['top3']} ({top3_acc}%)"
            )
# from django.core.management.base import BaseCommand
# from collections import defaultdict
#
# from apps.face_data.models import EnrollmentPhoto
# from apps.face_data.services import RecognitionSearchService
#
#
# class Command(BaseCommand):
#     help = "Embedded rasmlar bo'yicha offline recognition accuracy ni tekshiradi"
#
#     def add_arguments(self, parser):
#         parser.add_argument("--organization-id", type=int, required=True)
#         parser.add_argument("--limit", type=int, default=20)
#         parser.add_argument("--top-k", type=int, default=5)
#
#     def handle(self, *args, **options):
#         organization_id = options["organization_id"]
#         limit = options["limit"]
#         top_k = options["top_k"]
#
#         qs = (
#             EnrollmentPhoto.objects
#             .select_related("student", "external_photo")
#             .filter(
#                 student__organization__organization_id=organization_id,
#                 status=EnrollmentPhoto.STATUS_EMBEDDED,
#             )
#             .order_by("id")[:limit]
#         )
#
#         records = list(qs)
#         if not records:
#             self.stdout.write(self.style.WARNING("Test uchun embedded rasm topilmadi"))
#             return
#
#         service = RecognitionSearchService()
#
#         total = 0
#         top1_correct = 0
#         top3_correct = 0
#         errors = 0
#
#         photo_type_stats = defaultdict(lambda: {"total": 0, "top1": 0, "top3": 0})
#
#         self.stdout.write("------ RESULTS ------")
#
#         for rec in records:
#             total += 1
#             photo_type = rec.external_photo.photo_type
#             photo_type_stats[photo_type]["total"] += 1
#
#             try:
#                 result = service.search(
#                     image_path=rec.external_photo.image.path,
#                     organization_id=organization_id,
#                     top_k=top_k,
#                 )
#                 rows = result["results"]
#
#                 expected_pinfl = rec.student.pinfl
#                 predicted_top1 = rows[0]["pinfl"] if rows else None
#                 top3_pinfls = [r["pinfl"] for r in rows[:3]]
#
#                 is_top1 = predicted_top1 == expected_pinfl
#                 is_top3 = expected_pinfl in top3_pinfls
#
#                 if is_top1:
#                     top1_correct += 1
#                     photo_type_stats[photo_type]["top1"] += 1
#
#                 if is_top3:
#                     top3_correct += 1
#                     photo_type_stats[photo_type]["top3"] += 1
#
#                 self.stdout.write(
#                     f"PINFL={expected_pinfl} | type={photo_type} | "
#                     f"top1={predicted_top1} | "
#                     f"top1_ok={is_top1} | top3_ok={is_top3} | "
#                     f"score={(rows[0]['best_score'] if rows else 'N/A')}"
#                 )
#
#             except Exception as e:
#                 errors += 1
#                 self.stdout.write(
#                     self.style.ERROR(
#                         f"PINFL={rec.student.pinfl} | type={photo_type} | ERROR={e}"
#                     )
#                 )
#
#         self.stdout.write("\n------ SUMMARY ------")
#         self.stdout.write(f"organization_id: {organization_id}")
#         self.stdout.write(f"tested: {total}")
#         self.stdout.write(f"errors: {errors}")
#         self.stdout.write(f"top1_correct: {top1_correct}")
#         self.stdout.write(f"top3_correct: {top3_correct}")
#         self.stdout.write(f"top1_accuracy: {round((top1_correct / total) * 100, 2) if total else 0}%")
#         self.stdout.write(f"top3_accuracy: {round((top3_correct / total) * 100, 2) if total else 0}%")
#
#         self.stdout.write("\n------ PHOTO TYPE STATS ------")
#         for photo_type, stats in photo_type_stats.items():
#             total_type = stats["total"]
#             top1_acc = round((stats["top1"] / total_type) * 100, 2) if total_type else 0
#             top3_acc = round((stats["top3"] / total_type) * 100, 2) if total_type else 0
#
#             self.stdout.write(
#                 f"{photo_type}: total={total_type}, "
#                 f"top1={stats['top1']} ({top1_acc}%), "
#                 f"top3={stats['top3']} ({top3_acc}%)"
#             )