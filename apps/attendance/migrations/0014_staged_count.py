"""
StagedCount — B5 bosqichli tasdiqlash hisoblagichi (F2b).

(dars, bola) bo'yicha sifatli review-ko'rinishlar soni. Multi-worker
consumer'ga tayyor bo'lishi uchun RAM emas, DB'da saqlanadi.
"""
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0013_attendancelock_schedule"),
        ("integrations", "0003_minio_student_photo_storage"),
    ]

    operations = [
        migrations.CreateModel(
            name="StagedCount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("count", models.SmallIntegerField(default=0)),
                ("best_score", models.FloatField(default=0.0)),
                ("best_margin", models.FloatField(default=0.0)),
                ("schedule", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="staged_counts",
                    to="integrations.externalschedule")),
                ("student", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="staged_counts",
                    to="integrations.externalstudent")),
            ],
            options={"db_table": "staged_counts"},
        ),
        migrations.AddConstraint(
            model_name="stagedcount",
            constraint=models.UniqueConstraint(
                fields=("schedule", "student"), name="staged_count_unique"),
        ),
    ]
