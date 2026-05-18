from django.db import models
from apps.common.models import BaseModel
from apps.common.storage import MinioRecognitionStorage
class RecognitionEvent(BaseModel):
    DECISION_ACCEPTED = "accepted"
    DECISION_REVIEW = "review"
    DECISION_REJECTED = "rejected"

    DECISION_CHOICES = (
        (DECISION_ACCEPTED, "Accepted"),
        (DECISION_REVIEW, "Review"),
        (DECISION_REJECTED, "Rejected"),
    )

    student = models.ForeignKey(
        "integrations.ExternalStudent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recognition_events",
    )
    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recognition_events",
    )
    organization_id = models.BigIntegerField(null=True, blank=True)
    full_name = models.CharField(max_length=255, blank=True, default="")
    pinfl = models.CharField(max_length=32, blank=True, default="")
    recognized_at = models.DateTimeField()
    similarity = models.FloatField(null=True, blank=True)
    decision = models.CharField(max_length=16, choices=DECISION_CHOICES)
    source = models.CharField(max_length=32, default="ai")
    model_name = models.CharField(max_length=64, default="buffalo_l")
    image = models.ImageField(
        upload_to="recognition_events/",
        storage=MinioRecognitionStorage(),
        null=True,
        blank=True,
    )
    image_base64 = models.TextField(null=True, blank=True)
    meta_json = models.JSONField(null=True, blank=True)
    skud_pushed_at = models.DateTimeField(null=True, blank=True)
    skud_push_error = models.TextField(null=True, blank=True)
    # "skip:" prefiksi = qayta urinish kerak emas (student topilmadi, noto'g'ri ma'lumot)
    skud_push_attempts = models.SmallIntegerField(default=0)

    class Meta:
        db_table = "recognition_events"
        indexes = [
            models.Index(fields=["decision", "recognized_at"], name="re_decision_date_idx"),
            models.Index(fields=["organization_id", "recognized_at"], name="re_org_date_idx"),
        ]

    def __str__(self):
        return f"{self.pinfl} - {self.decision} - {self.recognized_at}"
class AttendanceLock(BaseModel):
    student = models.ForeignKey(
        "integrations.ExternalStudent",
        on_delete=models.CASCADE,
        related_name="attendance_locks",
    )
    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_locks",
    )
    organization_id = models.BigIntegerField(null=True, blank=True)
    locked_from = models.DateTimeField()
    locked_until = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    reason = models.CharField(max_length=64, default="attendance_done")

    class Meta:
        db_table = "attendance_locks"
        indexes = [
            models.Index(fields=["student_id", "is_active", "locked_until"], name="al_student_lock_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["student_id", "camera_id"],
                condition=models.Q(is_active=True),
                name="al_unique_active_lock",
            ),
        ]

    def __str__(self):
        return f"{self.student.pinfl} locked until {self.locked_until}"
class LessonAttendance(BaseModel):
    STATUS_PRESENT    = "present"
    STATUS_LATE       = "late"
    STATUS_ABSENT     = "absent"
    STATUS_WRONG_ROOM = "wrong_room"

    STATUS_CHOICES = (
        (STATUS_PRESENT,    "Keldi"),
        (STATUS_LATE,       "Kech keldi"),
        (STATUS_ABSENT,     "Kelmadi"),
        (STATUS_WRONG_ROOM, "Boshqa xona"),
    )

    schedule = models.ForeignKey(
        "integrations.ExternalSchedule",
        on_delete=models.CASCADE,
        related_name="lesson_attendances",
    )
    student = models.ForeignKey(
        "integrations.ExternalStudent",
        on_delete=models.CASCADE,
        related_name="lesson_attendances",
    )
    recognition_event = models.ForeignKey(
        "attendance.RecognitionEvent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lesson_attendances",
    )
    arrived_at = models.DateTimeField(null=True, blank=True)
    is_late    = models.BooleanField(default=False)
    status     = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ABSENT)

    class Meta:
        db_table = "lesson_attendances"
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "student"],
                name="lesson_attendance_unique",
            )
        ]
        indexes = [
            models.Index(fields=["schedule", "status"], name="la_schedule_status_idx"),
            models.Index(fields=["student", "arrived_at"], name="la_student_arrived_idx"),
        ]

    def __str__(self):
        return f"{self.student.full_name} — {self.schedule} — {self.status}"


class TrackSession(BaseModel):
    STATUS_NEW = "new"
    STATUS_TRACKING = "tracking"
    STATUS_RECOGNIZED = "recognized"
    STATUS_SKIPPED_LOCKED = "skipped_locked"
    STATUS_LOST = "lost"

    STATUS_CHOICES = (
        (STATUS_NEW, "New"),
        (STATUS_TRACKING, "Tracking"),
        (STATUS_RECOGNIZED, "Recognized"),
        (STATUS_SKIPPED_LOCKED, "Skipped locked"),
        (STATUS_LOST, "Lost"),
    )

    track_key = models.CharField(max_length=128, unique=True)
    camera = models.ForeignKey(
        "cameras.Camera",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="track_sessions",
    )
    organization_id = models.BigIntegerField(null=True, blank=True)

    student = models.ForeignKey(
        "integrations.ExternalStudent",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="track_sessions",
    )

    first_seen_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    recognized_at = models.DateTimeField(null=True, blank=True)

    best_score = models.FloatField(null=True, blank=True)
    last_score = models.FloatField(null=True, blank=True)

    frame_count = models.IntegerField(default=0)
    frontal_count = models.IntegerField(default=0)
    recognition_count = models.IntegerField(default=0)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW)
    is_active = models.BooleanField(default=True)

    bbox_x1 = models.IntegerField(null=True, blank=True)
    bbox_y1 = models.IntegerField(null=True, blank=True)
    bbox_x2 = models.IntegerField(null=True, blank=True)
    bbox_y2 = models.IntegerField(null=True, blank=True)

    meta_json = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "track_sessions"
        indexes = [
            models.Index(fields=["is_active", "last_seen_at"], name="ts_active_last_seen_idx"),
            models.Index(fields=["student_id", "is_active"],   name="ts_student_active_idx"),
            models.Index(fields=["camera_id",  "is_active"],   name="ts_camera_active_idx"),
        ]

    def __str__(self):
        return f"{self.track_key} - {self.status}"