"""
71-maktab 9G sinf uchun mock ma'lumotlar va embedding yaratish.

Nima qiladi:
  1. Tashkilot, sinf, bino, xona, kamera, jadval yaratadi
  2. Video fayldan yuzlarni topib, eng ko'p ko'ringan N ta yuzni oladi
  3. Har bir yuz uchun mock talaba + StudentEmbedding yaratadi
  4. Bugungi dars jadvali qo'yadi (kamera camera_id=1)

Ishga tushirish:
  docker compose exec web python3.14 manage.py seed_71_school
  docker compose exec web python3.14 manage.py seed_71_school --video /app/... --students 20
"""
import base64
import uuid
from collections import defaultdict
from datetime import date, time as dtime, timedelta

import cv2
import numpy as np
from django.core.management.base import BaseCommand
from django.utils import timezone


UZBEK_NAMES = [
    "Abdullayev Sherzod", "Toshmatov Jasur", "Yusupov Bobur",
    "Karimov Ulugbek", "Rahimov Sardor", "Xoliqov Doniyor",
    "Ergashev Oybek", "Nazarov Sanjar", "Mirzayev Ibrohim",
    "Qodirov Firdavs", "Holmatov Umid", "Sultonov Akbar",
    "Tursunov Otabek", "Baxtiyorov Shuhrat", "Nishonov Mansur",
    "Xasanov Dilshod", "Raximov Zafar", "Mamatov Anvar",
    "Usmonov Alisher", "Jurayev Hamidjon", "Sobirov Murod",
    "Haydarov Temur", "Qosimov Bunyod", "Fattoyev Lochin",
    "Botirov Ismoil", "Alimov Sirojiddin", "Normatov Elmurod",
    "Pulatov Furqat", "Muhammadiyev Samandar", "Xo'jayev Jahongir",
]


class Command(BaseCommand):
    help = "71-maktab 9G sinf uchun mock data va embedding yaratish"

    def add_arguments(self, parser):
        parser.add_argument(
            "--video",
            default="/app/deepstream_data/sinf.mp4",
            help="Video fayl yo'li (web container ichidagi yo'l: /app/deepstream_data/sinf.mp4)",
        )
        parser.add_argument(
            "--students",
            type=int,
            default=20,
            help="Nechta talaba yaratish (video dan topilgan yuzlar soni bilan cheklanadi)",
        )
        parser.add_argument(
            "--scan-frames",
            type=int,
            default=3000,
            help="Videoning qancha kadrini skanerlash",
        )
        parser.add_argument(
            "--frame-skip",
            type=int,
            default=5,
            help="Har necha kadrdan biri ishlanaladi",
        )
        parser.add_argument(
            "--min-face",
            type=int,
            default=60,
            help="Minimal yuz o'lchami (piksel)",
        )

    def handle(self, *args, **options):
        from apps.cameras.models import Auditorium, Building, Camera
        from apps.face_data.models import EnrollmentPhoto, StudentEmbedding
        from apps.integrations.models import (
            ExternalClass,
            ExternalClassroom,
            ExternalOrganization,
            ExternalSchedule,
            ExternalStudent,
            ExternalStudentPhoto,
        )

        video_path = options["video"]
        max_students = options["students"]
        scan_frames = options["scan_frames"]
        frame_skip = options["frame_skip"]
        min_face = options["min_face"]

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("  71-maktab 9G Mock Data"))
        self.stdout.write(self.style.SUCCESS("=" * 60))

        # ── 1. Tashkilot tuzilmasi ────────────────────────────────────────────
        self.stdout.write("\n[1/5] Tashkilot tuzilmasi yaratilmoqda...")

        org, _ = ExternalOrganization.objects.get_or_create(
            organization_id=710001,
            defaults={"organization_name": "71-maktab", "organization_inn": "710001"},
        )

        cls, _ = ExternalClass.objects.get_or_create(
            class_id=7100091,
            defaults={"class_name": "9G", "class_degree": 9, "organization": org},
        )

        building, _ = Building.objects.get_or_create(
            name="71-maktab asosiy bino",
        )

        auditorium, _ = Auditorium.objects.get_or_create(
            name="9-xona (Algebra)",
            defaults={"building": building},
        )

        camera, created = Camera.objects.get_or_create(
            name="71-maktab 9G algebra kamera",
            defaults={
                "ip_address": "192.168.1.101",
                "username": "admin",
                "password": "admin123",
                "stream_url": "rtsp://192.168.1.101:554/stream1",
                "organization_id": org.organization_id,
                "is_active_stream": True,
            },
        )
        if created:
            self.stdout.write(f"  Camera yaratildi: pk={camera.pk}")
        else:
            self.stdout.write(f"  Camera mavjud: pk={camera.pk}")

        classroom, _ = ExternalClassroom.objects.get_or_create(
            class_room_id=7100091001,
            defaults={
                "class_room_name": "9-xona",
                "organization": org,
                "camera": camera,
                "auditorium": auditorium,
            },
        )
        if not classroom.camera:
            classroom.camera = camera
            classroom.save(update_fields=["camera"])

        # ── 2. Bugungi dars jadvali ───────────────────────────────────────────
        self.stdout.write("\n[2/5] Dars jadvali yaratilmoqda...")

        today = date.today()
        # Dars vaqti: 08:00 - 18:00 (test uchun butun kun aktiv)
        schedule, _ = ExternalSchedule.objects.get_or_create(
            organization=org,
            class_obj=cls,
            classroom=classroom,
            lesson_number=3,
            date=today,
            defaults={
                "start_at": dtime(8, 0),
                "end_at": dtime(18, 0),
                "timezone": "Asia/Tashkent",
            },
        )
        self.stdout.write(f"  Jadval: {today} 08:00-18:00 (bugun, dars №3)")
        self.stdout.write(f"  Camera ID: {camera.pk} (kafka_consumer shu ID ni ishlatadi)")

        # ── 3. Videoni skanerlab yuzlarni topish ─────────────────────────────
        self.stdout.write(f"\n[3/5] Video skanerlanmoqda: {video_path}")
        self.stdout.write(f"  Birinchi {scan_frames} kadr, har {frame_skip} ta dan biri")

        face_crops = self._extract_faces_from_video(
            video_path, scan_frames, frame_skip, min_face, max_students
        )

        if not face_crops:
            self.stdout.write(self.style.ERROR("  Yuz topilmadi! Video faylni tekshiring."))
            return

        self.stdout.write(self.style.SUCCESS(f"  {len(face_crops)} ta unikal yuz topildi"))

        # ── 4. Talabalar va fotosuratlar ─────────────────────────────────────
        self.stdout.write(f"\n[4/5] {len(face_crops)} ta talaba yaratilmoqda...")

        created_count = 0
        for i, (track_id, crop_bgr) in enumerate(face_crops):
            name = UZBEK_NAMES[i % len(UZBEK_NAMES)]
            pinfl = f"mock71_{track_id:04d}"

            student, s_created = ExternalStudent.objects.get_or_create(
                pinfl=pinfl,
                defaults={"full_name": name, "organization": org, "class_obj": cls},
            )
            if not s_created:
                continue

            # JPG → base64
            _, jpg_buf = cv2.imencode(".jpg", crop_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
            img_b64 = base64.b64encode(jpg_buf.tobytes()).decode()

            ext_photo = ExternalStudentPhoto.objects.create(
                student=student,
                photo_type="front",
                photo_guid=str(uuid.uuid4()),
                image_base64=img_b64,
            )

            enroll = EnrollmentPhoto.objects.create(
                external_photo=ext_photo,
                student=student,
                status=EnrollmentPhoto.STATUS_VALID,
                face_count=1,
                face_width=crop_bgr.shape[1],
                face_height=crop_bgr.shape[0],
            )

            # Embedding
            embedding = self._get_embedding(crop_bgr)
            if embedding is not None:
                StudentEmbedding.objects.create(
                    student=student,
                    enrollment_photo=enroll,
                    model_name=StudentEmbedding.MODEL_ARCFACE,
                    model_version="buffalo_l",
                    embedding=embedding.tolist(),
                    embedding_dim=512,
                    is_primary=True,
                    is_active=True,
                )
                created_count += 1
                self.stdout.write(f"  [{i+1:2d}] {name} — embedding qurildi")
            else:
                enroll.status = EnrollmentPhoto.STATUS_NO_FACE
                enroll.save(update_fields=["status"])
                self.stdout.write(self.style.WARNING(f"  [{i+1:2d}] {name} — embedding yo'q"))

        # ── 5. Yakuniy hisobot ────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS("\n[5/5] YAKUNIY HOLAT:"))
        self.stdout.write(f"  Tashkilot:    {org.organization_name} (id={org.organization_id})")
        self.stdout.write(f"  Sinf:         {cls.class_name}")
        self.stdout.write(f"  Camera pk:    {camera.pk}")
        self.stdout.write(f"  Jadval:       {today} 08:00-18:00")
        self.stdout.write(f"  Talabalar:    {created_count} ta (embedding bilan)")
        self.stdout.write(f"  Embedding:    {StudentEmbedding.objects.filter(is_active=True).count()} jami")

        self.stdout.write(self.style.SUCCESS("\nPipeline tayyor! Deepstream logini kuzating:"))
        self.stdout.write("  docker compose logs -f deepstream kafka_consumer")

        if camera.pk != 1:
            self.stdout.write(self.style.WARNING(
                f"\n  DIQQAT: Camera pk={camera.pk}, lekin DeepStream CAMERA_ID=1 yuboryapti."
                f"\n  .env faylida DEEPSTREAM_CAMERA_ID={camera.pk} qiling va deepstream ni restart qiling."
            ))

    def _extract_faces_from_video(self, video_path, scan_frames, frame_skip, min_face, max_count):
        """Video dan unikal yuzlarni ajratib oladi."""
        from insightface.app import FaceAnalysis

        self.stdout.write("  InsightFace yuklanmoqda...")
        face_app = FaceAnalysis(
            name="buffalo_l",
            allowed_modules=["detection"],
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        face_app.prepare(ctx_id=0, det_size=(640, 640))

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            self.stdout.write(self.style.ERROR(f"  Video ochilmadi: {video_path}"))
            return []

        # track_id → [(frame_idx, crop, bbox_area)]
        track_best: dict[int, tuple] = {}
        tracker = SimpleTracker()
        frame_idx = 0

        while frame_idx < scan_frames:
            ok, frame = cap.read()
            if not ok:
                break
            frame_idx += 1
            if frame_idx % frame_skip != 0:
                continue

            faces = face_app.get(frame)
            h, w = frame.shape[:2]

            bboxes = []
            for f in faces:
                x1, y1, x2, y2 = f.bbox.astype(int)
                fw, fh = x2 - x1, y2 - y1
                if fw < min_face or fh < min_face:
                    continue
                bboxes.append((x1, y1, x2, y2, f.det_score))

            track_ids = tracker.update([(b[0], b[1], b[2], b[3]) for b in bboxes])

            for i, (x1, y1, x2, y2, score) in enumerate(bboxes):
                tid = track_ids[i] if i < len(track_ids) else -1
                area = (x2 - x1) * (y2 - y1)

                pad = 0.25
                cx1 = max(0, int(x1 - (x2-x1)*pad))
                cy1 = max(0, int(y1 - (y2-y1)*pad))
                cx2 = min(w, int(x2 + (x2-x1)*pad))
                cy2 = min(h, int(y2 + (y2-y1)*pad))
                crop = frame[cy1:cy2, cx1:cx2]
                if crop.size == 0:
                    continue

                if tid not in track_best or track_best[tid][0] < area * score:
                    track_best[tid] = (area * score, crop)

        cap.release()

        # Eng katta/sifatli yuzlar bo'yicha saralash
        sorted_tracks = sorted(track_best.items(), key=lambda x: x[1][0], reverse=True)
        return [(tid, data[1]) for tid, data in sorted_tracks[:max_count]]

    def _get_embedding(self, crop_bgr):
        """Yuz cropi uchun 512-dim ArcFace embedding."""
        if not hasattr(self, "_face_app_full"):
            from insightface.app import FaceAnalysis
            self._face_app_full = FaceAnalysis(
                name="buffalo_l",
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            self._face_app_full.prepare(ctx_id=0, det_size=(320, 320))

        faces = self._face_app_full.get(crop_bgr)
        if not faces:
            return None
        best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        return best.embedding


class SimpleTracker:
    """Yuz markazlari asosida track ID berish."""

    def __init__(self):
        self.next_id = 0
        self.objects: dict[int, tuple] = {}

    def update(self, bboxes):
        centroids = [((x1+x2)//2, (y1+y2)//2) for x1, y1, x2, y2 in bboxes]
        if not centroids:
            return []
        if not self.objects:
            ids = []
            for c in centroids:
                self.objects[self.next_id] = c
                ids.append(self.next_id)
                self.next_id += 1
            return ids

        obj_ids = list(self.objects.keys())
        obj_cents = list(self.objects.values())
        D = np.hypot(
            np.array([c[0] for c in obj_cents])[:, None] - np.array([c[0] for c in centroids]),
            np.array([c[1] for c in obj_cents])[:, None] - np.array([c[1] for c in centroids]),
        )
        assigned = {}
        used_r, used_c = set(), set()
        for _ in range(min(len(obj_ids), len(centroids))):
            r, c = np.unravel_index(D.argmin(), D.shape)
            if D[r, c] > 120 or r in used_r or c in used_c:
                D[r, :] = 1e9; D[:, c] = 1e9
                continue
            assigned[c] = obj_ids[r]
            self.objects[obj_ids[r]] = centroids[c]
            used_r.add(r); used_c.add(c)
            D[r, :] = 1e9; D[:, c] = 1e9
        for i, c in enumerate(centroids):
            if i not in assigned:
                self.objects[self.next_id] = c
                assigned[i] = self.next_id
                self.next_id += 1
        return [assigned.get(i, -1) for i in range(len(bboxes))]
