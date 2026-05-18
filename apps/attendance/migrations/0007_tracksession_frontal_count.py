from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0006_lessonattendance"),
    ]

    operations = [
        migrations.AddField(
            model_name="tracksession",
            name="frontal_count",
            field=models.IntegerField(default=0),
        ),
    ]
