# JAMI_3 — 2026-08-17/20: 225-maktab serveriga deploy

> JAMI_2.md (iyul sessiyasi) davomi. Maqsad: **boshqa mashinada** (MacOS) ishni
> davom ettirayotgan odam yoki Claude hech narsani qayta kashf qilmasdan
> shu nuqtadan davom etishi.
>
> Yozilgan: 2026-08-20. Branch: `deepstream8-migration`.

---

## 1. HOZIRGI HOLAT (eng muhim)

| Narsa | Holat |
|---|---|
| Git HEAD | `d3b41e6` — GitHub'da (`origin/deepstream8-migration`) |
| Dev mashina | Ubuntu, `172.16.125.114` — ishlab turibdi, 71-maktab demo ma'lumoti bilan |
| **Maktab serveri** | Ubuntu, RTX 5080, drayver 595.84 — **tayyor**, `~/school_ai_project` |
| Nishon | **225-maktab, SKUD org_id=16** (14-maktab/org 59 rejasi BEKOR qilindi 2026-08-20) |
| Sinov rejasi | Bolalar bir xonaga yig'ilib, jonli dars sinovi (9-sinf yoki 10-A) |

**Server holati (2026-08-20):** GPU konteynerda ko'rinadi, `web` ishlayapti,
58 migratsiya qo'llangan, `.env` to'ldirilgan (`BOT_ORG_ID=16`, `DEBUG=False`,
`ALLOWED_HOSTS=172.16.125.150`). SKUD sync va embedding — bajarilish arafasida.

**Server hali ofis tarmog'ida** (`172.16.125.150`), maktab tarmog'ida emas.
225-maktab kameralari `edu-api.devel.uz` proxy orqali ishlaydi (10/10 tirik),
shuning uchun jonli sinov proxy orqali ham mumkin.

---

## 2. BUGUNGI SESSIYADA TOPILGAN 6 TA BUG

Hammasi hujjatlashtirilgan va tuzatilgan. Bular "jim" xatolar — tizim sog'lom
ko'rinadi, lekin ishlamaydi.

### (1) AI_DET_SIZE — enrollment uchun 640, detection uchun 1280
14-maktab rasmlarida 690 fotodan **520 tasi `no_face`** bo'ldi, etalonli talaba
55 (208 dan). Sabab: `det_size=1280` da sifatsiz portretlarda SCRFD yuz topmaydi
(rasm bulanган: `std≈25`, blur `10-20`). 640 ga siqilganda downscale silliqlash
beradi va yuz topiladi.

O'lchov: bir xil rasmlar, `det_size` 320/640 — topildi, 1280 — topilmadi.
Tuzatishdan keyin: **690 embedding, 0 xato, 24 soniya**.

`.env` da `AI_DET_SIZE=1280` QOLADI (jonli detection uchun, evrika: +53%).
Enrollment buyruqlari env override bilan chaqiriladi:
```bash
docker compose exec -e AI_DET_SIZE=640 web python3.14 manage.py \
    sync_all_organizations --org-id 16 --step embeddings
```

### (2) Dockerfile: django-cors-headers Django pin'ini buzadi
Serverda build shu bilan yiqildi:
`ImportError: cannot import name 'cc_delim_re' from 'django.utils.cache'`

Sabab: `pip install --ignore-installed django-cors-headers==4.9.0` — bu paket
`django` ni versiyasiz talab qiladi, `--ignore-installed` bilan pip Django ni
qayta o'rnatib eng yangisini tortadi va `requirements.txt` dagi `Django==6.0.4`
pin'ini bekor qiladi. Yangi Django da `cc_delim_re` yo'q, DRF 3.17.1 esa uni
chaqiradi.

**Vaqtga bog'liq xato**: dev image 3 hafta oldin qurilgan, o'shanda eng yangi
Django 6.0.6 edi va ishlagan. Tuzatish: `--no-deps` (commit `a08c125`).

### (3) sync_organizations buyrug'i yo'q edi
Toza bazada `sync_full --org-id N` darhol yiqiladi:
`FAIL: ExternalOrganization matching query does not exist`
Sabab: `sync_organizations()` faqat HTTP API dan (`views.py:27`) chaqirilar edi.
Yangi buyruq yozildi — toza bazada **birinchi SKUD qadami**.

### (4) GPU almashtirilsa konteynerlar QAYTA YARATILSIN
`restart` yetarli emas — konteyner eski drayver holatiga bog'lanib qoladi,
ONNX jimgina CPU ga tushadi va log `ctx_id=0 (GPU)` deb **yolg'on yozadi**.
```bash
docker compose up -d --force-recreate web cameras
```
Tekshiruv loglarga emas, to'g'ridan: `docker compose exec web nvidia-smi -L`.

### (5) nvurisrcbin HLS `gap.mp4` (404) da jim o'ladi
Proxy kamera oqim bermaganda playlist'ga `gap.mp4` yozadi, faylni bermaydi.
GStreamer to'liq to'xtaydi: konteyner `running`, `RestartCount=0`, lekin
**7 daqiqa davomida kadr 0, GPU 0%**. Watchdog ham ishlamaydi (u RTSP uzilishi
uchun). OpenCV ayni oqimni ochadi — ya'ni faqat DeepStream pipeline'ga tegishli.
RTSP da yuzaga kelmaydi.

### (6) TensorRT engine repoda yo'q va nvinfer uni o'zi qura olmaydi
`deepstream_v3/engines/` `.gitignore` da. `pgie_det10g_1280.txt` da faqat
`model-engine-file=` bor, `onnx-file=` YO'Q — engine bo'lmasa pipeline umuman
ishga tushmaydi. Yechim: `bash deploy/build_engines.sh` (42 soniya).

**Tuzoq:** `make_input_size.py` STATIK shape li ONNX yasaydi
(`[1,3,1280,1280]`). Statik ONNX ga `trtexec --minShapes/--optShapes/--maxShapes`
BERILMAYDI — `Network And Config setup failed`. Eski 640 lik ONNX dynamic edi.

---

## 3. YARATILGAN FAYLLAR (hammasi GitHub'da)

| Fayl | Nima |
|---|---|
| `deploy/DEPLOY_14_MAKTAB.md` | To'liq deploy checklist (14-maktab uchun yozilgan, 225 ga ham mos — faqat org_id farq) |
| `deploy/SINOV_QOLLANMA.md` | **Jonli dars sinovi qo'llanmasi — maktabda shu ishlatiladi** |
| `deploy/server_setup.sh` | Serverni noldan tayyorlash (open modul, docker, toolkit) + GPU sinovi |
| `deploy/build_engines.sh` | TensorRT engine qurish (2 konteyner: onnx + trtexec) |
| `deploy/probe_cameras.sh` | Kameralarni zondlash (8 RTSP path, haqiqiy kadr o'qib) |
| `deploy/env.14maktab.example` | `.env` shabloni (org 59 uchun; 225 uchun `BOT_ORG_ID=16`) |
| `deploy/run_lesson_test.sh` | **Jonli dars sinovi — bitta buyruq** |
| `deploy/record_lesson.py` | Video yozish: xom (kameradan) + AI (MJPEG dan) |
| `apps/monitoring/.../setup_test_lesson.py` | Vaqtinchalik dars yozuvi |
| `apps/monitoring/.../lesson_report.py` | CSV hisobot (kim keldi, ball, SKUD) |
| `apps/integrations/.../sync_organizations.py` | Tashkilotlar sync (toza bazada 1-qadam) |
| `deepstream_v3/run_demo_isolated.sh` | Video demo — SKUD leak himoyasi bilan |

---

## 4. MA'LUMOT: 225-maktab (org 16)

SKUD dan o'lchangan (2026-08-20):

| | |
|---|---|
| Talaba | **325** |
| Rasmi bor | **314 (97%)** |
| Rasmi yo'q | 11 (3%, tarqoq) |
| Rakurslar | front 314, left 297, right 297, up 298, bottom 298 |
| Kameralar | 10 ta, `cam16_1..cam16_13`, proxy'da **10/10 tirik** |

Sinflar: 9-A (21), 9-B (38), 9-V (28), 10-A (42), 10-B (31), 10-V (40),
11-A (37), 11-B (33) va boshqalar.

**Taqqoslash — 14-maktab (org 59, rejadan chiqarilgan):** 208 talaba, 69 tasida
(33%) rasm yo'q, shundan 65 tasi = butun 11-sinf. Kameralari proxy'da yo'q.

---

## 5. SKUD LEAK — video/demo sinovda 3 sizish yo'li

Video replay bilan sinov qilinganda prod `edu.devel.uz` ga davomat sizadi:
1. **Inline push** — `services.py:886` `_push_to_skud`, shartsiz, o'chirish flagi yo'q
2. **Cron retry** — `docker/crontab:15`, har 5 daqiqada `retry_skud_push --limit 200`.
   O'lik URL bilan muvaffaqiyatsiz push `skud_push_error="network_error"` bo'lib
   qoladi (bu `skip:` EMAS), cron uni PROD URL bilan qayta yuboradi.
   **`school_ai_cron` ni to'xtatish SHART.**
3. **Kafka backlog** — prod consumer tiklanganda consume qilinmagan xabarlarni
   drenaj qilib push qiladi. Offset `--to-latest` reset shart.

Yechim: `bash deepstream_v3/run_demo_isolated.sh {start|stop|status}`.

**DIQQAT:** `run_lesson_test.sh` da izolyatsiya ATAYLAB YO'Q — jonli sinov
haqiqiy bo'lishi uchun SKUD ga real push ketadi (foydalanuvchi shunday qaror
qildi). SKUD API push-only, retract endpoint yo'q.

---

## 6. SERVER TALABLARI (o'lchangan)

Host'da **CUDA toolkit KERAK EMAS** — u konteyner image ichida keladi.

| Kerak | Versiya |
|---|---|
| Ubuntu | 24.04 |
| NVIDIA drayver **open modul** | 595.84 + `linux-modules-nvidia-595-open-$(uname -r)` |
| Docker + Compose | 29.x / v5.x |
| **nvidia-container-toolkit** | 1.19+ (eng ko'p unutiladigan) |
| Disk | **100 GB+** (image'lar 60 GB) |

RTX 5080 (Blackwell) proprietary modulni qo'llab-quvvatlamaydi. `nvidia-dkms`
paketi proprietary modulni `updates/dkms/` ga quradi va u open modulni bosib
ketadi -> `nvidia-smi: No devices were found`. Tuzatish:
```bash
sudo apt remove nvidia-dkms-595
sudo apt install linux-modules-nvidia-595-open-$(uname -r)
```

**Build vaqti:** `web` image noldan **69 daqiqa** (pip: onnxruntime-gpu +
insightface). Kesh bilan qayta build ~15 soniya.

---

## 7. KEYINGI QADAMLAR

1. **Serverda ma'lumot tayyorlash** (~15 daqiqa, darsdan OLDIN):
   `sync_organizations` -> `sync_full --org-id 16 --with-photos` ->
   rasmlar (partiyali, `remaining_estimate: 0` gacha) ->
   embedding (`AI_DET_SIZE=640`). Kutilgan: **etalonli=314**.
2. **Jonli dars sinovi**: `bash deploy/run_lesson_test.sh --camera-id N --class 9-A
   --subject "Tarix" --duration 45`. Natija: CSV + xom video + AI video.
3. Sinovdan keyin `setup_test_lesson --cleanup`.
4. Server maktab tarmog'iga o'tsa — `probe_cameras.sh` bilan RTSP ga o'tish
   (HLS `gap.mp4` bug'idan qutulish uchun).

---

## 8. BOSHQA MASHINADA (MacOS) DAVOM ETTIRISH

```bash
git clone git@github.com:temuralidavron/school_ai_project.git
cd school_ai_project
git checkout deepstream8-migration
```

Keyin Claude Code ni shu papkada oching. O'qish tartibi:
1. `CLAUDE.md` — avtomatik o'qiladi
2. **`JAMI_3.md`** (shu fayl) — bugungi holat
3. `deploy/SINOV_QOLLANMA.md` — maktabda ishlatiladigan buyruqlar
4. `JAMI_2.md` — iyul sessiyasi (evrika, B5, F0-F5)

MacOS da Docker ishlatilsa GPU bo'lmaydi (NVIDIA faqat Linux). Ya'ni MacOS dan
faqat **kod yozish va serverga SSH** qilinadi, AI pipeline serverda ishlaydi.

Foydalanuvchi konvensiyalari `CLAUDE.md` da: o'zbek tili, straight apostrof,
kod ichida emoji yo'q, **git commit/push faqat foydalanuvchi ruxsati bilan**,
mavjud kodga tegmaslik (yangi funksiya = yangi fayl).
