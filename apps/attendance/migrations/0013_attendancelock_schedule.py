"""
AttendanceLock — schedule-scoped lock.

Maqsad: har dars uchun alohida lock. 8:00-8:45 darsda yozilgan o'quvchi
9:00-9:45 darsda QAYTA yozilishi mumkin (yangi schedule_id = yangi lock).
Eski xato: (student, camera) lock 45 daq → kech kelgan o'quvchi keyingi
darsga 'absent' bo'lib qolardi.

Migratsiya tahrirlovchi emas — faqat schema o'zgaradi:
  + schedule_id FK (nullable, eski lock'lar uchun NULL qoladi)
  + al_student_sched_idx index
  − al_unique_active_lock (eski (student, camera) unique)
  + al_unique_active_schedule_lock (yangi (student, schedule) unique)
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0012_skud_push_attempts"),
        ("integrations", "0003_minio_student_photo_storage"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendancelock",
            name="schedule",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="attendance_locks",
                to="integrations.externalschedule",
            ),
        ),
        migrations.AddIndex(
            model_name="attendancelock",
            index=models.Index(
                fields=["student_id", "schedule_id", "is_active"],
                name="al_student_sched_idx",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="attendancelock",
            name="al_unique_active_lock",
        ),
        migrations.AddConstraint(
            model_name="attendancelock",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True), ("schedule_id__isnull", False)),
                fields=("student_id", "schedule_id"),
                name="al_unique_active_schedule_lock",
            ),
        ),
    ]
