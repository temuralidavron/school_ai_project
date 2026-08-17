# Deploy — 14-maktab (Toshkent viloyati, Qibray tumani)

> Umumiy deploy tartibi: [DEPLOY.md](DEPLOY.md). Bu fayl faqat 14-maktabga xos
> raqamlar, tuzoqlar va tekshiruvlarni qo'shadi. Yozilgan: 2026-08-17.

## 0. Maktab identifikatori (SKUD dan tasdiqlangan)

| Narsa | Qiymat |
|---|---|
| SKUD `org_id` | **59** |
| INN | `206920340` |
| Nomi | `14-maktab` |
| Sinflar | 10 ta: 8-A, 8-B, 9-A, 9-B, 9-V, 10-A, 10-B, 11-A, 11-B, 11-V |
| Xonalar | 7 ta, `deviceId` = `10.144.10.10` ... `10.144.10.15` |
| Talabalar | 208 |

DIQQAT: SKUD API tashkilot uchun atigi 3 maydon qaytaradi
(`organizationId`, `organizationInn`, `organizationName`) — **viloyat/tuman yo'q**.
"14-maktab" nomi SKUD'da yagona (142- va 148-maktablar boshqa ID), lekin agar
Qibray 14-maktabi ekaniga shubha bo'lsa, yagona qat'iy tekshiruv — **INN 206920340**.

## 1. BLOKER — 69 talabada rasm yo'q (deploy'dan OLDIN hal qilinsin)

| Maktab | Talaba | Front rasm | Rasmsiz |
|---|---|---|---|
| 225-maktab (org 16) | 325 | 314 | 11 (3%) |
| **14-maktab (org 59)** | **208** | **139** | **69 (33%)** |

208 talabaning 69 tasida SKUD'da hech qanday rasm yo'q (na `frontPhotoId`,
na `left/right/up/bottomPhotoId`). Bu bolalar uchun enrollment etaloni
yaratib bo'lmaydi — tizim ularni **hech qachon tanimaydi**, davomat doim
"kelmagan" bo'ladi.

Bu texnik muammo emas — **maktab ma'muriyati SKUD'ga rasm yuklashi kerak**.
Deploy'ni boshlash mumkin, lekin qamrov 67% dan oshmaydi.

Rasmsiz talabalar ro'yxatini olish (maktabga berish uchun):
```bash
docker exec school_ai_web python3.14 manage.py shell -c "
from apps.integrations.services import SkudClient
k = ['frontPhotoId','leftPhotoId','rightPhotoId','upPhotoId','bottomPhotoId']
for s in SkudClient().get_students(59):
    if not any(s.get(x) for x in k):
        print(s['className'], '|', s['fullName'], '|', s['pinfl'])
"
```

Ijobiy tomoni: rasmi bor 139 talabada **5 rakurs** bor (front ~139, left 138,
right 137, up 138, bottom 138) — F3b ko'p-shablon galereyasi uchun tayyor material.

## 2. Artefaktlarni tashish (eng og'ir qism)

O'lchangan hajmlar (taxmin emas):

| Artefakt | Hajm | Izoh |
|---|---|---|
| `school_ai_ds3:latest` | **38.1 GB** | DeepStream 8.0 pipeline |
| `school_ai:latest` | **21.4 GB** | web/cameras/cron/bot |
| NGC `deepstream:8.0-gc-triton-devel` | 36.8 GB | ds3 ning base image'i |
| `insightface_models` volume | 630 MB | buffalo_l — AI ISHLASHI UCHUN SHART |
| `deepstream_v3/engines/*.engine` | ~125 MB | TensorRT, **sm_120 ga bog'langan** |

Maktabda noldan build qilish ~37 GB internet yuklashni talab qiladi. Agar u yerda
internet sekin bo'lsa, tashqi disk bilan olib borish tezroq:

```bash
# BU YERDA (tayyorlash)
docker save school_ai:latest school_ai_ds3:latest | zstd -T0 -3 -o /media/disk/school_ai_images.tar.zst
docker run --rm -v school_ai_project_insightface_models:/v -v /media/disk:/out \
  alpine tar czf /out/insightface_models.tgz -C /v .

# MAKTABDA (tiklash)
zstd -d -c /media/disk/school_ai_images.tar.zst | docker load
docker volume create school_ai_project_insightface_models
docker run --rm -v school_ai_project_insightface_models:/v -v /media/disk:/in \
  alpine tar xzf /in/insightface_models.tgz -C /v
```

TensorRT engine'lar: agar maktab serverida ham RTX 5080 (sm_120) bo'lsa,
`deepstream_v3/engines/` ni o'z holicha ko'chirish mumkin. **Boshqa GPU bo'lsa
qayta qurish shart** — engine GPU arxitekturasiga bog'langan.

## 2b. Serverda nima o'rnatilishi kerak (aniq ro'yxat)

2026-08-17 da ishlaydigan dev mashinadan olingan — serverda shu bo'lsa yetadi.

| # | Nima | Ishlaydigan versiya | Izoh |
|---|---|---|---|
| 1 | Ubuntu | 24.04 LTS | Dockerfile shunga mo'ljallangan |
| 2 | NVIDIA drayver **open modul** | `595.84` + `linux-modules-nvidia-595-open-$(uname -r)` | RTX 5080 uchun open SHART (3-bo'lim) |
| 3 | Docker + Compose | `29.6.0` / Compose `v5.1.4` | Compose v2+ (plugin shakli) |
| 4 | **nvidia-container-toolkit** | `1.19.1` | **Eng ko'p unutiladigan** — busiz konteyner GPU ko'rmaydi |
| 5 | git | istalgan | repo klonlash |

**HOST DA CUDA TOOLKIT KERAK EMAS.** Dev mashinada `nvcc` YO'Q va 0 ta
`cuda-toolkit` paketi bor — hammasi baribir ishlaydi, chunki CUDA konteyner
image'ining ichida keladi. O'rnatilgan bo'lsa zarar qilmaydi, faqat joy egallaydi.

**Disk:** `school_ai` 22 GB + `school_ai_ds3` 38.1 GB + postgres/kafka/minio
1.6 GB + volume'lar 2.5 GB ≈ **64 GB**. Build vaqtidagi vaqtinchalik qatlamlar
bilan **kamida 100 GB** bo'sh joy kerak.

**Tekshiruv (serverda, ishni boshlashdan oldin):**
```bash
nvidia-smi                                  # RTX 5080 + 595.84
docker --version && docker compose version  # Compose v2+
dpkg -l | grep nvidia-container-toolkit     # BO'SH BO'LMASIN
df -h /                                     # 100 GB+ bo'sh
docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi
```
Oxirgi buyruq GPU ni ko'rsatsa — server tayyor.

**nvidia-container-toolkit yo'q bo'lsa:**
```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt update && sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
```

## 3. GPU — RTX 5080 uchun open kernel modul SHART

Bu tuzoq 2026-07-16 va 2026-08-17 da ikki marta chiqdi. Alomat: `nvidia-smi`
"No devices were found", dmesg'da `requires use of the NVIDIA open kernel modules`.

Sabab: `nvidia-dkms-*` paketi proprietary modulni `/lib/modules/$(uname -r)/updates/dkms/`
ga quradi, bu yo'l `kernel/nvidia-*-open/` dan ustun turadi.

Maktab serverida BIR MARTA to'g'ri qilish (kernel yangilansa ham buzilmaydi):
```bash
sudo apt remove nvidia-dkms-595            # nvidia-driver-595 metapaketi ham ketadi,
                                           # nvidia-utils/libnvidia-* qoladi
sudo apt install linux-modules-nvidia-595-open-$(uname -r)
sudo reboot
nvidia-smi                                  # RTX 5080 ko'rinishi kerak
docker run --rm --gpus all --entrypoint nvidia-smi school_ai_ds3:latest
```
Oxirgi buyruqda `--entrypoint` shart — image'ning ENTRYPOINT'i `main.py`.

## 3b. TensorRT engine — serverda QURILISHI SHART

`deepstream_v3/engines/` `.gitignore` da (82-qator), ya'ni GitHub dan KELMAYDI.
Engine GPU arxitekturasiga bog'langan (RTX 5080 = sm_120), boshqa mashinadan
nusxa ko'chirish ishonchsiz.

Muhimi: `configs/pgie_det10g_1280.txt` da faqat `model-engine-file=` bor,
**`onnx-file=` YO'Q** — ya'ni engine bo'lmasa `nvinfer` uni O'ZI QURA OLMAYDI,
pipeline umuman ishga tushmaydi.

```bash
bash deploy/build_engines.sh
```

Sinovdan o'tgan (2026-08-17, noldan): **42 soniya**, natija
`det_10g_1280_fp16.engine` 11.2 MB, keyin pipeline'da tasdiqlandi —
`frame#600 -> 25 track | 31 fps`.

Skript ikki konteynerni birlashtiradi (vositalar bo'lingan):
| Konteyner | Nima bor | Nima qiladi |
|---|---|---|
| `school_ai:latest` | `onnx` paketi (trtexec yo'q) | `make_input_size.py` bilan det_10g.onnx dan 1280 lik ONNX |
| `school_ai_ds3:latest` | `trtexec` (onnx paketi yo'q) | FP16 engine |

InsightFace modellari (`buffalo_l`, ~325 MB) volume'da bo'lmasa, skript ularni
o'zi yuklab oladi (internet kerak).

**Tuzoq:** `make_input_size.py` STATIK shape li ONNX yasaydi
(`[1,3,1280,1280]`). Statik ONNX ga `trtexec --minShapes/--optShapes/--maxShapes`
BERILMAYDI — aks holda `Network And Config setup failed`. Eski 640 lik ONNX
dynamic edi (`[1,3,?,?]`) va shape talab qilardi — chalkashlik shundan.
Skript buni to'g'ri qiladi, qo'lda `trtexec` yozsangiz e'tibor bering.

ArcFace uchun engine KERAK EMAS — v3 da `w600k_r50.onnx` to'g'ridan ONNX Runtime
GPU bilan ishlaydi (`deepstream_v3/pipeline/arcface_runner.py`).

## 4. Toza bazadan ko'tarish (tanlangan strategiya)

Quyidagi tartib toza bazada TO'LIQ ishlatib ko'rilgan (2026-08-17). Qadamlar
tartibi MUHIM — ayniqsa 4-qadam.

```bash
# 1. Servislar
docker compose up -d db minio minio_init
docker compose up -d web                    # entrypoint o'zi migrate + collectstatic qiladi

# 2. Migratsiya holatini tekshirish (toza bazada 58 ta qo'llanadi, qolgani bo'lmasin)
docker compose exec web python3.14 manage.py showmigrations | grep -c "\[X\]"
docker compose exec web python3.14 manage.py showmigrations | grep "\[ \]"   # bo'sh chiqishi kerak

# 3. Superuser
docker compose exec web python3.14 manage.py createsuperuser

# 4. TASHKILOTLAR RO'YXATI — TOZA BAZADA ENG BIRINCHI SKUD QADAMI
#    Busiz 5-qadam yiqiladi:
#      FAIL: ExternalOrganization matching query does not exist.
#    Sabab: sync_full darhol sync_classes dan boshlaydi va ExternalOrganization
#    yozuvini qidiradi; toza bazada esa u yo'q. SKUD 80 ta maktabni qaytaradi.
docker compose exec web python3.14 manage.py sync_organizations --check 59
#    -> "org_id=59: 14-maktab (INN 206920340)" chiqishi SHART.
#       Chiqmasa org_id noto'g'ri — davom etmang.

# 5. SKUD to'liq sync — sinf -> xona -> talaba -> jadval
docker compose exec web python3.14 manage.py sync_full --org-id 59 --with-photos

# 6. Rasmlar — PARTIYALI (bir chaqiruv 20 ta, 14-maktabda 690 ta bor).
#    remaining_estimate 0 bo'lguncha takrorlanadi (~35 marta, ~8 daqiqa):
until docker compose exec -T web python3.14 manage.py sync_full --org-id 59 --with-photos \
      2>&1 | grep -q "'remaining_estimate': 0"; do :; done

# 7. Embedding — AI_DET_SIZE=640 SHART (7a-bo'limga qarang)
docker compose exec -e AI_DET_SIZE=640 web python3.14 manage.py \
    sync_all_organizations --org-id 59 --step embeddings --embed-limit 1000

# 8. Tekshiruv — kutilgan raqamlar
docker compose exec web python3.14 manage.py shell -c "
from apps.face_data.models import EnrollmentPhoto, StudentEmbedding
from apps.integrations.models import ExternalStudent
from django.db.models import Count
n  = ExternalStudent.objects.filter(organization__organization_id=59).count()
em = StudentEmbedding.objects.filter(student__organization__organization_id=59).values('student_id').distinct().count()
st = dict(EnrollmentPhoto.objects.filter(student__organization__organization_id=59).values_list('status').annotate(c=Count('id')))
print(f'talaba={n} etalonli={em} foto={st}')"
```

**Kutilgan natija** (dev mashinada o'lchangan):
`talaba=208 etalonli=139 foto={'embedded': 690}` — ya'ni `no_face` NOL bo'lishi kerak.
Agar `no_face` chiqsa, 7-qadam `AI_DET_SIZE=640` siz bajarilgan.

Migratsiya tuzog'i: `apps/monitoring/migrations/0001_initial.py` yangi. TOZA bazada
muammo yo'q. Agar biror sababdan `bot_sent_reports` jadvali oldin yaratilgan bo'lsa
("relation already exists"), o'sha bitta app uchun:
`python3.14 manage.py migrate monitoring --fake-initial`.

## 5. Kameralar — RTSP yo'li (TANLANGAN)

**Qaror (2026-08-17, Aliyer):** 14-maktabda `edu-api` HLS proxy ISHLATILMAYDI,
kameralar bilan to'g'ridan **RTSP** orqali ishlanadi. Sabablari:
- maktab serveri kameralar bilan bitta tarmoqda (`10.144.10.x`) — proxy ortiqcha
  bo'g'in;
- 7b(a) bo'limidagi `gap.mp4` bug'i HLS ga xos — RTSP da yuzaga kelmaydi;
- tashqi xizmatga bog'liqlik yo'qoladi (internet uzilsa ham davomat ishlaydi).

**Kodga o'zgartirish KERAK EMAS** — RTSP allaqachon to'liq qo'llab-quvvatlanadi:
- `apps/cameras/services.py:158` — `rtsp://` bo'lsa URL o'zgartirilmaydi
  (`/index.m3u8` faqat HTTP proxy uchun qo'shiladi);
- `deepstream_v3/pipeline/main.py` — `nvurisrcbin` ga `rtsp-reconnect-interval=5`,
  `select-rtp-protocol=4` (TCP), `latency=200` beriladi;
- FFMPEG uchun `rtsp_transport=tcp` `docker/entrypoint-cameras.sh` da shell
  darajasida o'rnatilgan (commit `82b103f`).

### 5.1 Kameralarni topish (maktabda, birinchi qadam)

7 xona / 7 kamera, SKUD `deviceId` bo'yicha ketma-ket:

| Xona | classRoomId | Kamera IP |
|---|---|---|
| A5-xona | 145 | 10.144.10.10 |
| B5-xona | 146 | 10.144.10.11 |
| A4-xona | 147 | 10.144.10.12 |
| A6-xona | 148 | 10.144.10.13 |
| A7-xona | 149 | 10.144.10.14 |
| B11-xona | 150 | 10.144.10.15 |
| A8-xona | 151 | 10.144.10.16 |

RTSP yo'li (path) kamera brendiga bog'liq va oldindan noma'lum. Buni qo'lda
qidirmang — tayyor zondlovchi bor:

```bash
bash deploy/probe_cameras.sh                                  # user=admin, parol=.env dan
bash deploy/probe_cameras.sh --user admin --password PAROL    # parol boshqa bo'lsa
```

Skript har IP uchun: ping -> 554-port -> 8 ta RTSP path variantini **haqiqiy kadr
o'qib** sinaydi (OpenCV/FFMPEG bilan — `cameras` servisi ham shuni ishlatadi, ya'ni
"zond ishladi" = "tizim ham ishlaydi"). Ishlaganini topib `deploy/cameras_14.csv`
yozadi (`chmod 600` — ichida parol bor).

Sinaladigan yo'llar (birinchisi 71-maktabda ishlagan):
`/stream1`, `/Streaming/Channels/101`, `/cam/realmonitor?channel=1&subtype=0`,
`/h264/ch1/main/av_stream`, `/media/video1`, `/live/ch0`, `/onvif1`, `/11`.

Hech biri ishlamasa: kamera veb-interfeysiga kiring (`http://10.144.10.10`) — RTSP
manzili odatda o'sha yerda ko'rsatilgan. Topilgan yo'lni skriptdagi `paths`
ro'yxatiga qo'shish kifoya.

### 5.2 Bazaga qo'shish va pipeline'ga ulash

```bash
docker compose exec web python3.14 manage.py add_cameras --org-id 59 \
    --csv deploy/cameras_14.csv --activate
docker compose exec web python3.14 manage.py export_ds_sources --org-id 59 \
    --out deepstream_v3/configs/sources.json
docker compose --profile deepstream up -d ds3
docker logs -f school_ai_ds3            # "source N ulandi" + fps oqimi
```

## 5b. Kamera-xona bog'lanishi (eski 5-bo'lim)

SKUD xonalarining `deviceId` maydoni kamera IP'sini beradi
(`10.144.10.10` ... `10.144.10.15`). `sync_full` kamera<->xona bog'lanishini
`skud_device_id` orqali AVTOMATIK qiladi — shuning uchun CSV'dagi
`skud_device_id` ustuni SKUD'dagi `deviceId` bilan AYNAN mos kelishi shart.

```bash
# deploy/cameras_225.csv namunasidan nusxa olib, 14-maktab uchun to'ldiring:
#   Format: name;stream_url;skud_device_id
docker compose exec web python3.14 manage.py add_cameras --org-id 59 \
    --csv deploy/cameras_14.csv --activate

# DeepStream uchun manbalarni eksport qilish (yagona haqiqat manbai — Camera.stream_url)
docker compose exec web python3.14 manage.py export_ds_sources \
    --out deepstream_v3/configs/sources.json
```

Tekshirish: har kamera uchun `Camera.skud_device_id` to'ldirilganini ko'ring —
bo'sh bo'lsa `_find_classroom()` xonani topa olmaydi va **SKUD push ishlamaydi**
(`skip:no_classroom_for_camera`).

## 6. Production sozlamalari (.env)

Hozirgi dev qiymatlari serverga YARAMAYDI:

| O'zgaruvchi | Hozir | Serverda |
|---|---|---|
| `DEBUG` | `True` | `False` |
| `ALLOWED_HOSTS` | `*` | server IP/domen |
| `SECRET_KEY` | dev kaliti | yangi (`get_random_secret_key()`) |
| `DB_PASSWORD` | zaif | kuchli |
| `MINIO_ACCESS_KEY` / `SECRET_KEY` | `minioadmin` / `minioadmin123` | kuchli |
| `BOT_ORG_ID` | `16` | **`59`** |
| `AI_GPU_ID` | `0` | serverdagi GPU indeksi |

Portlar (`docker-compose.yml`) — hozir tashqariga ochiq, serverda yopilsin:
- `0.0.0.0:9001` MinIO Web UI -> `127.0.0.1:9001`
- `0.0.0.0:8080` Kafka UI -> `127.0.0.1:8080` yoki profil bilan o'chirilsin
- `8554` MJPEG -> kerak bo'lmasa `127.0.0.1:8554`

`.env` huquqi: `chmod 600 .env` (ichida SKUD siri bor).

## 7. Sinov tartibi (maktabda, shu ketma-ketlikda)

```bash
# 1. GPU
nvidia-smi && docker run --rm --gpus all --entrypoint nvidia-smi school_ai_ds3:latest

# 2. Servislar
docker compose ps                                  # hammasi healthy/running

# 3. Web
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/admin/

# 4. Ma'lumot
docker compose exec web python3.14 manage.py attendance_stats

# 5. Bitta kamera bilan jonli sinov (SKUD push YOQILGAN holda ehtiyot bo'ling)
docker compose --profile deepstream up -d kafka kafka_consumer
docker compose --profile deepstream up -d ds3
docker logs -f school_ai_ds3

# 6. Davomat sahifasi
#    http://<server>:8000/monitoring/live/<camera_id>/
```

SKUD leak ogohlantirishi: video/replay bilan sinov qilinsa, `run_demo.sh` ni
TO'G'RIDAN chaqirmang — `deepstream_v3/run_demo_isolated.sh start` ishlating,
tugagach `stop`. Sabab va tafsilot: skript sarlavhasida.

## 7b. JONLI SINOV NATIJALARI (2026-08-17, 225-maktab kamerasida)

Deploy'dan oldin jonli HLS manba 225-maktabning `cam16_2` kamerasida sinaldi.
Uch topilma — ikkitasi deploy'ga bevosita ta'sir qiladi.

### (a) BUG: pipeline yetishmayotgan HLS segmentda O'LADI va tiklanmaydi

`edu-api` proxy kamera oqim bermaganda playlist'ga `gap.mp4` segmentini yozadi,
lekin faylni BERMAYDI (404). GStreamer zanjiri shunda to'liq to'xtaydi:

```
souphttpsrc: Not Found (404), URL: .../cam16_2/gap.mp4
  -> basesrc: Internal data stream error
  -> streaming stopped, reason error (-5)
```

O'lchangan xulq: konteyner `running`, `RestartCount=0`, ArcFace va Kafka ulangan,
lekin **7 daqiqa davomida bironta kadr yo'q** — GPU 0%, MJPEG 0 bayt, Kafka offset
qimirlamagan. Ya'ni `SOURCE_STALE_SEC=30` watchdog ham, `nvurisrcbin` ning
o'z-o'zini tiklashi ham ishlamadi (ular RTSP uzilishi uchun, HTTP 404 uchun emas).

Nega muhim: bu faqat ta'til holati emas. Kamera quvvati/tarmog'i bir lahza uzilsa
proxy yana `gap.mp4` yozadi va **pipeline jim o'ladi** — konteyner "sog'lom"
ko'rinadi, davomat esa yozilmaydi. Maktabda buni payqash qiyin.

Tekshirilgan: `uridecodebin` ayni oqimni ochadi (buffering bilan bo'lsa ham),
`nvurisrcbin` esa 404 da darhol yiqiladi. Ya'ni muammo manba elementida.

Deploy'dan oldin qaror kerak: (1) HLS o'rniga lokal RTSP ishlatish — 14-maktabda
kameralar `10.144.10.x` da, server o'sha tarmoqda bo'ladi, ya'ni proxy umuman
kerak emas; yoki (2) 404 ni yutadigan/qayta ulanadigan manba mantig'i yozish.
**Tavsiya: (1)** — sodda va proxy'ga bog'liqlikni yo'qotadi.

### (b) 14-maktab kameralari hali proxy'da YO'Q

`cam59_A5`, `cam59_a5`, `cam59_145`, `cam14_A5`, `cam59_10` va boshqa variantlar —
hammasi 404. Taqqoslash uchun 225-maktabning 10 kamerasi (`cam16_1` ... `cam16_13`)
proxy'da bor. SKUD'da 7 xona va `deviceId` ro'yxatda turibdi, lekin oqim yo'q.

Maktabga borishdan OLDIN aniqlansin: kameralar fizik o'rnatilganmi, RTSP manzili
va login/paroli qanday, `edu-api` proxy'ga qo'shilishi kerakmi yoki lokal RTSP
yetadimi.

### (c) SKUD rasm yuklash PARTIYALI — bir chaqiruv 20 ta rasm

`sync_full --with-photos` bir marta ishga tushganda atigi **20 ta** rasm yuklaydi
(`batch_size=20`, javobda `remaining_estimate` qaytadi). 14-maktabda 690 rasm bor,
ya'ni ~35 marta takrorlash kerak.

Bu jim tuzoq: buyruq "muvaffaqiyatli yakunlandi" deb yozadi va rasmlar to'liq
yuklandi deb o'ylash mumkin. Har doim `remaining_estimate` ni tekshiring:

```bash
until docker compose exec -T web python3.14 manage.py sync_full --org-id 59 --with-photos \
      | grep -q "'remaining_estimate': 0"; do :; done
```

## 7a. ENG MUHIM: enrollment uchun AI_DET_SIZE=640, detection uchun 1280

2026-08-17 da o'lchandi. 14-maktab rasmlari bilan embedding yaratilganda
690 fotodan **520 tasi `no_face`** bo'ldi — atigi 55 talaba etalon oldi (208 dan 26%).

Sabab `det_size` da. Bir xil rasmlar, uch xil `det_size` bilan sinaldi:

| `det_size` | Sifatsiz rasmlarda yuz | Sifatli rasmlarda yuz |
|---|---|---|
| 320 | topildi | topildi |
| **640** | **topildi** | topildi |
| **1280** | **TOPILMADI** | topildi |

Rasm statistikasi farqni tushuntiradi:
- muvaffaqiyatsizlar: `std≈25`, Laplacian blur `10–20` (past kontrast, bulanган)
- muvaffaqiyatlilar: `std≈60`, blur `47–60` (aniq)

1280 da bulanган rasm o'z holicha qoladi; 640 ga siqilganda downscale silliqlash
beradi va SCRFD yuzni topadi. Ya'ni **katta det_size sifatsiz enrollment
rasmlariga ZARAR qiladi**.

Tuzatish natijasi (`reprocess_failed_enrollment` + `AI_DET_SIZE=640`):
**520 embedding yaratildi, 0 muvaffaqiyatsiz, 24 soniya (GPU)**. Etalonli talaba
55 -> **139** (rasmi bor talabalarning HAMMASI), qamrov 26% -> 67%.

**ZIDDIYATGA E'TIBOR:** `.env` da bitta `AI_DET_SIZE` bor, lekin ikki bosqichga
ikki xil qiymat kerak:
- **enrollment** (SKUD rasmidan etalon) -> **640** (sifatsiz portretlar uchun)
- **jonli detection** (sinfdagi kadr) -> **1280** (uzoqdagi kichik yuzlar; `evrika`
  tag'ida o'lchangan: davomat +53%)

Shuning uchun `.env` da `AI_DET_SIZE=1280` QOLSIN, enrollment buyruqlari esa
env override bilan chaqirilsin:

```bash
# etalon yaratish — 640 bilan
docker compose exec -e AI_DET_SIZE=640 web python3.14 manage.py sync_all_organizations --org-id 59 --step embeddings
docker compose exec -e AI_DET_SIZE=640 web python3.14 manage.py reprocess_failed_enrollment --organization-id 59 --limit 1000

# tekshiruv — no_face 0 ga tushishi kerak
docker compose exec web python3.14 manage.py shell -c "
from apps.face_data.models import EnrollmentPhoto
from django.db.models import Count
print(list(EnrollmentPhoto.objects.filter(student__organization__organization_id=59)
      .values('status').annotate(n=Count('id'))))"
```

Taqqoslash uchun 71-maktab (org 32): rasmlari sifatli, shuning uchun 1280 da ham
99% qamrov bergan (665/666). Ya'ni muammo har maktabda emas — **rasm sifatiga
bog'liq**, va yangi maktabda ALBATTA tekshirilsin.

## 7d. BUG: GPU yo'q bo'lsa embedding jim-jimlik bilan CPU ga tushadi

2026-08-17 da 14-maktab embeddingini yaratishda chiqdi. `school_ai_web` konteyneri
GPU drayveri tuzatilishidan OLDIN ishga tushgan edi — natijada ichkarida
`nvidia-smi -L` "Failed to initialize NVML" berdi va ONNX Runtime CPU ga tushdi:

```
CUDA failure 100: no CUDA-capable device is detected ; GPU=-1
Falling back to ['CPUExecutionProvider'] and retrying.
```

**Eng xavflisi — log YOLG'ON gapiradi.** O'sha ishga tushishda dastur
`InsightFace tayyor: ctx_id=0 (GPU) det_size=1280x1280` deb yozdi, aslida CPU da
ishladi. Ya'ni loglarga qarab "GPU ishlayapti" degan xulosa chiqarib bo'lmaydi.

Ikki qoida:

1. **GPU drayveri o'zgartirilsa (modul almashtirilsa, driver yangilansa), GPU
   ishlatadigan HAR BIR konteyner qayta YARATILSIN** — `restart` YETARLI EMAS,
   chunki konteyner eski drayver holatiga bog'lanib qolgan:
   ```bash
   docker compose up -d --force-recreate web cameras
   docker compose --profile deepstream up -d --force-recreate ds3 kafka_consumer
   ```

2. **GPU ni loglarga emas, to'g'ridan tekshiring** (deploy tekshiruv ro'yxatiga
   kiritilsin):
   ```bash
   docker exec school_ai_web nvidia-smi -L          # RTX 5080 ko'rinishi shart
   docker exec school_ai_web python3.14 -c "
   import onnxruntime as ort
   s = ort.InferenceSession('/root/.insightface/models/buffalo_l/w600k_r50.onnx',
                            providers=['CUDAExecutionProvider'])
   print(s.get_providers())"   # CUDAExecutionProvider chiqishi shart
   ```

## 7c. DB sequence tuzog'i (faqat dump ko'chirilsa)

Dev bazada `cameras_id_seq` band ID qaytardi va yangi kamera qo'shishda
`IntegrityError: duplicate key (id)=(2)` berdi — ma'lumot ID ko'rsatib kiritilgani
uchun sequence orqada qolgan. Toza bazada bu muammo YO'Q, lekin agar biror sababdan
`pg_dump`/`pg_restore` ishlatilsa, restore'dan keyin barcha sequence tekislansin:

```sql
DO $$
DECLARE r RECORD; mx BIGINT;
BEGIN
  FOR r IN SELECT c.relname AS tbl, a.attname AS col,
                  pg_get_serial_sequence(c.relname, a.attname) AS seq
           FROM pg_class c
           JOIN pg_attribute a ON a.attrelid=c.oid
           JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE c.relkind='r' AND n.nspname='public'
             AND a.attnum>0 AND NOT a.attisdropped
             AND pg_get_serial_sequence(c.relname, a.attname) IS NOT NULL
  LOOP
    EXECUTE format('SELECT COALESCE(MAX(%I),0) FROM %I', r.col, r.tbl) INTO mx;
    IF mx > 0 THEN PERFORM setval(r.seq, mx, true); END IF;
  END LOOP;
END $$;
```
`NOT a.attisdropped` shart — aks holda `django_content_type` dagi o'chirilgan
ustunda yiqiladi.

## 8. Hal qilinmagan savollar

- Maktab serverida qaysi GPU bo'ladi? RTX 5080 bo'lmasa TensorRT engine'lar qayta quriladi.
- 7 xonaning nechtasiga kamera fizik o'rnatilgan? SKUD'da 7 ta `deviceId` bor, lekin
  kameralar haqiqatan ulanganmi — joyida tekshirilsin.
- Kamera oqim manzili: `deviceId` faqat IP beradi, `stream_url` (RTSP/HLS proxy)
  formati maktab tarmog'iga qarab aniqlanishi kerak.
- 69 rasmsiz talaba: maktab qachon yuklaydi? Ulargacha qamrov 67%.
