from django.db import models
from apps.common.models import BaseModel
from apps.common.storage import MinioStudentPhotoStorage


class ExternalOrganization(BaseModel):
    organization_id = models.BigIntegerField(unique=True)
    organization_inn = models.CharField(max_length=64, blank=True, default="")
    organization_name = models.CharField(max_length=255)

    class Meta:
        db_table = "external_organizations"

    def __str__(self):
        return self.organization_name


class ExternalClass(BaseModel):
    class_id = models.BigIntegerField(unique=True)
    class_degree = models.IntegerField(null=True, blank=True)
    class_name = models.CharField(max_length=100)
    organization = models.ForeignKey(
        ExternalOrganization,
        on_delete=models.CASCADE,
        related_name="classes",
    )

    class Meta:
        db_table = "external_classes"

    def __str__(self):
        return self.class_name


class ExternalClassroom(BaseModel):
    class_room_id = models.BigIntegerField(unique=True)
    class_room_name = models.CharField(max_length=255)
    device_id = models.CharField(max_length=128, blank=True, default="")
    organization = models.ForeignKey(
        ExternalOrganization,
        on_delete=models.CASCADE,
        related_name="classrooms",
    )

    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="external_classrooms",
    )
    smart_camera = models.ForeignKey(
        "cameras.SmartCamera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="external_classrooms",
    )
    auditorium = models.ForeignKey(
        "cameras.Auditorium",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="external_classrooms",
    )

    class Meta:
        db_table = "external_classrooms"

    def __str__(self):
        return self.class_room_name


class ExternalStudent(BaseModel):
    pinfl = models.CharField(max_length=32, unique=True)
    full_name = models.CharField(max_length=255)
    organization = models.ForeignKey(
        ExternalOrganization,
        on_delete=models.CASCADE,
        related_name="students",
    )
    class_obj = models.ForeignKey(
        ExternalClass,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="students",
    )

    class Meta:
        db_table = "external_students"

    def __str__(self):
        return f"{self.full_name} ({self.pinfl})"


class ExternalStudentPhoto(BaseModel):
    PHOTO_TYPES = (
        ("front", "Front"),
        ("up", "Up"),
        ("left", "Left"),
        ("right", "Right"),
        ("bottom", "Bottom"),
    )

    student = models.ForeignKey(
        ExternalStudent,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    photo_type = models.CharField(max_length=20, choices=PHOTO_TYPES)
    photo_guid = models.CharField(max_length=100, unique=True)
    image = models.ImageField(
        upload_to="external_students/photos/",
        storage=MinioStudentPhotoStorage(),
        null=True,
        blank=True,
    )
    image_base64 = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "external_student_photos"
        constraints = [
            models.UniqueConstraint(fields=["student", "photo_type"], name="external_student_photo_type_uniq"),
        ]


class ExternalSchedule(BaseModel):
    organization = models.ForeignKey(
        ExternalOrganization,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    class_obj = models.ForeignKey(
        ExternalClass,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    classroom = models.ForeignKey(
        ExternalClassroom,
        on_delete=models.CASCADE,
        related_name="schedules",
    )
    lesson_number = models.IntegerField()
    date = models.DateField()
    timezone = models.CharField(max_length=64, default="Asia/Tashkent")
    start_at = models.TimeField()
    end_at = models.TimeField()

    class Meta:
        db_table = "external_schedules"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "class_obj", "classroom", "lesson_number", "date"],
                name="external_schedule_unique_lesson",
            )
        ]

    def __str__(self):
        return f"{self.class_obj} {self.date} #{self.lesson_number}"