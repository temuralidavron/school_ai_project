from django.db import models

from apps.common.models import BaseModel


class BotSentReport(BaseModel):
    """
    Bot yuborgan hisobotlarni belgilaydi — takror yuborilmasligi uchun.
    Bot FAQAT shu jadvalga yozadi; davomat jadvallariga (LessonAttendance...)
    umuman tegmaydi (izolyatsiya).
    """
    TYPE_LESSON = "lesson"
    TYPE_DAILY = "daily"
    TYPE_CHOICES = (
        (TYPE_LESSON, "Dars hisoboti"),
        (TYPE_DAILY, "Kunlik hisobot"),
    )

    report_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    schedule = models.ForeignKey(
        "integrations.ExternalSchedule",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="bot_reports",
    )
    report_date = models.DateField(null=True, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "bot_sent_reports"
        indexes = [
            models.Index(fields=["report_type", "report_date"], name="bsr_type_date_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["report_type", "schedule"],
                condition=models.Q(schedule__isnull=False),
                name="bsr_unique_lesson_report",
            ),
            models.UniqueConstraint(
                fields=["report_type", "report_date"],
                condition=models.Q(schedule__isnull=True),
                name="bsr_unique_daily_report",
            ),
        ]

    def __str__(self):
        return f"{self.report_type} — {self.schedule_id or self.report_date}"
