from django.contrib import admin

from apps.cameras.models import (
    Building, Auditorium, Camera, CameraROI, SmartCamera,
    AuditoriumCamera, CameraPatrolPoint,
)


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at")
    search_fields = ("name",)


@admin.register(Auditorium)
class AuditoriumAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "building", "created_at")
    list_filter = ("building",)
    search_fields = ("name",)


class CameraPatrolPointInline(admin.TabularInline):
    model = CameraPatrolPoint
    extra = 1
    ordering = ("order",)


@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "stream_url", "is_active_stream",
                    "patrol_mode", "organization_id", "created_at")
    list_filter = ("is_active_stream", "patrol_mode")
    search_fields = ("name", "stream_url")
    inlines = [CameraPatrolPointInline]


@admin.register(CameraPatrolPoint)
class CameraPatrolPointAdmin(admin.ModelAdmin):
    list_display = ("id", "camera", "order", "preset_token", "label", "dwell_seconds")
    list_filter = ("camera",)
    ordering = ("camera_id", "order")


@admin.register(CameraROI)
class CameraROIAdmin(admin.ModelAdmin):
    list_display = ("id", "camera", "roi_x", "roi_y", "roi_width", "roi_height",
                    "frame_width", "frame_height", "updated_at")
    list_filter = ("camera",)


@admin.register(SmartCamera)
class SmartCameraAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at")
    search_fields = ("name",)


@admin.register(AuditoriumCamera)
class AuditoriumCameraAdmin(admin.ModelAdmin):
    list_display = ("id", "auditorium", "camera")
