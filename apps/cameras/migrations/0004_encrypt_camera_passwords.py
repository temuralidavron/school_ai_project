from django.db import migrations
import apps.common.fields


def encrypt_existing_passwords(apps, schema_editor):
    """Mavjud plain-text parollarni shifrlaydi."""
    Camera = apps.get_model("cameras", "Camera")
    SmartCamera = apps.get_model("cameras", "SmartCamera")

    from apps.common.fields import _get_fernet
    fernet = _get_fernet()
    prefix = "enc:"

    def _encrypt(value):
        if not value or value.startswith(prefix):
            return value
        return prefix + fernet.encrypt(value.encode()).decode()

    for cam in Camera.objects.all():
        changed = False
        if cam.username and not cam.username.startswith(prefix):
            cam.username = _encrypt(cam.username)
            changed = True
        if cam.password and not cam.password.startswith(prefix):
            cam.password = _encrypt(cam.password)
            changed = True
        if changed:
            cam.save(update_fields=["username", "password"])

    for sc in SmartCamera.objects.all():
        changed = False
        if sc.login and not sc.login.startswith(prefix):
            sc.login = _encrypt(sc.login)
            changed = True
        if sc.password and not sc.password.startswith(prefix):
            sc.password = _encrypt(sc.password)
            changed = True
        if changed:
            sc.save(update_fields=["login", "password"])


class Migration(migrations.Migration):

    dependencies = [
        ("cameras", "0003_add_indexes_and_constraints"),
    ]

    operations = [
        migrations.AlterField(
            model_name="camera",
            name="username",
            field=apps.common.fields.EncryptedTextField(),
        ),
        migrations.AlterField(
            model_name="camera",
            name="password",
            field=apps.common.fields.EncryptedTextField(),
        ),
        migrations.AlterField(
            model_name="smartcamera",
            name="login",
            field=apps.common.fields.EncryptedTextField(),
        ),
        migrations.AlterField(
            model_name="smartcamera",
            name="password",
            field=apps.common.fields.EncryptedTextField(),
        ),
        migrations.RunPython(
            encrypt_existing_passwords,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
