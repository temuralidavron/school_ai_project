import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('attendance', '0005_add_db_indexes'),
        ('integrations', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LessonAttendance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(blank=True, null=True)),
                ('arrived_at', models.DateTimeField(blank=True, null=True)),
                ('is_late', models.BooleanField(default=False)),
                ('status', models.CharField(
                    choices=[
                        ('present',    'Keldi'),
                        ('late',       'Kech keldi'),
                        ('absent',     'Kelmadi'),
                        ('wrong_room', 'Boshqa xona'),
                    ],
                    default='absent',
                    max_length=16,
                )),
                ('schedule', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='lesson_attendances',
                    to='integrations.externalschedule',
                )),
                ('student', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='lesson_attendances',
                    to='integrations.externalstudent',
                )),
                ('recognition_event', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='lesson_attendances',
                    to='attendance.recognitionevent',
                )),
            ],
            options={
                'db_table': 'lesson_attendances',
            },
        ),
        migrations.AddConstraint(
            model_name='lessonattendance',
            constraint=models.UniqueConstraint(
                fields=['schedule', 'student'],
                name='lesson_attendance_unique',
            ),
        ),
        migrations.AddIndex(
            model_name='lessonattendance',
            index=models.Index(fields=['schedule', 'status'], name='la_schedule_status_idx'),
        ),
        migrations.AddIndex(
            model_name='lessonattendance',
            index=models.Index(fields=['student', 'arrived_at'], name='la_student_arrived_idx'),
        ),
    ]
