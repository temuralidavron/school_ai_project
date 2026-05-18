from django.contrib import admin

from apps.face_data.models import EnrollmentPhoto, StudentEmbedding


@admin.register(EnrollmentPhoto)
class EnrollmentPhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "status", "face_count", "blur_score",
                    "face_width", "face_height", "quality_score")
    list_filter = ("status",)
    search_fields = ("student__pinfl", "student__full_name")
    ordering = ("status", "-created_at")


@admin.register(StudentEmbedding)
class StudentEmbeddingAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "model_name", "model_version",
                    "embedding_dim", "is_primary", "is_active", "quality_score", "created_at")
    list_filter = ("model_name", "is_primary", "is_active")
    search_fields = ("student__pinfl", "student__full_name")
    ordering = ("-created_at",)
