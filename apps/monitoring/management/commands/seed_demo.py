"""
Demo (mock) ma'lumot yaratadi — bot'ni LOKAL sinash uchun.

Faqat TEST: 3 sinf, har birida o'quvchilar, bugungi darslar, davomat
(present/late/absent). Real SKUD ma'lumotiga tegmaydi — alohida demo org.

Ishlatish:
    python manage.py seed_demo
    python manage.py seed_demo --clear   # avval demo'ni tozalab, qayta yaratadi
"""
import random
from datetime import time as dtime

from django.core.management.base import BaseCommand
from django.utils import timezone


DEMO_ORG_ID = 16   # bot BOT_ORG_ID bilan mos

CLASSES = [(9, "A", 28), (10, "B", 31), (11, "V", 29)]
LESSONS = [(1, dtime(8, 0), dtime(8, 45)), (2, dtime(8, 50), dtime(9, 35)), (3, dtime(9, 40), dtime(10, 25))]


class Command(BaseCommand):
    help = "Bot test uchun demo davomat ma'lumoti yaratadi"

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true")

    def handle(self, *args, **options):
        from apps.integrations.models import (
            ExternalOrganization, ExternalClass, ExternalClassroom,
            ExternalStudent, ExternalSchedule,
        )
        from apps.attendance.models import LessonAttendance

        today = timezone.now().date()

        org, _ = ExternalOrganization.objects.get_or_create(
            organization_id=DEMO_ORG_ID,
            defaults={"organization_name": "225-maktab (demo)"},
        )

        if options["clear"]:
            ExternalSchedule.objects.filter(organization=org, date=today).delete()
            self.stdout.write("Bugungi demo jadval tozalandi")

        total_att = 0
        for degree, name, count in CLASSES:
            cls, _ = ExternalClass.objects.get_or_create(
                class_id=degree * 100 + ord(name),
                defaults={"class_degree": degree, "class_name": name, "organization": org},
            )
            room, _ = ExternalClassroom.objects.get_or_create(
                class_room_id=degree * 1000 + ord(name),
                defaults={"class_room_name": f"{degree}-{name} xona", "organization": org},
            )
            # O'quvchilar
            students = []
            for i in range(count):
                pinfl = f"DEMO{degree}{name}{i:03d}"
                st, _ = ExternalStudent.objects.get_or_create(
                    pinfl=pinfl,
                    defaults={"full_name": f"{degree}{name} O'quvchi-{i+1}", "organization": org, "class_obj": cls},
                )
                students.append(st)

            # Darslar + davomat
            for lesson_no, start, end in LESSONS:
                sch, _ = ExternalSchedule.objects.get_or_create(
                    organization=org, class_obj=cls, classroom=room,
                    lesson_number=lesson_no, date=today,
                    defaults={"start_at": start, "end_at": end},
                )
                # Demo davomat: ~70-90% keldi, ba'zi kech, qolgani absent
                LessonAttendance.objects.filter(schedule=sch).delete()
                for st in students:
                    r = random.random()
                    if r < 0.70:
                        status = LessonAttendance.STATUS_PRESENT
                    elif r < 0.82:
                        status = LessonAttendance.STATUS_LATE
                    else:
                        status = LessonAttendance.STATUS_ABSENT
                    arrived = None
                    is_late = status == LessonAttendance.STATUS_LATE
                    if status in (LessonAttendance.STATUS_PRESENT, LessonAttendance.STATUS_LATE):
                        arrived = timezone.now()
                    LessonAttendance.objects.create(
                        schedule=sch, student=st, status=status,
                        is_late=is_late, arrived_at=arrived,
                    )
                    total_att += 1

        self.stdout.write(self.style.SUCCESS(
            f"Demo tayyor: {len(CLASSES)} sinf, {len(LESSONS)} dars, {total_att} davomat yozuvi.\n"
            f"Endi: python manage.py run_bot  → Telegram'da tugmalarni sinang."
        ))
