import logging
import os
import threading
import time
import cv2
import numpy as np

logger = logging.getLogger(__name__)
from collections import defaultdict

from django.db import transaction
from django.db.models import Count, F, Q
from pgvector.django import CosineDistance
from insightface.app import FaceAnalysis

from apps.face_data.models import EnrollmentPhoto, StudentEmbedding
from apps.integrations.models import ExternalStudent, ExternalStudentPhoto

# buffalo_l bir marta yuklanadi — har yangi service obyektida qayta disk o'qilmaydi
_face_app: FaceAnalysis | None = None
_face_app_init_lock = threading.Lock()
# InsightFace FaceAnalysis.get() ichki buferlar ishlatadi — thread-safe emas.
# CPU da parallel inference ham foyda bermaydi (bottleneck CPU o'zi).
# Shuning uchun barcha threadlar bir navbat orqali o'tadi.
_face_app_inference_lock = threading.Lock()

_PGVECTOR_FETCH_LIMIT = 1000
_QUALITY_FACE_AREA_NORM = 40_000.0  # 200x200 piksel yuz "ideal" deb hisoblangan
_QUALITY_BLUR_NORM = 300.0          # Laplacian dispersiyasi "ideal" deb hisoblangan


def get_face_app() -> FaceAnalysis:
    global _face_app
    if _face_app is None:
        with _face_app_init_lock:
            if _face_app is None:
                from django.conf import settings
                gpu_id  = getattr(settings, "AI_GPU_ID",   -1)
                det_dim = getattr(settings, "AI_DET_SIZE", 640)
                app = FaceAnalysis(name="buffalo_l")
                app.prepare(ctx_id=gpu_id, det_size=(det_dim, det_dim))
                logger.info(
                    "InsightFace tayyor: ctx_id=%s (%s) det_size=%sx%s",
                    gpu_id, "GPU" if gpu_id >= 0 else "CPU", det_dim, det_dim,
                )
                _face_app = app
    return _face_app


def detect_faces(img: np.ndarray) -> list:
    """Thread-safe InsightFace yuz aniqlash — barcha threadlar shu orqali o'tadi."""
    app = get_face_app()
    _wait0 = time.monotonic()
    with _face_app_inference_lock:
        _t0 = time.monotonic()
        faces = app.get(img)
        _dur_ms = int((time.monotonic() - _t0) * 1000)
    _wait_ms = int((_t0 - _wait0) * 1000)
    try:
        from django.conf import settings as _s
        _warn = int(getattr(_s, "AI_INFERENCE_WARN_MS", 2000))
    except Exception:
        _warn = 2000
    if _dur_ms + _wait_ms > _warn:
        logger.warning(
            "INFERENCE SEKIN | inference=%dms lock_kutish=%dms (jami=%dms > %dms) "
            "— GPU yuklangan yoki kamera ko'p",
            _dur_ms, _wait_ms, _dur_ms + _wait_ms, _warn,
        )
    return faces


class EnrollmentAuditService:
    REQUIRED_PHOTO_TYPES = {"front", "up", "left", "right", "bottom"}

    def ensure_enrollment_rows(self, organization_id: int | None = None):
        photos_qs = ExternalStudentPhoto.objects.select_related("student", "student__organization")

        if organization_id is not None:
            photos_qs = photos_qs.filter(
                student__organization__organization_id=organization_id
            )

        existing_ids = set(
            EnrollmentPhoto.objects.filter(
                external_photo__in=photos_qs
            ).values_list("external_photo_id", flat=True)
        )

        to_create = []
        for photo in photos_qs.iterator(chunk_size=500):
            if photo.id not in existing_ids:
                to_create.append(
                    EnrollmentPhoto(
                        external_photo=photo,
                        student=photo.student,
                        status=EnrollmentPhoto.STATUS_PENDING,
                    )
                )

        if to_create:
            EnrollmentPhoto.objects.bulk_create(to_create, batch_size=500, ignore_conflicts=True)

        return len(to_create)

    def build_summary(self, organization_id: int | None = None):
        students_qs = ExternalStudent.objects.select_related("organization")
        photos_qs = ExternalStudentPhoto.objects.select_related("student", "student__organization")
        enroll_qs = EnrollmentPhoto.objects.select_related("student", "student__organization")

        if organization_id is not None:
            students_qs = students_qs.filter(organization__organization_id=organization_id)
            photos_qs = photos_qs.filter(student__organization__organization_id=organization_id)
            enroll_qs = enroll_qs.filter(student__organization__organization_id=organization_id)

        total_students = students_qs.count()
        total_photos = photos_qs.count()
        total_enrollment_rows = enroll_qs.count()

        photo_stats = (
            photos_qs.values("student_id")
            .annotate(
                total=Count("id"),
                front=Count("id", filter=Q(photo_type="front")),
                up=Count("id", filter=Q(photo_type="up")),
                left=Count("id", filter=Q(photo_type="left")),
                right=Count("id", filter=Q(photo_type="right")),
                bottom=Count("id", filter=Q(photo_type="bottom")),
            )
        )

        full_set_students = 0
        partial_students = 0
        students_with_photos = set()

        for row in photo_stats:
            students_with_photos.add(row["student_id"])
            has_full = (
                row["front"] > 0
                and row["up"] > 0
                and row["left"] > 0
                and row["right"] > 0
                and row["bottom"] > 0
            )
            if has_full:
                full_set_students += 1
            else:
                partial_students += 1

        no_photo_students = total_students - len(students_with_photos)

        pending_count = enroll_qs.filter(status=EnrollmentPhoto.STATUS_PENDING).count()
        embedded_count = enroll_qs.filter(status=EnrollmentPhoto.STATUS_EMBEDDED).count()
        valid_count = enroll_qs.filter(status=EnrollmentPhoto.STATUS_VALID).count()
        failed_count = enroll_qs.filter(
            status__in=[
                EnrollmentPhoto.STATUS_NO_FACE,
                EnrollmentPhoto.STATUS_MULTI_FACE,
                EnrollmentPhoto.STATUS_BLURRY,
                EnrollmentPhoto.STATUS_TOO_SMALL,
                EnrollmentPhoto.STATUS_FAILED,
            ]
        ).count()

        return {
            "organization_id": organization_id,
            "total_students": total_students,
            "total_photos": total_photos,
            "total_enrollment_rows": total_enrollment_rows,
            "students_with_full_5_photos": full_set_students,
            "students_with_partial_photos": partial_students,
            "students_with_no_photos": no_photo_students,
            "pending_enrollment": pending_count,
            "valid_enrollment": valid_count,
            "embedded_enrollment": embedded_count,
            "failed_enrollment": failed_count,
        }


class EnrollmentQualityService:
    """
    EnrollmentPhoto sifatini InsightFace bilan tekshiradi.
    Oldingi Haar Cascade o'rniga get_face_app() ishlatiladi —
    EmbeddingGenerationService bilan bir xil model, izchil natija.
    """

    def __init__(self, blur_threshold: float = 80.0, min_face_size: int = 80):
        self.blur_threshold = blur_threshold
        self.min_face_size = min_face_size

    def _calc_quality_score(self, blur_score: float, face_w: int, face_h: int) -> float:
        size_score = min((face_w * face_h) / _QUALITY_FACE_AREA_NORM, 1.0) if face_w and face_h else 0.0
        blur_norm = min(blur_score / _QUALITY_BLUR_NORM, 1.0)
        return round((size_score * 0.4 + blur_norm * 0.6) * 100, 2)

    def _mark_failed(self, record: EnrollmentPhoto, status: str, reason: str):
        record.status = status
        record.failure_reason = reason
        record.save(update_fields=["status", "failure_reason", "updated_at"])

    def process_one(self, record: EnrollmentPhoto):
        image_field = record.external_photo.image

        if not image_field:
            self._mark_failed(record, EnrollmentPhoto.STATUS_FAILED, "Image field bo'sh")
            return record

        try:
            img = _read_image_from_field(image_field)
        except ValueError as exc:
            self._mark_failed(record, EnrollmentPhoto.STATUS_FAILED, str(exc))
            return record

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        record.blur_score = blur_score

        faces = detect_faces(img)
        record.face_count = len(faces)

        if len(faces) == 0:
            record.status = EnrollmentPhoto.STATUS_NO_FACE
            record.failure_reason = "No face detected"
            record.save(update_fields=["blur_score", "face_count", "status", "failure_reason", "updated_at"])
            return record

        if len(faces) > 1:
            record.status = EnrollmentPhoto.STATUS_MULTI_FACE
            record.failure_reason = f"Multiple faces detected: {len(faces)}"
            record.save(update_fields=["blur_score", "face_count", "status", "failure_reason", "updated_at"])
            return record

        face = faces[0]
        x1, y1, x2, y2 = face.bbox.astype(int).tolist()
        w = x2 - x1
        h = y2 - y1
        record.face_width = int(w)
        record.face_height = int(h)

        if min(w, h) < self.min_face_size:
            record.status = EnrollmentPhoto.STATUS_TOO_SMALL
            record.failure_reason = f"Face too small: {w}x{h}"
            record.save(
                update_fields=["blur_score", "face_count", "face_width", "face_height",
                               "status", "failure_reason", "updated_at"]
            )
            return record

        if blur_score < self.blur_threshold:
            record.status = EnrollmentPhoto.STATUS_BLURRY
            record.failure_reason = f"Blur score too low: {blur_score:.2f}"
            record.save(
                update_fields=["blur_score", "face_count", "face_width", "face_height",
                               "status", "failure_reason", "updated_at"]
            )
            return record

        record.quality_score = self._calc_quality_score(blur_score, w, h)
        record.status = EnrollmentPhoto.STATUS_VALID
        record.failure_reason = ""
        record.save(
            update_fields=["blur_score", "face_count", "face_width", "face_height",
                           "quality_score", "status", "failure_reason", "updated_at"]
        )
        return record

    def scan_batch(self, organization_id: int | None = None, limit: int = 100):
        qs = EnrollmentPhoto.objects.select_related(
            "student",
            "student__organization",
            "external_photo",
        ).filter(status=EnrollmentPhoto.STATUS_PENDING)

        if organization_id is not None:
            qs = qs.filter(student__organization__organization_id=organization_id)

        records = list(qs.order_by("id")[:limit])

        processed = 0
        valid = 0
        failed = 0

        for record in records:
            self.process_one(record)
            processed += 1

            if record.status == EnrollmentPhoto.STATUS_VALID:
                valid += 1
            elif record.status != EnrollmentPhoto.STATUS_PENDING:
                failed += 1

        remaining = EnrollmentPhoto.objects.filter(status=EnrollmentPhoto.STATUS_PENDING)
        if organization_id is not None:
            remaining = remaining.filter(student__organization__organization_id=organization_id)

        return {
            "organization_id": organization_id,
            "processed": processed,
            "valid": valid,
            "non_valid": failed,
            "remaining_pending": remaining.count(),
        }

    def summary(self, organization_id: int | None = None):
        qs = EnrollmentPhoto.objects.select_related("student", "student__organization")

        if organization_id is not None:
            qs = qs.filter(student__organization__organization_id=organization_id)

        return {
            "organization_id": organization_id,
            "pending": qs.filter(status=EnrollmentPhoto.STATUS_PENDING).count(),
            "valid": qs.filter(status=EnrollmentPhoto.STATUS_VALID).count(),
            "embedded": qs.filter(status=EnrollmentPhoto.STATUS_EMBEDDED).count(),
            "no_face": qs.filter(status=EnrollmentPhoto.STATUS_NO_FACE).count(),
            "multi_face": qs.filter(status=EnrollmentPhoto.STATUS_MULTI_FACE).count(),
            "blurry": qs.filter(status=EnrollmentPhoto.STATUS_BLURRY).count(),
            "too_small": qs.filter(status=EnrollmentPhoto.STATUS_TOO_SMALL).count(),
            "failed": qs.filter(status=EnrollmentPhoto.STATUS_FAILED).count(),
        }


def _read_image_from_field(image_field) -> np.ndarray:
    """ImageField dan numpy array — lokal disk yoki MinIO (S3) uchun ishlaydi."""
    if not image_field:
        raise ValueError("Image field bo'sh")
    try:
        with image_field.open("rb") as f:
            img_bytes = f.read()
    except Exception as exc:
        raise ValueError(f"Rasmni o'qib bo'lmadi: {exc}") from exc
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("cv2.imdecode muvaffaqiyatsiz — fayl buzilgan bo'lishi mumkin")
    return img


class EmbeddingGenerationService:

    def _read_image(self, enrollment_photo: EnrollmentPhoto):
        ext_photo = enrollment_photo.external_photo
        image_field = ext_photo.image
        if image_field:
            try:
                return _read_image_from_field(image_field)
            except Exception as e:
                logger.debug("MinIO dan o'qib bo'lmadi, base64 ga o'tilmoqda: %s", e)

        # MinIO ishlamasa — DB dagi base64 dan o'qiymiz
        b64 = getattr(ext_photo, "image_base64", None)
        if not b64:
            raise ValueError("Rasm yo'q: na MinIO, na image_base64")
        import base64 as _b64
        raw = b64.split(",", 1)[-1] if "," in b64 else b64
        img_bytes = _b64.b64decode(raw)
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("base64 dan rasm o'qib bo'lmadi")
        return img

    def process_one(self, enrollment_photo: EnrollmentPhoto):
        if enrollment_photo.status != EnrollmentPhoto.STATUS_VALID:
            raise ValueError(f"EnrollmentPhoto status valid emas: {enrollment_photo.status}")

        img = self._read_image(enrollment_photo)
        faces = detect_faces(img)

        if len(faces) == 0:
            enrollment_photo.status = EnrollmentPhoto.STATUS_NO_FACE
            enrollment_photo.failure_reason = "No face detected by InsightFace"
            enrollment_photo.save(update_fields=["status", "failure_reason", "updated_at"])
            raise ValueError("No face detected")

        if len(faces) > 1:
            enrollment_photo.status = EnrollmentPhoto.STATUS_MULTI_FACE
            enrollment_photo.failure_reason = f"Multiple faces detected by InsightFace: {len(faces)}"
            enrollment_photo.save(update_fields=["status", "failure_reason", "updated_at"])
            raise ValueError("Multiple faces detected")

        face = faces[0]
        embedding = face.embedding
        if embedding is None:
            enrollment_photo.status = EnrollmentPhoto.STATUS_FAILED
            enrollment_photo.failure_reason = "Embedding is None"
            enrollment_photo.save(update_fields=["status", "failure_reason", "updated_at"])
            raise ValueError("Embedding is None")

        embedding_list = embedding.astype(np.float32).tolist()

        student_embedding = StudentEmbedding.objects.create(
            student=enrollment_photo.student,
            enrollment_photo=enrollment_photo,
            model_name=StudentEmbedding.MODEL_ARCFACE,
            model_version="buffalo_l",
            embedding=embedding_list,
            embedding_dim=len(embedding_list),
            is_primary=False,
            quality_score=enrollment_photo.quality_score,
            is_active=True,
        )

        enrollment_photo.status = EnrollmentPhoto.STATUS_EMBEDDED
        enrollment_photo.failure_reason = ""
        enrollment_photo.save(update_fields=["status", "failure_reason", "updated_at"])

        return student_embedding

    def process_batch(self, organization_id: int | None = None, limit: int = 50):
        """Har bir yozuv o'z transaksiyasida — bittasi xato bo'lsa qolganlari saqlanadi."""
        qs = EnrollmentPhoto.objects.select_related(
            "student",
            "student__organization",
            "external_photo",
        ).filter(status=EnrollmentPhoto.STATUS_VALID)

        if organization_id is not None:
            qs = qs.filter(student__organization__organization_id=organization_id)

        qs = qs.exclude(embeddings__isnull=False).order_by("id")[:limit]
        records = list(qs)

        embedded = 0
        failed = []

        for record in records:
            try:
                with transaction.atomic():
                    self.process_one(record)
                embedded += 1
            except Exception as e:
                failed.append({
                    "id": record.id,
                    "pinfl": record.student.pinfl,
                    "photo_type": record.external_photo.photo_type,
                    "error": str(e),
                })

        remaining_qs = (
            EnrollmentPhoto.objects
            .select_related("student")
            .filter(status=EnrollmentPhoto.STATUS_VALID)
            .exclude(embeddings__isnull=False)
        )
        if organization_id is not None:
            remaining_qs = remaining_qs.filter(
                student__organization__organization_id=organization_id
            )

        return {
            "organization_id": organization_id,
            "processed": len(records),
            "embedded": embedded,
            "failed_count": len(failed),
            "failed_preview": failed[:10],
            "remaining_valid_without_embedding": remaining_qs.count(),
        }

    def mark_primary_embeddings(self, organization_id: int | None = None):
        """
        Har talaba uchun eng yuqori sifatli embeddingni primary=True qiladi.
        PostgreSQL DISTINCT ON orqali N+1 o'rniga 2 ta query bilan bajariladi.
        """
        qs = StudentEmbedding.objects.filter(is_active=True)

        if organization_id is not None:
            qs = qs.filter(student__organization__organization_id=organization_id)

        qs.update(is_primary=False)

        primary_ids = list(
            qs
            .order_by("student_id", F("quality_score").desc(nulls_last=True), "id")
            .distinct("student_id")
            .values_list("id", flat=True)
        )

        if primary_ids:
            StudentEmbedding.objects.filter(id__in=primary_ids).update(is_primary=True)

        return {"students_with_primary_embedding": len(primary_ids)}


class LessonEmbeddingCache:
    """
    Dars davomida talabalar embeddinglarini RAM da saqlaydi.
    DB ga faqat dars boshida bir marta murojaat qiladi (~5-10ms),
    har kadrda matris ko'paytmasi ishlatiladi (~0.1ms).

    Hayot tsikli: schedule o'zgarganda yangidan yaratiladi,
    dars tugashi bilan `cache = None` → GC tozalaydi → 0 KB.
    """

    def __init__(self, schedule):
        self._schedule = schedule
        self._matrix: np.ndarray | None = None     # (N, 512) float32, L2-normalized
        self._idx_to_student_id: list[int] = []    # matrix satri → student_id
        self._student_info: dict[int, dict] = {}   # student_id → {pinfl, full_name, organization_id}
        self._load()

    def _load(self):
        from django.db.models import F

        rows = list(
            StudentEmbedding.objects
            .filter(is_active=True, student__class_obj=self._schedule.class_obj)
            .values(
                "student_id",
                "embedding",
                student_pinfl=F("student__pinfl"),
                student_full_name=F("student__full_name"),
                org_id=F("student__organization__organization_id"),
            )
        )

        if not rows:
            self._matrix = np.empty((0, 512), dtype=np.float32)
            return

        vecs = []
        for row in rows:
            sid = row["student_id"]
            vecs.append(np.asarray(row["embedding"], dtype=np.float32))
            if sid not in self._student_info:
                self._student_info[sid] = {
                    "pinfl": row["student_pinfl"],
                    "full_name": row["student_full_name"],
                    "organization_id": row["org_id"],
                }
            self._idx_to_student_id.append(sid)

        mat = np.stack(vecs, axis=0)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._matrix = (mat / norms).astype(np.float32)

    @property
    def size(self) -> int:
        return len(self._idx_to_student_id)

    def decide_match(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        accept_threshold: float = 0.70,
        review_threshold: float = 0.55,
    ) -> dict:
        """
        RAM da matris @ vektor bilan cosine o'xshashlik hisoblaydi.
        Natija formati RecognitionSearchService.decide_match_by_embedding() bilan mos.
        """
        if self._matrix is None or self._matrix.shape[0] == 0:
            return {
                "decision": "rejected",
                "reason": "no_candidates",
                "best_match": None,
                "top_candidates": [],
            }

        q = query_embedding.astype(np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm > 0:
            q = q / q_norm

        scores = self._matrix @ q                        # (N,) — DB ga tegmaydi

        best_per_student: dict[int, float] = {}
        for idx, s in enumerate(scores.tolist()):
            sid = self._idx_to_student_id[idx]
            if sid not in best_per_student or s > best_per_student[sid]:
                best_per_student[sid] = s

        candidates = []
        for sid, score in best_per_student.items():
            info = self._student_info[sid]
            candidates.append({
                "student_id": sid,
                "pinfl": info["pinfl"],
                "full_name": info["full_name"],
                "organization_id": info["organization_id"],
                "best_score": round(float(score), 6),
            })

        candidates.sort(key=lambda x: x["best_score"], reverse=True)
        top = candidates[:top_k]

        if not top:
            return {
                "decision": "rejected",
                "reason": "no_candidates",
                "best_match": None,
                "top_candidates": [],
            }

        best = top[0]
        score = best["best_score"]
        if score >= accept_threshold:
            decision = "accepted"
        elif score >= review_threshold:
            decision = "review"
        else:
            decision = "rejected"

        return {
            "decision": decision,
            "accept_threshold": accept_threshold,
            "review_threshold": review_threshold,
            "best_match": {**best, "effective_score": score},
            "top_candidates": top,
        }


class RecognitionSearchService:

    def decide_match_by_embedding(
            self,
            query_embedding: np.ndarray,
            organization_id: int | None = None,
            top_k: int = 5,
            exclude_embedding_ids: list[int] | None = None,
            exclude_student_id: int | None = None,
            accept_threshold: float = 0.70,
            review_threshold: float = 0.55,
            primary_only: bool = False,
    ):
        result = self.search_by_embedding(
            query_embedding=query_embedding,
            organization_id=organization_id,
            top_k=top_k,
            exclude_embedding_ids=exclude_embedding_ids,
            exclude_student_id=exclude_student_id,
            primary_only=primary_only,
        )

        rows = result["results"]
        if not rows:
            return {
                "organization_id": organization_id,
                "decision": "rejected",
                "reason": "no_candidates",
                "best_match": None,
                "top_candidates": [],
            }

        best = rows[0]
        # Live kamera uchun best_score ishlatiladi — kamera muayyan burchakni ko'rsatadi,
        # shu burchakdagi eng mos embedding etarli. top3_avg boshqa burchak embeddinglarini
        # ham kiritib natijani pasaytiradi.
        effective_score = best["best_score"]

        if effective_score >= accept_threshold:
            decision = "accepted"
        elif effective_score >= review_threshold:
            decision = "review"
        else:
            decision = "rejected"

        best = dict(best)
        best["effective_score"] = round(effective_score, 6)

        return {
            "organization_id": organization_id,
            "decision": decision,
            "accept_threshold": accept_threshold,
            "review_threshold": review_threshold,
            "best_match": best,
            "top_candidates": rows,
        }

    def search_by_embedding(
            self,
            query_embedding: np.ndarray,
            organization_id: int | None = None,
            top_k: int = 5,
            exclude_embedding_ids: list[int] | None = None,
            exclude_student_id: int | None = None,
            primary_only: bool = False,
    ):
        q = query_embedding.tolist() if isinstance(query_embedding, np.ndarray) else query_embedding

        base_filter = {"is_active": True}
        if primary_only:
            base_filter["is_primary"] = True

        qs = StudentEmbedding.objects.select_related(
            "student",
            "student__organization",
            "enrollment_photo",
            "enrollment_photo__external_photo",
        ).filter(**base_filter).annotate(
            distance=CosineDistance("embedding", q)
        ).order_by("distance")

        if organization_id is not None:
            qs = qs.filter(student__organization__organization_id=organization_id)

        if exclude_embedding_ids:
            qs = qs.exclude(id__in=exclude_embedding_ids)

        if exclude_student_id is not None:
            qs = qs.exclude(student_id=exclude_student_id)

        student_best = {}
        student_all_scores = defaultdict(list)

        for row in qs[:_PGVECTOR_FETCH_LIMIT]:
            score = 1.0 - float(row.distance)
            student_id = row.student_id
            student_all_scores[student_id].append(score)

            current = student_best.get(student_id)
            if current is None or score > current["best_score"]:
                student_best[student_id] = {
                    "student_id": row.student_id,
                    "pinfl": row.student.pinfl,
                    "full_name": row.student.full_name,
                    "organization_id": row.student.organization.organization_id,
                    "best_score": score,
                    "photo_type": row.enrollment_photo.external_photo.photo_type,
                    "embedding_id": row.id,
                }

        results = []
        for student_id, data in student_best.items():
            scores = sorted(student_all_scores[student_id], reverse=True)
            data["score_count"] = len(scores)
            data["top3_avg_score"] = round(sum(scores[:3]) / min(len(scores), 3), 6)
            data["best_score"] = round(data["best_score"], 6)
            results.append(data)

        results.sort(key=lambda x: x["best_score"], reverse=True)

        return {
            "organization_id": organization_id,
            "top_k": top_k,
            "results": results[:top_k],
        }

    def _read_image(self, image_path: str):
        if not image_path or not os.path.exists(image_path):
            raise ValueError(f"Image not found: {image_path}")

        img = cv2.imread(image_path)
        if img is None:
            raise ValueError("cv2.imread failed")
        return img

    def _extract_embedding(self, image_path: str):
        img = self._read_image(image_path)
        faces = detect_faces(img)

        if len(faces) == 0:
            raise ValueError("No face detected in query image")
        if len(faces) > 1:
            raise ValueError(f"Multiple faces detected in query image: {len(faces)}")

        emb = faces[0].embedding
        if emb is None:
            raise ValueError("Embedding is None for query image")

        return emb.astype(np.float32)

    def search(
            self,
            image_path: str,
            organization_id: int | None = None,
            top_k: int = 5,
            exclude_embedding_ids: list[int] | None = None,
            exclude_student_id: int | None = None,
            primary_only: bool = False,
    ):
        query_embedding = self._extract_embedding(image_path)
        result = self.search_by_embedding(
            query_embedding=query_embedding,
            organization_id=organization_id,
            top_k=top_k,
            exclude_embedding_ids=exclude_embedding_ids,
            exclude_student_id=exclude_student_id,
            primary_only=primary_only,
        )
        return {"query_image": image_path, **result}

    def decide_match(
        self,
        image_path: str,
        organization_id: int | None = None,
        top_k: int = 5,
        exclude_embedding_ids: list[int] | None = None,
        exclude_student_id: int | None = None,
        accept_threshold: float = 0.70,
        review_threshold: float = 0.55,
        primary_only: bool = False,
    ):
        query_embedding = self._extract_embedding(image_path)
        result = self.decide_match_by_embedding(
            query_embedding=query_embedding,
            organization_id=organization_id,
            top_k=top_k,
            exclude_embedding_ids=exclude_embedding_ids,
            exclude_student_id=exclude_student_id,
            accept_threshold=accept_threshold,
            review_threshold=review_threshold,
            primary_only=primary_only,
        )
        return {"query_image": image_path, **result}
