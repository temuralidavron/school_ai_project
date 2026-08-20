"""
Jonli sinov uchun VAQTINCHALIK dars yozuvi yaratadi.

Ta'til paytida yoki jadval bo'lmaganda bolalar bir xonaga yig'ilganda ishlatiladi:
davomat pipeline'i dars yozuvisiz ishlamaydi (LessonEmbeddingCache bugungi sana +
hozirgi vaqt oralig'idagi ExternalSchedule ni qidiradi).

MAVJUD KODGA TEGMAYDI — faqat bitta ExternalSchedule qatori qo'shadi.

Ishlatish:
    python manage.py setup_test_lesson --org-id 16 --class-name 10-A --camera-id 3 --duration 45
    python manage.py setup_test_lesson --org-id 16 --class-name 10-A --camera-id 3 --cleanup
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db.models import Max

from apps.cameras.models import Camera
from apps.face_data.models import StudentEmbedding
from apps.integrations.models import (
    ExternalClass,
    ExternalClassroom,
    ExternalOrganization,
    ExternalSchedule,
    ExternalStudent,
)

TZ = ZoneInfo("Asia/Tashkent")


class Command(BaseCommand):
    help = "Jonli sinov uchun vaqtinchalik dars yozuvi yaratadi"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, required=True)
        parser.add_argument("--class-name", type=str, required=True,
                            help="Sinf nomi, masalan 10-A")
        parser.add_argument("--camera-id", type=int, required=True,
                            help="Camera.id — xona shu kamera orqali topiladi")
        parser.add_argument("--duration", type=int, default=45,
                            help="Dars davomiyligi, daqiqa (default 45)")
        parser.add_argument("--subject", type=str, default="Tarix",
                            help="Fan nomi — faqat hisobot uchun, DB da saqlanmaydi")
        parser.add_argument("--cleanup", action="store_true",
                            help="Yaratilgan test darsini va uning davomatini o'chiradi")

    def handle(self, *args, **o):
        org = ExternalOrganization.objects.filter(organization_id=o["org_id"]).first()
        if not org:
            self.stderr.write(self.style.ERROR(
                f"org_id={o['org_id']} topilmadi. Avval: manage.py sync_organizations"))
            return

        klass = ExternalClass.objects.filter(
            organization=org, class_name__iexact=o["class_name"]).first()
        if not klass:
            mavjud = list(ExternalClass.objects.filter(organization=org)
                          .values_list("class_name", flat=True)[:20])
            self.stderr.write(self.style.ERROR(
                f"'{o['class_name']}' sinfi topilmadi. Mavjud: {mavjud}"))
            return

        camera = Camera.objects.filter(id=o["camera_id"]).first()
        if not camera:
            self.stderr.write(self.style.ERROR(f"Camera id={o['camera_id']} topilmadi"))
            return

        # Davomat va SKUD push kamera->xona bog'lanishisiz ishlamaydi
        # (services.py _find_classroom: ExternalClassroom.filter(camera_id=...))
        room = ExternalClassroom.objects.filter(camera_id=camera.id).first()
        if not room:
            self.stderr.write(self.style.ERROR(
                f"Camera id={camera.id} ('{camera.name}') hech bir xonaga bog'lanmagan.\n"
                f"  Sabab: ExternalClassroom.camera_id bo'sh. sync_full kamera'ni "
                f"skud_device_id orqali bog'laydi — Camera.skud_device_id ni tekshiring "
                f"(hozir: {camera.skud_device_id!r})."))
            return

        today = datetime.now(TZ).date()

        if o["cleanup"]:
            qs = ExternalSchedule.objects.filter(
                organization=org, class_obj=klass, classroom=room, date=today)
            n = qs.count()
            qs.delete()
            self.stdout.write(self.style.SUCCESS(f"O'chirildi: {n} ta test darsi"))
            return

        now = datetime.now(TZ)
        start = now.time().replace(microsecond=0)
        end = (now + timedelta(minutes=o["duration"])).time().replace(microsecond=0)

        # unique constraint: (organization, class_obj, classroom, lesson_number, date)
        top = ExternalSchedule.objects.filter(
            organization=org, date=today).aggregate(m=Max("lesson_number"))["m"]
        lesson_no = (top or 0) + 1

        sched = ExternalSchedule.objects.create(
            organization=org, class_obj=klass, classroom=room,
            lesson_number=lesson_no, date=today,
            timezone="Asia/Tashkent", start_at=start, end_at=end,
        )

        # Sinf tayyorligi — nechta bola umuman tanilishi mumkin
        jami = ExternalStudent.objects.filter(class_obj=klass).count()
        etalonli = (StudentEmbedding.objects
                    .filter(student__class_obj=klass, is_active=True)
                    .values("student_id").distinct().count())

        self.stdout.write(self.style.SUCCESS("Test darsi yaratildi"))
        self.stdout.write(f"  schedule_id : {sched.id}")
        self.stdout.write(f"  sinf        : {klass.class_name}  (fan: {o['subject']})")
        self.stdout.write(f"  xona        : {room.class_room_name}  (classRoomId={room.class_room_id})")
        self.stdout.write(f"  kamera      : id={camera.id}  {camera.name}")
        self.stdout.write(f"  sana/vaqt   : {today}  {start}–{end}  ({o['duration']} daqiqa)")
        self.stdout.write(f"  dars raqami : {lesson_no}")
        self.stdout.write("")
        self.stdout.write(f"  sinfda talaba      : {jami}")
        if etalonli < jami:
            self.stdout.write(self.style.WARNING(
                f"  etaloni bor        : {etalonli}  "
                f"({jami - etalonli} tasi TANILMAYDI — SKUD da rasmi yo'q)"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  etaloni bor        : {etalonli}"))
        self.stdout.write("")
        self.stdout.write(f"  Sinov tugagach o'chirish uchun: --cleanup")
