# school_attendace_v1 — Claude uchun kontekst

Sen Claude'sing. Foydalanuvchi — **Aliyer Temur**, CV/Python/Django muhandisi. Til: O'zbek (Latin), straight apostrof (`'`), emoji ishlatma kod ichida.

Loyiha tafsilotlari uchun: [LOYIHA.md](LOYIHA.md).

## Loyiha

**225-maktab AI davomat tizimi** (org_id=16). 325 talaba, 10 PTZ kamera, edu.devel.uz ga SKUD push.

Stack: Django 5 + DRF · PostgreSQL 16 + pgvector · MinIO · InsightFace `buffalo_l` (CUDA 12.6, RTX 5080) · Docker compose · Ubuntu 24.04 host (10.144.4.249).

## Asosiy modullar

```
apps/
├── academics/        Talabalar, sinflar
├── attendance/       Davomat pipeline, lock, tracking
├── cameras/          Kamera oqimi, PTZ
│   └── management/commands/
│       ├── run_camera_stream.py   eski oqim (OpenCV + InsightFace)
│       └── kafka_consumer.py      YANGI: DeepStream xabarlarini qabul qilish
├── face_data/        AI model, LessonEmbeddingCache (RAM)
├── integrations/     SKUD HTTP klient (edu.devel.uz)
└── monitoring/
```

Asosiy klasslar va fayllar:
- `apps/attendance/services.py`: `LiveFrameProcessorService`, `RecognitionEventService`, `FaceTrackService`, `AttendanceLockService`
- `apps/face_data/services.py`: `LessonEmbeddingCache`, `get_face_app()`
- `apps/cameras/services.py`: `CameraStreamService` (eski OpenCV oqim)
- `apps/integrations/services.py`: `SkudAttendancePushService`

## DeepStream integratsiya (YANGI)

DeepStream — mavjud davomat pipeline'ga **qo'shimcha**. Faqat yuz topishni tezlashtiradi. Recognition/lock/DB/SKUD push — barchasi mavjud kodda.

```
Video/RTSP → DeepStream pipeline → Kafka → kafka_consumer command
                                              ↓
                                       MAVJUD RecognitionEventService
                                       MAVJUD AttendanceLockService
                                       MAVJUD SkudClient
                                              ↓
                                       PostgreSQL + SKUD
```

Joylashuvi:
```
deepstream/
├── pipeline/
│   ├── main.py           DeepStream + Kafka producer
│   ├── Dockerfile        DeepStream 7.1 image
│   └── requirements.txt
├── configs/              pgie, tracker, labels
├── data/                 video (sinf.mp4)
├── models/               TRT engine fayllar
└── QO_LLANMA.txt
```

Django consumer: [apps/cameras/management/commands/kafka_consumer.py](apps/cameras/management/commands/kafka_consumer.py)

Ishga tushirish (Ubuntu):
```bash
# Video qo'yish
cp /path/to/video.mp4 deepstream/data/sinf.mp4

# Camera ID
echo "DEEPSTREAM_CAMERA_ID=1" >> .env

# Hammasini boshlash (eski + yangi profil)
docker compose --profile deepstream up -d

# Loglar
docker compose logs -f deepstream         # pipeline
docker compose logs -f kafka_consumer     # davomat real-time

# Kafka UI
# http://localhost:8080
```

## Eski vs yangi rejim

```bash
# Eski (cameras stream — OpenCV + InsightFace)
docker compose up -d

# Yangi (DeepStream qo'shilgan, eski ham ishlaydi)
docker compose --profile deepstream up -d
```

DeepStream service'lar `profiles: ["deepstream"]` bilan opt-in — default ishga tushmaydi.

## Bosqichlar (rivojlanish)

**Phase 1 — TAYYOR (hozir):**
- DeepStream face detection (FaceNet)
- Face crop Kafka'ga base64 JPG
- Django `kafka_consumer` buffalo_l ishlatadi
- MAVJUD RecognitionEventService chaqiriladi

**Phase 2 — keyingi (1-2 kun):**
- `w600k_r50.onnx` (buffalo_l ichidagi recognition) → TensorRT engine
- DeepStream SGIE sifatida qo'shish
- Embedding to'g'ridan-to'g'ri Kafka'ga (face crop emas)

**Phase 3 — production (1+ oy):**
- 10 ta RTSP source bitta DeepStream'da (nvstreammux batch)
- Multi-worker Kafka consumer
- Eski `CameraStreamService` o'rniga DeepStream

## Sozlamalar (.env)

```bash
AI_GPU_ID=0
AI_DET_SIZE=1280
AI_FRAME_MAX_DIM=1280
AI_ACCEPT_THRESHOLD=0.55
AI_REVIEW_THRESHOLD=0.42
AI_FRAME_INTERVAL=1.0
AI_UPSCALE_SMALL_FACES=False    # det_size>=1280 da — kerak emas

# DeepStream (opt-in)
DEEPSTREAM_CAMERA_ID=1
KAFKA_BOOTSTRAP=kafka:9092
KAFKA_TOPIC=deepstream-faces
KAFKA_GROUP_ID=attendance-consumer
```

## Foydalanuvchi afzalliklari

- Til: O'zbek (Latin), straight apostrof (`'`)
- Kod: kommentariy past — faqat WHY (non-obvious), WHAT emas
- Logs: ingliz tilida
- Emoji: chat'da OK, kod ichida yo'q
- Git: hech qachon commit/push qilma — foydalanuvchi o'zi
- Mavjud kodga tegma — yangi qo'shish kerak bo'lsa alohida fayl/papka
- Read first, write second — har doim mavjud kodni o'qib chiqib keyin yoz

## Tez-tez chiqadigan savollar

- "DeepStream'ga buffalo_l qo'shamizmi?" — TRT konversiya + custom parser kerak (2-5 kun ish). Phase 2'da rejalashtirilgan
- "Mavjud DRF oqimga ta'sir qiladimi?" — Yo'q. DeepStream `--profile` orqali opt-in, alohida service
- "10 ta kamera DeepStream'da?" — Phase 3. Hozir bitta video bilan POC
- "Kafka kerak ekanmi?" — Ha, DeepStream (C++) va Django (Python) o'rtasida xavfsiz va backpressure-tolerant bog'lanish

## Bog'liq fayllar

- [DAVOM.md](DAVOM.md) — **ENG YANGI (2026-08-25): bir buyruq start.sh, threshold, RTSP holati, ertangi 10-V test. BIRINCHI SHUNI O'QI**
- [JAMI_3.md](JAMI_3.md) — avgust-2026 holat: 225-maktab serveriga deploy, 6 ta topilgan bug, jonli dars sinovi
- [deploy/SINOV_QOLLANMA.md](deploy/SINOV_QOLLANMA.md) — maktabda jonli dars sinovi: tayyorgarlik, sinf/kamera tanlash, ishga tushirish, natijalar
- [JAMI_2.md](JAMI_2.md) — iyul-2026 holati: 1280 detection, B5 margin, realtime, F0-F5 reja (bu CLAUDE.md ning ba'zi qismlari eskirgan)
- [LOYIHA.md](LOYIHA.md) — to'liq loyiha tafsilotlari
- [deepstream/QO_LLANMA.txt](deepstream/QO_LLANMA.txt) — DeepStream qo'llanmasi
- [docker-compose.yml](docker-compose.yml) — barcha service'lar (eski + yangi)
- [.env](.env) — sozlamalar (gitignore — `.env.example` shablon sifatida)
