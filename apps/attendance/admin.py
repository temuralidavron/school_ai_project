from django.contrib import admin
from django.utils.html import format_html

from apps.attendance.models import RecognitionEvent, AttendanceLock, TrackSession


@admin.register(RecognitionEvent)
class RecognitionEventAdmin(admin.ModelAdmin):
    list_display = ("id", "full_name", "pinfl", "decision_badge", "similarity_fmt",
                    "camera", "recognized_at", "created_at")
    list_filter = ("decision", "camera", "model_name")
    search_fields = ("full_name", "pinfl")
    readonly_fields = ("recognized_at", "created_at", "updated_at",
                       "image_preview", "meta_json", "image_base64")
    date_hierarchy = "recognized_at"
    ordering = ("-recognized_at",)

    fieldsets = (
        ("Asosiy", {"fields": ("student", "camera", "organization_id",
                               "full_name", "pinfl", "decision", "similarity",
                               "recognized_at")}),
        ("Model", {"fields": ("source", "model_name")}),
        ("Rasm", {"fields": ("image", "image_preview")}),
        ("Qo'shimcha", {"fields": ("meta_json",), "classes": ("collapse",)}),
        ("Vaqtlar", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def decision_badge(self, obj):
        colors = {
            "accepted": "#28a745",
            "review": "#ffc107",
            "rejected": "#dc3545",
        }
        color = colors.get(obj.decision, "#6c757d")
        return format_html(
            '<span style="background:{};color:white;padding:2px 8px;border-radius:4px">{}</span>',
            color, obj.decision
        )
    decision_badge.short_description = "Qaror"

    def similarity_fmt(self, obj):
        if obj.similarity is None:
            return "—"
        return f"{obj.similarity:.3f}"
    similarity_fmt.short_description = "O'xshashlik"

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height:200px">', obj.image.url)
        return "—"
    image_preview.short_description = "Rasm"


@admin.register(AttendanceLock)
class AttendanceLockAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "camera", "locked_from", "locked_until", "is_active", "reason")
    list_filter = ("is_active", "reason", "camera")
    search_fields = ("student__pinfl", "student__full_name")
    ordering = ("-locked_from",)


@admin.register(TrackSession)
class TrackSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "track_key", "student", "camera", "status",
                    "frame_count", "recognition_count", "best_score_fmt",
                    "first_seen_at", "last_seen_at", "is_active")
    list_filter = ("status", "camera", "is_active")
    search_fields = ("track_key", "student__pinfl", "student__full_name")
    ordering = ("-last_seen_at",)
    readonly_fields = ("created_at", "updated_at")

    def best_score_fmt(self, obj):
        if obj.best_score is None:
            return "—"
        return f"{obj.best_score:.3f}"
    best_score_fmt.short_description = "Best score"


