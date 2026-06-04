from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── Security ─────────────────────────────────────────────────────────────────
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1,localhost', cast=Csv())

# ─── Applications ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.postgres',
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "pgvector.django",
    "apps.common.apps.CommonConfig",
    "apps.academics.apps.AcademicsConfig",
    "apps.cameras.apps.CamerasConfig",
    "apps.attendance.apps.AttendanceConfig",
    "apps.face_data.apps.FaceDataConfig",
    "apps.integrations.apps.IntegrationsConfig",
    "apps.monitoring.apps.MonitoringConfig",
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ─── Database ─────────────────────────────────────────────────────────────────
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config('DB_NAME', default='school_ai'),
        "USER": config('DB_USER', default='postgres'),
        "PASSWORD": config('DB_PASSWORD'),
        "HOST": config('DB_HOST', default='127.0.0.1'),
        "PORT": config('DB_PORT', default='5432'),
    }
}

# ─── Password validation ───────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ─── Internationalization ──────────────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

# ─── Static / Media ───────────────────────────────────────────────────────────
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ─── Django REST Framework ────────────────────────────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.LimitOffsetPagination',
    'PAGE_SIZE': 50,
}

# ─── CORS ─────────────────────────────────────────────────────────────────────
_cors_origins = config('CORS_ALLOWED_ORIGINS', default='', cast=Csv())
CORS_ALLOWED_ORIGINS = [o for o in _cors_origins if o]
CORS_ALLOW_CREDENTIALS = True

# ─── CSRF (admin/IP orqali kirish uchun) ──────────────────────────────────────
# .env da CSRF_TRUSTED_ORIGINS bo'lsa o'sha; bo'lmasa ALLOWED_HOSTS dan
# avtomatik http://<host>:8000 hosil qilinadi (admin login ishlashi uchun).
_csrf_env = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())
CSRF_TRUSTED_ORIGINS = [o for o in _csrf_env if o]
if not CSRF_TRUSTED_ORIGINS:
    for _h in ALLOWED_HOSTS:
        if _h and _h not in ("*",):
            CSRF_TRUSTED_ORIGINS.append(f"http://{_h}:8000")
            CSRF_TRUSTED_ORIGINS.append(f"https://{_h}")

# ─── SKUD API ─────────────────────────────────────────────────────────────────
SKUD_API_BASE_URL   = config('SKUD_API_BASE_URL',   default='https://edu.devel.uz')
SKUD_CLIENT_ID      = config('SKUD_CLIENT_ID',      default='faceid')
SKUD_CLIENT_SECRET  = config('SKUD_CLIENT_SECRET',  default='')
SKUD_ACCESS_TOKEN   = config('SKUD_ACCESS_TOKEN',   default='')

# ─── Telegram bot (davomat hisoboti — ALOHIDA konteyner, read-only) ────────────
# Bot davomat pipeline'ga tegmaydi: GPU yo'q, faqat DB read + BotSentReport write.
TELEGRAM_BOT_TOKEN     = config('TELEGRAM_BOT_TOKEN',     default='')
TELEGRAM_ADMIN_CHAT_ID = config('TELEGRAM_ADMIN_CHAT_ID', default='')
TELEGRAM_GROUP_CHAT_ID = config('TELEGRAM_GROUP_CHAT_ID', default='')
BOT_ORG_ID             = config('BOT_ORG_ID',             default=16,   cast=int)

# ─── AI / InsightFace ─────────────────────────────────────────────────────────
# GPU ID: -1=CPU, 0=birinchi GPU (RTX 5080 / Jetson Orin)
AI_GPU_ID            = config('AI_GPU_ID',            default=-1,   cast=int)
# Det window: 640 CPU uchun, 1280 GPU uchun (8MP kamera)
AI_DET_SIZE          = config('AI_DET_SIZE',          default=640,  cast=int)
# Kadr qayta ishlash o'lchami (max_dim): 640 CPU, 1280 GPU
AI_FRAME_MAX_DIM     = config('AI_FRAME_MAX_DIM',     default=640,  cast=int)
# Tanish chegaralari
AI_ACCEPT_THRESHOLD  = config('AI_ACCEPT_THRESHOLD',  default=0.55, cast=float)
AI_REVIEW_THRESHOLD  = config('AI_REVIEW_THRESHOLD',  default=0.42, cast=float)
# Kamera stream oralig'i (soniya)
AI_FRAME_INTERVAL    = config('AI_FRAME_INTERVAL',    default=2.0,  cast=float)

# ─── AI aniqlik sozlash (kalibrlash uchun — .env'dan, kod o'zgarmaydi) ─────────
# Default'lar = hozirgi xatti-harakat (o'zgartirilmasa hech narsa o'zgarmaydi).
# Strategiya: 1-kun past threshold + review ham yozsin → ma'lumot yig'iladi →
#   keyin .env'da threshold oshiriladi, review o'chiriladi (kod tegmaydi).
# Frontal kadrlar soni: 1=bitta kadr (hozirgi), 3=3 kadr o'rtacha (aniqroq)
AI_MIN_FRONTAL_FRAMES      = config('AI_MIN_FRONTAL_FRAMES',      default=1,    cast=int)
# Poza chegaralari (gradus) — kichikroq = qattiqroq filtr (aniqroq embedding)
AI_MAX_YAW_DEG             = config('AI_MAX_YAW_DEG',             default=40.0, cast=float)
AI_MAX_PITCH_DEG           = config('AI_MAX_PITCH_DEG',           default=40.0, cast=float)
# review natija ham davomatga yozilsinmi (1-kun: True = ko'proq ushlaydi;
#   threshold oshirilgach: False = faqat aniq accepted)
AI_REVIEW_RECORDS_ATTENDANCE = config('AI_REVIEW_RECORDS_ATTENDANCE', default=False, cast=bool)
# Event rasmi base64 Postgres'ga ham yozilsinmi (False = DB bloat kamayadi,
#   rasm baribir MinIO'da). Default True = hozirgi xatti-harakat.
AI_SAVE_EVENT_BASE64       = config('AI_SAVE_EVENT_BASE64',       default=True,  cast=bool)
# SKUD push bounded pool — cheksiz thread o'rniga (sinf kirganda)
AI_SKUD_PUSH_WORKERS       = config('AI_SKUD_PUSH_WORKERS',       default=8,    cast=int)
# Track student'ga qulflanганда o'tkazib yuborilsinmi. Default True = hozirgi.
#   Patrul rejimida False tavsiya (boshqa o'quvchi bir katakda — ushlanadi)
AI_SKIP_LOCKED_TRACK       = config('AI_SKIP_LOCKED_TRACK',       default=True, cast=bool)
# Inference shu ms'dan uzoq cho'zilsa WARNING (jim sekinlashuvni ko'rsatadi)
AI_INFERENCE_WARN_MS       = config('AI_INFERENCE_WARN_MS',       default=2000, cast=int)
# Kichik yuzlarni upscale qilib qayta detect qilish. det_size>=1280 da KERAK EMAS
# (asosiy detektsiya allaqachon sifatli) — har yuz uchun qo'shimcha GPU inference
# (global lock) → sinf to'lganda 10-20x sekinlashtiradi. det=1920 da False tavsiya.
AI_UPSCALE_SMALL_FACES     = config('AI_UPSCALE_SMALL_FACES',     default=True, cast=bool)
# Inference parallellik — bir vaqtда necha thread GPU inference qila oladi.
#   1 = serial (eski xulq, eng xavfsiz). 10 kamera serial → throughput past.
#   3-4 = GPU parallel (RTX 5080) → 10 kamera tezroq ishlanadi → ko'proq kadr.
# Crash/CUDA xato bo'lsa → 1 ga qaytaring. CPU (AI_GPU_ID=-1) da 1 qoldiring.
AI_INFERENCE_CONCURRENCY   = config('AI_INFERENCE_CONCURRENCY',   default=1,    cast=int)

# ─── Kamera stream shabloni (SKUD deviceId=IP dan URL quriladi) ───────────────
# {ip} = SKUD deviceId, {user}/{password} = kamera login, {org}/{room} = SKUD id
# Misol (Hikvision): rtsp://{user}:{password}@{ip}:554/Streaming/Channels/101
# Misol (Dahua):     rtsp://{user}:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=0
# Misol (edu proxy): https://edu-api.devel.uz/cam{org}_{room}
CAMERA_STREAM_TEMPLATE = config('CAMERA_STREAM_TEMPLATE', default='')
CAMERA_USER            = config('CAMERA_USER',            default='')
CAMERA_PASSWORD        = config('CAMERA_PASSWORD',        default='')

# ─── Kamera patrul (aylanish) ─────────────────────────────────────────────────
# Global rejim: off | preset | sweep | hybrid
# Har kamera Camera.patrol_mode bilan bekor qila oladi ("default" = shu global)
PATROL_MODE                = config('PATROL_MODE',                default='off',  cast=str)
# True bo'lsa faqat aktiv dars vaqtida aylanadi (tanaffusda home preset)
PATROL_ONLY_DURING_LESSON  = config('PATROL_ONLY_DURING_LESSON',  default=True,   cast=bool)

# ─── MinIO ────────────────────────────────────────────────────────────────────
MINIO_HOST         = config('MINIO_HOST',         default='localhost')
MINIO_PORT         = config('MINIO_PORT',         default=9000, cast=int)
MINIO_ACCESS_KEY   = config('MINIO_ACCESS_KEY',   default='minioadmin')
MINIO_SECRET_KEY   = config('MINIO_SECRET_KEY',   default='minioadmin')
MINIO_BUCKET_NAME         = config('MINIO_BUCKET_NAME',         default='student-photos')
MINIO_RECOGNITION_BUCKET  = config('MINIO_RECOGNITION_BUCKET',  default='recognition-events')
MINIO_USE_SSL             = config('MINIO_USE_SSL',             default=False, cast=bool)
MINIO_ENDPOINT_URL = f"{'https' if MINIO_USE_SSL else 'http'}://{MINIO_HOST}:{MINIO_PORT}"

# ─── Logging ──────────────────────────────────────────────────────────────────
import logging.handlers  # noqa: E402
import time as _time

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)


class _LocalFormatter(logging.Formatter):
    """Loglar Toshkent vaqtida chiqishi uchun — UTC emas."""
    converter = _time.localtime


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "detailed": {
            "()": _LocalFormatter,
            "format": "[{asctime}] {levelname:<8} {name} | {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "simple": {
            "()": _LocalFormatter,
            "format": "[{asctime}] {levelname} | {message}",
            "style": "{",
            "datefmt": "%H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
            "level": "INFO",
        },
        "file_all": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "attendance.log",
            "maxBytes": 20 * 1024 * 1024,
            "backupCount": 7,
            "formatter": "detailed",
            "encoding": "utf-8",
            "level": "DEBUG",
        },
        "file_errors": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "errors.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "detailed",
            "encoding": "utf-8",
            "level": "ERROR",
        },
        "file_skud": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "skud.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 7,
            "formatter": "detailed",
            "encoding": "utf-8",
            "level": "DEBUG",
        },
    },
    "root": {
        "handlers": ["console", "file_errors"],
        "level": "WARNING",
    },
    "loggers": {
        "apps": {
            "handlers": ["console", "file_all", "file_errors"],
            "level": "DEBUG",
            "propagate": False,
        },
        # SKUD va integratsiya operatsiyalari alohida faylga
        "apps.integrations": {
            "handlers": ["console", "file_skud", "file_errors"],
            "level": "DEBUG",
            "propagate": False,
        },
        "django": {
            "handlers": ["console", "file_errors"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "file_errors"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
