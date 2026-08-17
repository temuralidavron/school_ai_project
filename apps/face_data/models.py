from django.db import models
from pgvector.django import HnswIndex, VectorField
from apps.common.models import BaseModel



class EnrollmentPhoto(BaseModel):
    STATUS_PENDING = "pending"
    STATUS_VALID = "valid"
    STATUS_NO_FACE = "no_face"
    STATUS_MULTI_FACE = "multi_face"
    STATUS_BLURRY = "blurry"
    STATUS_TOO_SMALL = "too_small"
    STATUS_FAILED = "failed"
    STATUS_EMBEDDED = "embedded"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_VALID, "Valid"),
        (STATUS_NO_FACE, "No face"),
        (STATUS_MULTI_FACE, "Multiple faces"),
        (STATUS_BLURRY, "Blurry"),
        (STATUS_TOO_SMALL, "Too small"),
        (STATUS_FAILED, "Failed"),
        (STATUS_EMBEDDED, "Embedded"),
    )

    external_photo = models.OneToOneField(
        "integrations.ExternalStudentPhoto",
        on_delete=models.CASCADE,
        related_name="enrollment_record",
    )
    student = models.ForeignKey(
        "integrations.ExternalStudent",
        on_delete=models.CASCADE,
        related_name="enrollment_photos",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    face_count = models.IntegerField(default=0)
    blur_score = models.FloatField(null=True, blank=True)
    face_width = models.IntegerField(null=True, blank=True)
    face_height = models.IntegerField(null=True, blank=True)
    quality_score = models.FloatField(null=True, blank=True)
    failure_reason = models.TextField(null=True, blank=True)
    aligned_image = models.ImageField(upload_to="enrollment/aligned/", null=True, blank=True)

    class Meta:
        db_table = "enrollment_photos"

    def __str__(self):
        return f"{self.student.pinfl} - {self.external_photo.photo_type} - {self.status}"


class StudentEmbedding(BaseModel):
    MODEL_ARCFACE = "arcface"
    MODEL_CUSTOM = "custom"

    MODEL_CHOICES = (
        (MODEL_ARCFACE, "ArcFace"),
        (MODEL_CUSTOM, "Custom"),
    )

    SOURCE_ENROLLMENT = "enrollment"
    SOURCE_CAMERA = "camera"

    SOURCE_CHOICES = (
        (SOURCE_ENROLLMENT, "Enrollment"),
        (SOURCE_CAMERA, "Camera"),
    )

    student = models.ForeignKey(
        "integrations.ExternalStudent",
        on_delete=models.CASCADE,
        related_name="student_embeddings",
    )
    enrollment_photo = models.ForeignKey(
        EnrollmentPhoto,
        on_delete=models.CASCADE,
        related_name="embeddings",
        null=True,
        blank=True,
    )
    model_name = models.CharField(max_length=32, choices=MODEL_CHOICES, default=MODEL_ARCFACE)
    model_version = models.CharField(max_length=64, blank=True, default="")
    embedding = VectorField(dimensions=512)
    embedding_dim = models.IntegerField(default=512)
    is_primary = models.BooleanField(default=False)
    quality_score = models.FloatField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    source = models.CharField(
        max_length=16, choices=SOURCE_CHOICES, default=SOURCE_ENROLLMENT)
    source_meta = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "student_embeddings"
        indexes = [
            models.Index(fields=["is_active"], name="se_is_active_idx"),
            models.Index(fields=["student_id", "is_active"], name="se_student_active_idx"),
            HnswIndex(
                fields=["embedding"],
                name="se_emb_hnsw_cosine_idx",
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self):
        return f"{self.student.pinfl} - {self.model_name}"