from storages.backends.s3boto3 import S3Boto3Storage


def _minio_kwargs(bucket_name: str, **extra) -> dict:
    from django.conf import settings
    return {
        "bucket_name": bucket_name,
        "endpoint_url": settings.MINIO_ENDPOINT_URL,
        "access_key": settings.MINIO_ACCESS_KEY,
        "secret_key": settings.MINIO_SECRET_KEY,
        "region_name": "us-east-1",
        "file_overwrite": False,
        "default_acl": None,
        "querystring_auth": False,
        "verify": False,
        **extra,
    }


class MinioStudentPhotoStorage(S3Boto3Storage):
    """MinIO da talaba ro'yxatga olish rasmlari (SKUD dan keladi)."""

    def __init__(self, **kwargs):
        from django.conf import settings
        super().__init__(**_minio_kwargs(settings.MINIO_BUCKET_NAME, **kwargs))


class MinioRecognitionStorage(S3Boto3Storage):
    """MinIO da yuz tanish hodisalari rasmlarini saqlash."""

    def __init__(self, **kwargs):
        from django.conf import settings
        bucket = getattr(settings, "MINIO_RECOGNITION_BUCKET", settings.MINIO_BUCKET_NAME)
        super().__init__(**_minio_kwargs(bucket, **kwargs))
