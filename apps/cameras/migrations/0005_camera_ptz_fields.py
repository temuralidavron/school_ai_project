from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cameras", "0004_encrypt_camera_passwords"),
    ]

    operations = [
        migrations.AddField(
            model_name="camera",
            name="onvif_port",
            field=models.IntegerField(default=80),
        ),
        migrations.AddField(
            model_name="camera",
            name="ptz_preset_token",
            field=models.CharField(
                blank=True,
                help_text="ONVIF preset token (davomat pozitsiyasi)",
                max_length=64,
                null=True,
            ),
        ),
    ]
