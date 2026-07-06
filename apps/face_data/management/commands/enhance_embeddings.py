"""
SKUD rasmlarini yaxshilab embedding qayta yaratish.

Qiladigan ishlari:
  1. Flip (teskari) rasmlarni aniqlash va to'g'rilash
  2. CLAHE — past yorug'likda kontrast oshirish
  3. Unsharp mask — hira rasmni keskinlashtirish
  4. Yangi embedding yaratish, eskisini deaktiv qilish
  5. Primary embedding belgilash

Ishlatish:
    python manage.py enhance_embeddings --org-id 32
    python manage.py enhance_embeddings --org-id 32 --dry-run
    python manage.py enhance_embeddings --org-id 32 --limit 50
"""
import base64
import time

import cv2
import numpy as np
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.face_data.models import EnrollmentPhoto, StudentEmbedding
from apps.face_data.services import detect_faces, EmbeddingGenerationService


# ─── Preprocessing funksiyalar ────────────────────────────────────────────────

def _read_image(enrollment_photo: EnrollmentPhoto) -> np.ndarray | None:
    ext = enrollment_photo.external_photo
    if ext.image:
        try:
            with ext.image.open("rb") as f:
                data = f.read()
            arr = np.frombuffer(data, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is not None:
                return img
        except Exception:
            pass
    b64 = getattr(ext, "image_base64", None)
    if b64:
        raw = b64.split(",", 1)[-1] if "," in b64 else b64
        arr = np.frombuffer(base64.b64decode(raw), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            return img
    return None


def _is_flipped(face) -> bool:
    """Gorizontal mirror: left_eye.x > right_eye.x (faqat tik yuzlar uchun)."""
    kps = face.kps
    if kps is None or len(kps) < 2:
        return False
    return float(kps[0][0]) > float(kps[1][0])


def _is_upside_down(face) -> bool:
    """180° aylangan: burun ko'z markazidan YUQORIDA turadi (y o'q pastga)."""
    kps = face.kps
    if kps is None or len(kps) < 3:
        return False
    eye_y = (float(kps[0][1]) + float(kps[1][1])) / 2
    nose_y = float(kps[2][1])
    return nose_y < eye_y


def _apply_clahe(img: np.ndarray) -> np.ndarray:
    """LAB rang fazasida L kanaliga CLAHE — yoritish tenglashtirish."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_eq = clahe.apply(l)
    merged = cv2.merge([l_eq, a, b])
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def _apply_sharpening(img: np.ndarray) -> np.ndarray:
    """Unsharp mask — hira rasmni keskinlashtirish."""
    blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=2.0)
    return cv2.addWeighted(img, 1.5, blurred, -0.5, 0)


def enhance_image(img: np.ndarray, face) -> np.ndarray:
    """Rotation tuzatish + CLAHE + sharpening."""
    if _is_upside_down(face):
        img = cv2.rotate(img, cv2.ROTATE_180)   # 180° aylangan rasm
    elif _is_flipped(face):
        img = cv2.flip(img, 1)                   # gorizontal mirror
    img = _apply_clahe(img)
    img = _apply_sharpening(img)
    return img


# ─── Command ──────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "SKUD rasmlarini yaxshilab embedding qayta yaratadi (flip+CLAHE+sharp)"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, default=32,
                            help="Tashkilot org_id (default: 32 = 71-maktab)")
        parser.add_argument("--limit", type=int, default=0,
                            help="Nechta rasm (0 = hammasi)")
        parser.add_argument("--dry-run", action="store_true",
                            help="Yozmaydi, faqat hisobot ko'rsatadi")

    def handle(self, *args, **options):
        org_id   = options["org_id"]
        limit    = options["limit"]
        dry_run  = options["dry_run"]

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS(f"  Enhance Embeddings — org_id={org_id}"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        if dry_run:
            self.stdout.write(self.style.WARNING("  DRY RUN — hech narsa yozilmaydi"))

        qs = EnrollmentPhoto.objects.select_related(
            "student", "student__organization", "external_photo"
        ).filter(
            student__organization__organization_id=org_id,
            status=EnrollmentPhoto.STATUS_EMBEDDED,
        ).order_by("id")

        total = qs.count()
        if limit:
            qs = qs[:limit]
            self.stdout.write(f"  Jami: {total} | Ishlash: {limit}")
        else:
            self.stdout.write(f"  Jami: {total}")

        stats = {
            "ok": 0, "flipped": 0, "upside_down": 0, "no_face": 0,
            "no_image": 0, "error": 0, "skipped": 0,
        }
        t0 = time.time()

        for i, ep in enumerate(qs.iterator(chunk_size=100), 1):
            try:
                self._process_one(ep, stats, dry_run)
            except Exception as exc:
                stats["error"] += 1
                self.stdout.write(
                    self.style.ERROR(f"  XATO [{ep.id}] {ep.student.full_name}: {exc}")
                )

            if i % 50 == 0 or i == total:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed else 0
                self.stdout.write(
                    f"  [{i:4d}/{total}] "
                    f"ok={stats['ok']} flip={stats['flipped']} "
                    f"180°={stats['upside_down']} "
                    f"no_face={stats['no_face']} err={stats['error']} "
                    f"| {rate:.1f} rasm/s",
                    ending="\r",
                )
                self.stdout.flush()

        self.stdout.write("")

        if not dry_run and stats["ok"] > 0:
            self.stdout.write("Primary embeddinglar belgilanmoqda...")
            svc = EmbeddingGenerationService()
            result = svc.mark_primary_embeddings(organization_id=org_id)
            self.stdout.write(self.style.SUCCESS(
                f"Primary: {result['students_with_primary_embedding']} ta o'quvchi"
            ))

        elapsed = time.time() - t0
        self.stdout.write(self.style.SUCCESS(
            f"\n{'=' * 60}\n"
            f"  Tugadi: {elapsed:.0f}s\n"
            f"  Yaxshilandi:      {stats['ok']}\n"
            f"  Flip tuzatildi:   {stats['flipped']}\n"
            f"  180° tuzatildi:   {stats['upside_down']}\n"
            f"  Yuz topilmadi:    {stats['no_face']}\n"
            f"  Rasm yo'q:        {stats['no_image']}\n"
            f"  Xato:             {stats['error']}\n"
            f"{'=' * 60}"
        ))

    def _process_one(self, ep: EnrollmentPhoto, stats: dict, dry_run: bool):
        img = _read_image(ep)
        if img is None:
            stats["no_image"] += 1
            return

        # Asl rasmdan yuz topish
        faces = detect_faces(img)
        if not faces:
            stats["no_face"] += 1
            return

        face = faces[0]
        was_upside_down = _is_upside_down(face)
        was_flipped = (not was_upside_down) and _is_flipped(face)

        # Preprocessing
        enhanced = enhance_image(img, face)

        # Yaxshilangan rasmdan yuz va embedding
        enh_faces = detect_faces(enhanced)
        if not enh_faces:
            # CLAHE/sharpening yuz yo'q qildi — asl rasmni ishlatamiz
            enh_face = face
            enh_img  = img
        else:
            enh_face = enh_faces[0]
            enh_img  = enhanced

        embedding = enh_face.embedding
        if embedding is None:
            stats["no_face"] += 1
            return

        if dry_run:
            stats["ok"] += 1
            if was_flipped:
                stats["flipped"] += 1
            if was_upside_down:
                stats["upside_down"] += 1
            self.stdout.write(
                f"  [DRY] {ep.student.full_name} | "
                f"flip={was_flipped} 180°={was_upside_down} | "
                f"blur={ep.blur_score or 0:.0f}"
            )
            return

        with transaction.atomic():
            # Eski embeddinglarni deaktiv qilish
            StudentEmbedding.objects.filter(
                enrollment_photo=ep, is_active=True
            ).update(is_active=False, is_primary=False)

            # Quality score yangilash
            gray = cv2.cvtColor(enh_img, cv2.COLOR_BGR2GRAY)
            new_blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            bbox = enh_face.bbox.astype(int)
            fw = int(bbox[2] - bbox[0])
            fh = int(bbox[3] - bbox[1])
            area_score = min((fw * fh) / 40_000.0, 1.0)
            blur_norm  = min(new_blur / 300.0, 1.0)
            new_quality = round((area_score * 0.4 + blur_norm * 0.6) * 100, 2)

            # Yangi embedding yaratish
            StudentEmbedding.objects.create(
                student=ep.student,
                enrollment_photo=ep,
                model_name=StudentEmbedding.MODEL_ARCFACE,
                model_version="buffalo_l_enhanced",
                embedding=embedding.astype(np.float32).tolist(),
                embedding_dim=len(embedding),
                is_primary=False,
                quality_score=new_quality,
                is_active=True,
            )

            # EnrollmentPhoto ni yangilash
            ep.blur_score    = new_blur
            ep.face_width    = fw
            ep.face_height   = fh
            ep.quality_score = new_quality
            ep.save(update_fields=[
                "blur_score", "face_width", "face_height",
                "quality_score", "updated_at"
            ])

        stats["ok"] += 1
        if was_flipped:
            stats["flipped"] += 1
        if was_upside_down:
            stats["upside_down"] += 1
