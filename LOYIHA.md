# Maktab Davomati Tizimi — Loyiha Tahlili

## Nima qiladi?

Kameralar orqali real vaqtda o'quvchilarning yuzini tanib, dars davomatini avtomatik yozadi.
Tashqi SKUD tizimi bilan sinxronlanadi: talabalar, dars jadvallari va xona ma'lumotlari SKUD API dan keladi,
davomat natijasi esa qaytib SKUD ga yuboriladi.

---

## Texnologiyalar

| Qatlam | Texnologiya |
|---|---|
| Backend framework | Django 6.0.4 |
| Ma'lumotlar bazasi | PostgreSQL + `pgvector` extension |
| Yuz tanish modeli | InsightFace `buffalo_l` (ArcFace, 512-dim embedding) |
| Rasm ishlash | OpenCV (cv2) |
| Vector qidiruv indeks | HNSW (cosine similarity) |
| Tashqi integratsiya | SKUD API (REST, JWT token) |
| API | Django REST Framework |

---

## Umumiy Arxitektura

```
SKUD API
   │
   ▼
[integrations app]          [cameras app]
 ExternalOrganization        Camera (RTSP/HLS stream)
 ExternalClass               CameraROI (diqqat maydoni)
 ExternalClassroom ──────────► Camera (bog'lanish)
 ExternalStudent
 ExternalStudentPhoto
 ExternalSchedule
   │
   ▼
[face_data app]
 EnrollmentPhoto  ─►  sifat tekshiruvi (blur, o'lcham, yuz soni)
 StudentEmbedding ─►  512-dim ArcFace vector (pgvector HNSW indeksida)
   │
   ▼
[Kamera stream — har 2 soniyada 1 kadr]
   │
   ▼
LiveFrameProcessorService
   1. ROI qirqish (60s cache)
   2. InsightFace: yuz topish
   3. O'lcham tekshiruvi (< 30px o'tkazib yuborish)
   4. Poza tekshiruvi (yaw ≤ 40°, pitch ≤ 40°)
   5. Loyqalik tekshiruvi (Laplacian dispersiyasi ≥ 40)
   6. Upscale (< 160px yuzlar uchun)
   7. Frontal frame yig'ish (_FRONTAL_STORE)
   8. O'rtacha embedding (N ta frontal kadr)
   │
   ▼
RecognitionSearchService (pgvector cosine similarity)
   ├── similarity ≥ 0.70  →  accepted  (davomat yoziladi)
   ├── similarity ≥ 0.55  →  review    (ko'rib chiqish kerak)
   └── similarity < 0.55  →  rejected
   │
   ▼
[attendance app]
 RecognitionEvent  ─►  har bir tanish urinishi yoziladi
 AttendanceLock    ─►  45 daqiqa davomida takroriy yozishni bloklaydi
 LessonAttendance  ─►  talaba + dars juftligi uchun yakuniy holat
 TrackSession      ─►  yuz tracking sessiyasi (camera frame bo'yicha)
   │
   ▼
SKUD API ga davomat push qilinadi
```

---

## Dastur Qismlari (Apps)

### `apps/common`
- `BaseModel` — barcha modellar uchun `created_at`, `updated_at`
- `User`, `Role`, `Permission` — tizim foydalanuvchilari va RBAC huquq tizimi

### `apps/academics`
- HEMIS tizimidan sinxronlangan: talabalar, o'qituvchilar, guruhlar, fanlar, jadvallar
- `Classifier` / `Reference` — HEMIS klassifikator qiymatlari (jinsi, ta'lim shakli, ...)

### `apps/cameras`
- `Camera` — IP kamera konfiguratsiyasi (RTSP, HLS stream URL)
- `CameraROI` — har kamera uchun diqqat maydoni (Rectangle)
- `Auditorium` / `Building` — fizik bino va xonalar
- `SmartCamera` — SKUD aqlli kamera qurilmalari

### `apps/face_data`
- `EnrollmentPhoto` — talaba fotosuratining sifat holati
- `StudentEmbedding` — 512-o'lchamli ArcFace vektori, HNSW indeksida

### `apps/attendance`
- `RecognitionEvent` — har bir yuz tanish urinishi (accepted/review/rejected)
- `AttendanceLock` — 45 daqiqalik takroriy davomat bloki
- `LessonAttendance` — dars + talaba uchun yakuniy davomat (present/late/absent/wrong_room)
- `TrackSession` — kamera kadrida yuz kuzatuvi

### `apps/integrations`
- SKUD API dan ma'lumot yuklash: tashkilot, sinflar, xonalar, talabalar, jadval
- `SkudSyncService` — sinxronlash servisi
- `SkudAttendancePushService` — davomatni SKUD ga yuborish
- `SkudClient` — JWT token boshqaruvi bilan HTTP klient

### `apps/monitoring`
- Kamera holatini real-time kuzatish (dashboard)

---

## Ma'lumot Oqimi (Data Flow)

### 1. Talabalarni Tayyorlash (bir martalik)
```
sync_all_organizations → sync_students → sync_photos
       ↓
scan_enrollment_quality  (blur, yuz soni, o'lcham tekshiruvi)
       ↓
build_all_embeddings     (InsightFace → 512-dim vector → DB)
       ↓
mark_primary_embeddings  (har talaba uchun eng sifatli embedding)
```

### 2. Real Vaqt Davomat
```
run_camera_stream --all
       ↓                     ↓                 ↓
  cam-1 thread          cam-2 thread       cam-N thread
       ↓
HLS/M3U8 stream → kadr → temp fayl
       ↓
LiveFrameProcessorService.process_frame_image()
       ↓
pgvector: SELECT * FROM student_embeddings
          ORDER BY embedding <=> query_vec LIMIT 1000
       ↓
RecognitionEvent.create()  +  AttendanceLock.create()
       ↓
LessonAttendance.create/update()
       ↓
SkudAttendancePushService.push_recognition_event()
```

### 3. Dars Tugagach
```
mark_absent_for_finished_lessons()
  ─ dars vaqti tugagan + kelmaganlar "absent" qilinadi
```

---

## Konfiguratsiya Fayllari

| Fayl | Maqsad |
|---|---|
| `config/settings.py` | Django sozlamalari, DB, SKUD credentials, logging |
| `start_attendance.sh` | Tizimni ishga tushiruvchi shell script |
| `select_roi.py` | Kamera ROI ni vizual belgilash utility |
| `main.py` | Qo'shimcha kirish nuqtasi |

---

## Management Commandlar

| Command | Nima qiladi |
|---|---|
| `sync_all_organizations` | SKUD dan barcha tashkilotlarni sinxronlaydi |
| `build_all_embeddings` | Barcha valid fotosuratlar uchun embedding yaratadi |
| `generate_embeddings` | Bitta tashkilot uchun embedding |
| `scan_enrollment_quality` | Fotosuratlar sifatini tekshiradi |
| `audit_enrollment` | Enrollment holati statistikasi |
| `recognize_face` | Bitta rasm uchun qo'lda tanish testi |
| `recognize_track_flow` | Track-based tanish oqimi testi |
| `process_frame_image` | Bitta kadr faylini qayta ishlash |
| `run_camera_stream` | Kamera streamini ishga tushirish |
| `setup_cameras` | Kameralarni sozlash |
| `reprocess_failed_enrollment` | Muvaffaqiyatsiz enrollment qayta ishlash |
| `evaluate_search` | Qidiruv sifatini baholash |
| `check_api_vs_local` | API va lokal ma'lumotlarni solishtirish |

---

## Yutug'lari

### Texnik
- **pgvector HNSW indeks** — 512-dim vektorlarda O(log N) qidiruv, millionlab yozuvda ham tez
- **InsightFace buffalo_l** — production-darajali yuz tanish modeli, ArcFace arxitekturasi
- **Frontal frame accumulation** — bir necha kadrning o'rtacha embeddingi — tanish aniqligi oshadi
- **ROI cache (60s TTL)** — har kadrda DB ga bormaslik uchun
- **AttendanceLock** — 45 daqiqada bir marta davomat, duplicate yozuvlar bo'lmaydi
- **TrackSession** — yuz tracking, bitta kishi bir sessiyada ko'p marta qayta tanilmaydi
- **Upscaling** — 160px dan kichik yuzlar upscale qilinadi, uzak kameralarda ham ishlaydi
- **Thread per camera** — har kamera o'z threadida, to'xtab qolganlar boshqasini bloklamaydi
- **LessonAttendance priority** — `present > late > wrong_room > absent` (yaxshi holat ustun turadi)
- **Rotating file logs** — 20MB limit, 7 ta backup, Toshkent vaqtida
- **2-qadam sync** — avval DB, keyin foto yuklab olish (fayl xatosi DB ni buzmaydi)

### Arxitektura
- **Service layer** — business logic modellarda emas, service klasslarda
- **Multi-organization** — bitta tizim bir necha maktab/tashkilotga xizmat qiladi
- **SKUD bi-directional** — ma'lumot ham olinadi, ham yuboriladi

---

## Kamchiliklari

### Xavfsizlik (Kritik)
1. **`SECRET_KEY` ochiq yozilgan** (`config/settings.py:23`) — production uchun xavfli, environment variable bo'lishi kerak
2. **DB paroli hardcoded** (`settings.py:89`: `"PASSWORD": "1995"`) — `.env` fayl ishlatish kerak
3. **SKUD credentials ochiq** (`settings.py:143-144`: `SKUD_CLIENT_SECRET`) — environment variable bo'lishi kerak
4. **`DEBUG = True`** (`settings.py:22`) — production serverda False bo'lishi shart
5. **`ALLOWED_HOSTS = ["*"]`** (`settings.py:29`) — aniq domenlar ko'rsatilishi kerak

### Kod Sifati
6. **Eski modellar o'chirilmagan** — `AiAttendance`, `AiAttendanceFinal`, `AiAttendanceEmployee` modellari hali turibdi, lekin `LessonAttendance` + `RecognitionEvent` ular o'rnini bosgan; migratsiyalar hamda admin.py tozalanmagan
7. **`sync_photos` da `@transaction.atomic` + fayl saqlash** (`integrations/services.py:459`) — DB rollback bo'lsa disk fayllar orphan bo'lib qoladi; fayl saqlash transaksiyadan tashqariga chiqarilishi kerak
8. **In-memory state** (`_FRONTAL_STORE`, `_ROI_CACHE`) — multi-process (gunicorn) muhitida har process o'z cache sini saqlaydi, holatlar mos kelmaydi; Redis ishlatish kerak
9. **Grid-based track_key** — yaqin turadigan 2 talaba bir grid katagiga tushishi mumkin, noto'g'ri track sessiyalari yaratilishi ehtimoli bor
10. **`select_roi.py`** loyiha strukturasiga kirmagan, root papkada alohida turibdi
11. **`BaseModel.created_at`** — `auto_now_add=True` emas, `null=True, blank=True` — yangi yozuvlarda vaqt avtomatik to'ldirilmaydi

### Funksionallik
12. **`mark_absent_for_finished_lessons`** qo'lda yoki cron orqali chaqirilishi kerak — avtomatik cron sozlanmagan
13. **`sync_students` da parallel foto yuklash** (`workers=10`) — connection pool exhaustion xavfi bor, `close_old_connections()` chaqirilmagan

---

## Fayl Tuzilmasi

```
school_attendace_v1/
├── LOYIHA.md                  ← shu fayl
├── config/
│   ├── settings.py            ← Django sozlamalari
│   ├── urls.py                ← URL routing
│   ├── asgi.py / wsgi.py
├── apps/
│   ├── common/                ← BaseModel, User, RBAC
│   ├── academics/             ← HEMIS: talaba, o'qituvchi, jadval
│   ├── cameras/               ← Kamera, bino, xona, ROI
│   ├── face_data/             ← Enrollment foto + embedding
│   ├── attendance/            ← Davomat yozuvi, lock, track
│   ├── integrations/          ← SKUD sync + push servislari
│   └── monitoring/            ← Dashboard
├── docs/models/               ← Har model uchun alohida tahlil
├── start_attendance.sh        ← Ishga tushirish scripti
├── select_roi.py              ← ROI belgilash utility
└── manage.py
```

---

## Baho (Umumiy)

| Mezon | Ball | Izoh |
|---|---|---|
| Yuz tanish sifati | 9/10 | buffalo_l + frontal accumulation + upscaling — juda yaxshi |
| Arxitektura | 7/10 | Service layer yaxshi, lekin in-memory cache multi-process bilan muammo |
| DB dizayni | 8/10 | pgvector HNSW indeks — professional tanlov; eski modellar tozalanmagan |
| Xavfsizlik | 3/10 | Credentials hardcoded, DEBUG=True — production uchun jiddiy muammo |
| Kod sifati | 7/10 | Izohlar yaxshi (o'zbek tilida), service pattern izchil |
| Integratsiya | 8/10 | SKUD bi-directional sinx — to'liq va ishonchli |

**Umumiy baho: 7/10** — Texnik jihatdan kuchli tizim, lekin production ga chiqishdan oldin xavfsizlik muammolari hal qilinishi shart.
