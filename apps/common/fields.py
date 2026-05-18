import base64
import hashlib

from django.db import models


def _get_fernet():
    from cryptography.fernet import Fernet
    from django.conf import settings
    raw = settings.SECRET_KEY.encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
    return Fernet(key)


class EncryptedTextField(models.TextField):
    """
    DB da shifrlangan holda saqlaydi, o'qiganda avtomatik ochadi.
    Mavjud plain-text qiymatlar saqlaganda avtomatik shifrlanadie
    (backward compatibility: "enc:" prefiksi bo'lmagan qiymatlar ochilgan holda qaytariladi).
    """
    _PREFIX = "enc:"

    def from_db_value(self, value, expression, connection):
        if not value or not value.startswith(self._PREFIX):
            return value
        try:
            return _get_fernet().decrypt(value[len(self._PREFIX):].encode()).decode()
        except Exception:
            return value

    def to_python(self, value):
        if not value or not isinstance(value, str) or not value.startswith(self._PREFIX):
            return value
        try:
            return _get_fernet().decrypt(value[len(self._PREFIX):].encode()).decode()
        except Exception:
            return value

    def get_prep_value(self, value):
        if not value or value.startswith(self._PREFIX):
            return value
        try:
            return self._PREFIX + _get_fernet().encrypt(value.encode()).decode()
        except Exception:
            return value
