"""
Test darsi natijasini CSV ga chiqaradi — sinov isboti uchun.

Har talaba uchun: keldimi, qachon tanildi, qanday ball bilan, SKUD ga
yuborildimi, etaloni bormi. Kelmaganlar ham chiqadi (sababi bilan).

MAVJUD KODGA TEGMAYDI — faqat o'qiydi.

Ishlatish:
    python manage.py lesson_report --schedule-id 12 --out /app/logs/hisobot.csv
    python manage.py lesson_report --schedule-id 12          # stdout ga
"""
import csv
import sys
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand

from apps.attendance.models import LessonAttendance, RecognitionEvent
from apps.face_data.models import StudentEmbedding
from apps.integrations.models import ExternalSchedule, ExternalStudent

TZ = ZoneInfo("Asia/Tashkent")


class Command(BaseCommand):
    help = "Test darsi davomatini CSV ga chiqaradi"

    def add_arguments(self, parser):
        parser.add_argument("--schedule-id", type=int, required=True)
        parser.add_argument("--out", type=str, default=None)
        parser.add_argument("--subject", type=str, default="",
                            help="Fan nomi (DB da saqlanmaydi, hisobotga yoziladi)")

    def handle(self, *args, **o):
        sched = ExternalSchedule.objects.filter(id=o["schedule_id"]).select_related(
            "class_obj", "classroom", "organization").first()
        if not sched:
            self.stderr.write(self.style.ERROR(f"schedule_id={o['schedule_id']} topilmadi"))
            return

        klass = sched.class_obj
        students = list(ExternalStudent.objects.filter(class_obj=klass).order_by("full_name"))

        etalonli = set(StudentEmbedding.objects.filter(
            student__class_obj=klass, is_active=True).values_list("student_id", flat=True))

        # Shu darsdagi davomat
        att = {a.student_id: a for a in LessonAttendance.objects.filter(
            schedule=sched).select_related("recognition_event")}

        # Har talabaning shu darsdagi eng yaxshi tanilishi
        evs = {}
        for ev in RecognitionEvent.objects.filter(
                camera_id=sched.classroom.camera_id,
                recognized_at__date=sched.date,
                recognized_at__time__gte=sched.start_at,
                decision=RecognitionEvent.DECISION_ACCEPTED,
        ).order_by("recognized_at"):
            if ev.student_id and ev.student_id not in evs:
                evs[ev.student_id] = ev

        rows = []
        keldi = kelmadi = etalonsiz = skud_ok = skud_xato = 0
        for st in students:
            ev = evs.get(st.id)
            a = att.get(st.id)
            bor_etalon = st.id in etalonli

            if ev:
                keldi += 1
                holat = "keldi"
                vaqt = ev.recognized_at.astimezone(TZ).strftime("%H:%M:%S")
                ball = f"{ev.similarity:.3f}" if ev.similarity is not None else ""
                if ev.skud_pushed_at:
                    skud = "yuborildi"
                    skud_ok += 1
                elif ev.skud_push_error:
                    skud = f"xato: {ev.skud_push_error[:40]}"
                    skud_xato += 1
                else:
                    skud = "navbatda"
            else:
                kelmadi += 1
                vaqt = ball = ""
                skud = ""
                if not bor_etalon:
                    holat = "kelmadi (SKUD da rasmi yo'q — tanib bo'lmaydi)"
                    etalonsiz += 1
                else:
                    holat = "kelmadi"

            rows.append({
                "sinf": klass.class_name,
                "fio": st.full_name,
                "pinfl": st.pinfl,
                "holat": holat,
                "tanilgan_vaqt": vaqt,
                "ball": ball,
                "skud": skud,
                "etaloni_bor": "ha" if bor_etalon else "yo'q",
                "davomat_yozuvi": (a.status if a else ""),
            })

        # ── CSV ───────────────────────────────────────────────────────────────
        cols = ["sinf", "fio", "pinfl", "holat", "tanilgan_vaqt", "ball",
                "skud", "etaloni_bor", "davomat_yozuvi"]
        fh = open(o["out"], "w", newline="", encoding="utf-8") if o["out"] else sys.stdout
        try:
            fh.write(f"# Dars: {klass.class_name}"
                     f"{' | fan: ' + o['subject'] if o['subject'] else ''}"
                     f" | xona: {sched.classroom.class_room_name}"
                     f" | {sched.date} {sched.start_at}-{sched.end_at}\n")
            fh.write(f"# Jami {len(students)} talaba | keldi {keldi} | kelmadi {kelmadi}"
                     f" | etaloni yo'q {etalonsiz} | SKUD yuborildi {skud_ok}\n")
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        finally:
            if o["out"]:
                fh.close()

        # ── Ekranga xulosa ────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== DARS HISOBOTI ==="))
        self.stdout.write(f"  sinf/xona   : {klass.class_name} / {sched.classroom.class_room_name}"
                          f"{' | fan: ' + o['subject'] if o['subject'] else ''}")
        self.stdout.write(f"  vaqt        : {sched.date} {sched.start_at}–{sched.end_at}")
        self.stdout.write(f"  jami talaba : {len(students)}")
        self.stdout.write(self.style.SUCCESS(f"  KELDI       : {keldi}"))
        self.stdout.write(f"  kelmadi     : {kelmadi}"
                          + (f"  (shundan {etalonsiz} tasining rasmi yo'q)" if etalonsiz else ""))
        self.stdout.write(f"  SKUD        : {skud_ok} yuborildi"
                          + (f", {skud_xato} xato" if skud_xato else ""))
        if len(students):
            qamrov = 100 * keldi // len(students)
            tanish_mumkin = len(students) - etalonsiz
            self.stdout.write(f"  qamrov      : {qamrov}% (tanish mumkin bo'lganlardan: "
                              f"{100 * keldi // tanish_mumkin if tanish_mumkin else 0}%)")
        if o["out"]:
            self.stdout.write("")
            self.stdout.write(f"  CSV: {o['out']}")
