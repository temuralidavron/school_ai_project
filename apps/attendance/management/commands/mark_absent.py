"""
Tugagan darslar uchun kelmagan o'quvchilarni 'absent' belgilaydi.

Dars end_at vaqti o'tib ketgan bo'lsa, o'sha darsda LessonAttendance
yozuvi bo'lmagan har bir o'quvchi 'absent' sifatida yoziladi.

Ishlatish:
    python manage.py mark_absent              # barcha tashkilot
    python manage.py mark_absent --org-id 16  # faqat 225-maktab
"""
from django.core.management.base import BaseCommand

from apps.attendance.services import ActiveScheduleService


class Command(BaseCommand):
    help = "Tugagan darslarda kelmagan o'quvchilarni 'absent' qiladi"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, default=None,
                            help="Faqat bitta tashkilot (yo'q bo'lsa hammasi)")

    def handle(self, *args, **options):
        svc = ActiveScheduleService()
        result = svc.mark_absent_for_finished_lessons(
            organization_id=options["org_id"]
        )
        marked = result.get("absent_marked", 0)
        self.stdout.write(self.style.SUCCESS(
            f"'absent' belgilandi: {marked} ta o'quvchi"
        ))
