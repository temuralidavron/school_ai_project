from django.contrib import admin

from apps.integrations.models import (
    ExternalOrganization, ExternalClass, ExternalClassroom,
    ExternalStudent, ExternalStudentPhoto, ExternalSchedule,
)


@admin.register(ExternalOrganization)
class ExternalOrganizationAdmin(admin.ModelAdmin):
    list_display = ("id", "organization_id", "organization_name", "organization_inn")
    search_fields = ("organization_name", "organization_inn")


@admin.register(ExternalClass)
class ExternalClassAdmin(admin.ModelAdmin):
    list_display = ("id", "class_id", "class_name", "class_degree", "organization")
    list_filter = ("organization", "class_degree")
    search_fields = ("class_name",)


@admin.register(ExternalClassroom)
class ExternalClassroomAdmin(admin.ModelAdmin):
    list_display = ("id", "class_room_id", "class_room_name", "organization", "camera", "device_id")
    list_filter = ("organization",)
    search_fields = ("class_room_name", "device_id")


@admin.register(ExternalStudent)
class ExternalStudentAdmin(admin.ModelAdmin):
    list_display = ("id", "pinfl", "full_name", "organization", "class_obj")
    list_filter = ("organization", "class_obj")
    search_fields = ("pinfl", "full_name")


@admin.register(ExternalStudentPhoto)
class ExternalStudentPhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "photo_type", "photo_guid")
    list_filter = ("photo_type",)
    search_fields = ("student__pinfl", "student__full_name")


@admin.register(ExternalSchedule)
class ExternalScheduleAdmin(admin.ModelAdmin):
    list_display = ("id", "organization", "class_obj", "classroom",
                    "lesson_number", "date", "start_at", "end_at")
    list_filter = ("organization", "date", "classroom")
    search_fields = ("class_obj__class_name",)
    date_hierarchy = "date"
    ordering = ("-date", "lesson_number")
