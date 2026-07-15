# Deploy — school_attendace_v1 (Docker + GPU)

To'liq Docker deploy: PostgreSQL + MinIO + Django (web) + kamera stream (cameras).
web/cameras NVIDIA GPU dan foydalanadi.

## 0. Server talablari (Ubuntu 22.04/24.04 + RTX 5080)

```bash
# NVIDIA drayver tekshirish
nvidia-smi

# Docker + Compose
curl -fsSL https://get.docker.com | sh

# NVIDIA Container Toolkit (GPU ni Docker ichida ishlatish uchun — MAJBURIY)
distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# GPU Docker ichida ishlayotganini tekshirish:
docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi
```

## 1. Loyihani ko'chiring

```bash
git clone <repo> /home/ubuntu/school_attendace_v1
cd /home/ubuntu/school_attendace_v1
```

## 2. .env sozlang

```bash
nano .env
```
Production uchun o'zgartirish kerak:
```
SECRET_KEY=<python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())">
DEBUG=False
ALLOWED_HOSTS=<server-ip>,<domen>
DB_PASSWORD=<kuchli parol>
# DB_HOST va MINIO_HOST — compose o'zi 'db'/'minio' ga o'rnatadi, tegmang
CORS_ALLOWED_ORIGINS=http://<server-ip>

# GPU — MAJBURIY yoqing (aks holda CPU da sekin):
AI_GPU_ID=0
AI_DET_SIZE=1280
AI_FRAME_MAX_DIM=1280
AI_FRAME_INTERVAL=1.0
```

## 3. Build + ishga tushirish

```bash
docker compose build           # ~10-15 daqiqa (CUDA + Python 3.14 + InsightFace)
docker compose up -d            # db, minio, minio_init, web, cameras
docker compose ps               # hammasi 'healthy/running' bo'lishi kerak
```

`web` konteyner avtomatik `migrate` + `collectstatic` qiladi.

## 4. Superuser + ma'lumot sync

```bash
docker compose exec web python3.14 manage.py createsuperuser

# SKUD dan talabalar + rasm + embedding (225-maktab = org_id 16):
docker compose exec web python3.14 manage.py sync_all_organizations --org-id 16
```

## 4b. Kamera patrul rejimini tanlash (deploy paytida)

Bitta PTZ kamera butun xonani qamrashi uchun aylanadi. `.env` da `PATROL_MODE`:

| Rejim | Qachon ishlatiladi | Sozlash |
|---|---|---|
| `off` | Kamera statik (eshikka qaratilgan) | Sozlash kerak emas |
| `sweep` | Standart xona — avtomatik chap↔o'ng | `.env` da PATROL_MODE=sweep, kerak bo'lsa admin da pan_min/pan_max |
| `preset` | Aniq burchaklar kerak | Har xona uchun qo'lda preset saqlash (pastda) |
| `hybrid` | Aralash — preset bor bo'lsa preset, yo'q bo'lsa sweep | PATROL_MODE=hybrid |

```bash
# Global tanlash:
#   .env →  PATROL_MODE=sweep
#           PATROL_ONLY_DURING_LESSON=True   # tanaffusda to'xtaydi

# Har kamera alohida (ixtiyoriy): admin → Camera → patrol_mode

# 'preset' rejimi: har xonada kamerani qo'lda burab preset saqlash
docker compose exec web python3.14 manage.py lock_cameras --camera-id 5 --list-presets
docker compose exec web python3.14 manage.py lock_cameras --camera-id 5 --save-preset --preset-name "chap"
#   → admin → CameraPatrolPoint: camera=5 order=0 preset_token=... (har nuqta uchun)

# Tekshirish (ishga tushirmasdan):
docker compose exec web python3.14 manage.py run_camera_patrol --all --dry-run
```

`patrol` konteyner avtomatik ishga tushadi (docker-compose). Faqat dars vaqtida
aylanadi (`PATROL_ONLY_DURING_LESSON=True`), tanaffusda home preset ga qaytadi.

## 5. Nginx (reverse proxy, ixtiyoriy)

```bash
# nginx.conf dagi SERVER_IP_OR_DOMAIN ni o'zgartiring
sudo cp deploy/nginx.conf /etc/nginx/sites-available/school_attendance
sudo ln -s /etc/nginx/sites-available/school_attendance /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```
web konteyner `127.0.0.1:8000` da → nginx shu portga proxy qiladi.

## Foydali buyruqlar

```bash
# Loglar
docker compose logs -f web
docker compose logs -f cameras
tail -f logs/attendance.log logs/skud.log

# Kamera streamni qayta ishga tushirish
docker compose restart cameras

# SKUD push xatolarini qayta yuborish
docker compose exec web python3.14 manage.py retry_skud_push --org-id 16 --limit 100

# Embedding holati
docker compose exec web python3.14 manage.py attendance_stats

# Kod yangilangach
git pull && docker compose build web && docker compose up -d web cameras
```

## Eslatma — kamera tarmog'i

`cameras` konteyner RTSP orqali kameralarga ulanadi (outbound). Agar kameralar
boshqa VLAN/subnetda bo'lsa va bridge tarmoq yetmasa, `cameras` servisiga
`network_mode: host` qo'shing (compose da) — u holda GPU bilan birga ishlaydi.

---

## DeepStream jonli deploy (F1, 2026-07)

Pipeline endi jonli kameralar bilan ishlaydi (HLS/RTSP), fayl rejimi dev/A-B uchun qoladi.

```bash
# 1. Kameralardan sources.json yaratish (yagona haqiqat manbasi — Camera.stream_url)
docker exec school_ai_web python3.14 manage.py export_ds_sources \
    --out /app/deepstream_data/../deepstream_v3/configs/sources.json   # yoki hostda

# 2. Jonli pipeline'ni ko'tarish
docker compose --profile deepstream up -d ds3

# 3. Tekshirish
docker logs -f school_ai_ds3            # "source N ulandi" + frame oqimi
curl -I http://localhost:8554/mjpeg/0   # jonli AI ko'rinish
docker inspect --format='{{.State.Health.Status}}' school_ai_ds3   # healthy
```

Chidamlilik: RTSP qisqa uzilish — nvurisrcbin o'zi tiklaydi; bitta kamera xatosi
boshqalarini to'xtatmaydi; kadr 60s to'xtasa healthcheck -> avto-restart.
Sinov uchun bitta kamera: `--camera-id N` bilan export yoki pipeline'ga
to'g'ridan `--uri "N=https://..."`.
