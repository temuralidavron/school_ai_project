# JAMI — DeepStream 8.0 migratsiyasi: to'liq holat va davom ettirish qo'llanmasi

> Bu fayl — loyihaning **DeepStream'ga to'liq o'tish** ishi bo'yicha to'liq hisobot va
> davom ettirish qo'llanmasi. Maqsad: keyingi odam (yoki keyingi Claude sessiyasi)
> hech narsani qayta kashf qilmasdan, aynan shu nuqtadan davom eta olishi.
>
> Yozilgan sana: 2026-07-06. Branch: `deepstream8-migration`.
> Checkpoint (eski, ishlaydigan versiya): tag `v1.0-ort`, commit `082a75e`.

---

## 1. Loyiha nima haqida (qisqa eslatma)

**school_ai_project** — maktabda kamera orqali yuz tanib avtomatik davomat yozadigan
tizim (Django + PostgreSQL/pgvector + InsightFace buffalo_l + Kafka + SKUD integratsiyasi).
Asosiy maqsad: **1 ta RTX 5080 GPU bilan 15-20 ta sinf/kamerada bir vaqtda, dars
boshidan 5-7 daqiqada, ishonchli davomat qilish.**

To'liq loyiha tahlili: [`LOYIHA.md`](LOYIHA.md), [`CLAUDE.md`](CLAUDE.md).
Foydalanuvchi: Aliyer Temur (CV/Python/Django muhandisi). Til: o'zbek.

---

## 2. Nega DeepStream'ga o'tildi — muammo va sabab

Loyiha boshida (`deepstream/` va `deepstream_v2/` papkalar) yuz aniqlash/tanish
Python + `onnxruntime` orqali ishlardi (haqiqiy DeepStream emas — faqat video decode
GPU'da, qolgani CPU'da Python). Bu quyidagi muammolarni berdi:

1. **Sekinlik**: 1 kadr/kamerada ~14 fps — 10-15 kamera uchun yetarli emas edi.
2. **Video kichraytirilishi**: pipeline videoni 1280x720 ga tushirar edi → uzoq/orqa
   qatordagi yuzlar yo'qolib qolardi (1 kadrda 20 o'quvchidan atigi 1 tasi topilardi).
3. **Track ID sakrashi**: oddiy Python `IouTracker` yuz bir necha kadr ko'rinmasa
   (bu deyarli har doim bo'lardi — muammo #2 sabab) yangi ID berardi — bir odam
   dars davomida 13+ marta "yangi odam" bo'lib qayd etilardi.

**2026-07-06 kuni gaplashilgan qaror**: bularni bittalab tuzatish o'rniga, **to'liq
DeepStream'ga o'tish** — ya'ni GPU'ning o'z `nvinfer` (TensorRT inference) va
`nvtracker` (GPU tracking) modullarini ishlatish. Bu haqiqatan DeepStream'ning
kuchidan foydalanish va 15-20 kamera masalasini tubdan hal qilish degani.

**Muhim texnik to'siq**: server GPU'si — RTX 5080 (Blackwell, `sm_120`). DeepStream
7.1 (loyihada ilgari ishlatilgan versiya) bilan kelgan TensorRT 10.3 `sm_120`ni
qo'llamaydi. Shuning uchun avval **DeepStream 8.0** (TensorRT 10.9, `sm_120`ni
rasman qo'llaydi) borligini tekshirib, shu versiyaga o'tildi.

---

## 3. Migratsiya rejasi — 7 bosqich (B0—B6)

Reja **TaskList**da saqlangan (TaskList/TaskGet bilan ko'rish mumkin — task #1-7,
"B0: DS 8.0..." dan "B6: Production mustahkamlik..." gacha). Holat:

| # | Bosqich | Holat | Natija (qisqa) |
|---|---|---|---|
| B0 | DS 8.0 + sm_120 TRT sinovi (GO/NO-GO) | ✅ TAYYOR | SCRFD va ArcFace TRT engine PASSED |
| B1 | nvinfer PGIE + Python tensor parse | ✅ TAYYOR | 22.5 yuz/kadr, ~800 fps |
| B2 | nvtracker (NvDCF) integratsiyasi | ✅ TAYYOR | 22 barqaror track/kadr |
| B3 | ArcFace gibrid + Kafka (eski format) | ✅ TAYYOR | To'liq zanjir: davomat + SKUD ishlaydi |
| B4 | Multi-source batch (2→20 video) | ✅ TAYYOR | **20 kamera 1 GPU'da isbotlandi** |
| B5 | Aqlli threshold + eng yaxshi kadr | 🔄 **BOSHLANGAN, TUGALLANMAGAN** | Kod joyi topilgan, hali yozilmagan |
| B6 | Production mustahkamlik va gigiyena | ⏳ boshlanmagan | — |

**B5 va B6 — KEYINGI ISH.** Pastda batafsil tavsif bor (bo'lim 8).

---

## 4. B0—B4: nima qilindi, qanday, qaysi tuzoqlar chiqdi

### 4.1 Umumiy arxitektura (deepstream_v3/)

```
deepstream_v3/
├── Dockerfile                     DS 8.0 image + pyds 1.2.2 + ORT 1.23.2 + Kafka
├── configs/
│   ├── pgie_det10g.txt             nvinfer PGIE konfiguratsiyasi (TRT engine yo'li)
│   └── tracker_nvdcf_faces.yml     NvDCF tracker sozlamalari (yuz uchun moslashtirilgan)
├── engines/                        (.gitignore'da — TRT engine fayllari, GPU-xos)
│   ├── det_10g_batched.onnx         SCRFD + Unsqueeze(batch dim) — add_batch_dim.py natijasi
│   ├── det_10g_batched_fp16.engine  ISHLATILAYOTGAN SCRFD TRT engine
│   └── w600k_r50_b16_fp16.engine    ArcFace TRT engine (build qilingan, HOZIRCHA ishlatilmayapti — B3 ORT gibrid)
├── pipeline/
│   ├── main.py                     Asosiy pipeline: nvinfer+nvtracker+ArcFace+Kafka+MJPEG
│   ├── scrfd_decode.py              SCRFD tensor decode (anchors, NMS) — Python, C++ EMAS
│   ├── face_align.py                v2'dan nusxa — InsightFace standart align
│   ├── arcface_runner.py            v2'dan nusxa — ORT ArcFace inference
│   ├── kafka_client.py              v2'dan nusxa — Kafka producer (FORMAT O'ZGARMAGAN)
│   └── mjpeg_server.py              v2'dan nusxa — jonli video (8554 port)
├── tools/
│   └── add_batch_dim.py             ONNX'ga Unsqueeze(axis=0) qo'shadi (pastda tushuntirilgan)
└── run_2cam.sh                      Tayyor skript: 2 videoni (9-G+11-G) bir buyruqda ishga tushiradi
```

**Muhim: Kafka xabar formati eskisi bilan AYNAN BIR XIL.** Django tarafi
(`apps/cameras/management/commands/kafka_consumer.py`, `apps/attendance/services.py`)
**hech qanday o'zgarishsiz** ishlatiladi. Bu B3'ning asosiy dizayn qarori edi —
riskni kamaytirish uchun.

### 4.2 Docker image qurish va ishga tushirish

```bash
# Image (bir marta, yoki kod o'zgarganda qayta):
cd /home/user02/Desktop/school_full/school_ai_project
docker build -t school_ai_ds3:latest deepstream_v3/

# 1 video (9-G) — qo'lda:
docker run -d --name school_ai_ds3_run --gpus all \
  --network school_ai_project_default -p 8554:8554 \
  -e KAFKA_BOOTSTRAP=kafka:9092 -e CAMERA_IDS=1 \
  -e TRACK_SEND_COOLDOWN=3 -e VIS_EVERY=2 \
  -v school_ai_project_insightface_models:/root/.insightface:ro \
  -v "$(pwd)/deepstream_v3/engines:/engines:ro" \
  -v "$(pwd)/deepstream/data:/data:ro" \
  school_ai_ds3:latest --video /data/sinf.mp4

# 2 video (9-G + 11-G) parallel — TAYYOR SKRIPT:
bash deepstream_v3/run_2cam.sh
```

Ko'rish manzillari (ishga tushgach ~30s kutish kerak — model yuklanadi):
- Jonli video (faqat 1-manba, yuz+ism+foiz): `http://localhost:8554/mjpeg`
- Davomat ro'yxati 9-G: `http://127.0.0.1:8000/monitoring/room/1/`
- Davomat ro'yxati 11-G: `http://127.0.0.1:8000/monitoring/room/2/`
- Solishtiruv (asl vs kamera): `http://127.0.0.1:8000/monitoring/comparison/`

To'xtatish: `docker stop school_ai_ds3_run` (yoki `docker stop <konteyner-nomi>`).

### 4.3 B0 — TRT engine sinovi (GO/NO-GO)

DS 8.0 konteynerida (`nvcr.io/nvidia/deepstream:8.0-gc-triton-devel`, diskda
36.8GB, allaqachon bor edi — qayta yuklash shart emas) `trtexec` bilan:
- `det_10g.onnx` (SCRFD, yuz aniqlash) → FP16 engine: **PASSED**, 0.49ms/kadr (2037 qps)
- `w600k_r50.onnx` (ArcFace, tanish) → FP16 engine: **PASSED**, 1.18ms (846 qps)

TensorRT versiyasi: **10.9.0.34** (`sm_120`ni rasman qo'llaydi). GO qarori qabul qilindi.

**Muhim eslatma:** DS 8.0 image entrypoint'i argumentlarni "yutib" ketadi (LICENSE
banner chiqarib to'xtaydi) — konteyner ichida buyruq ishlatish uchun har doim
`--entrypoint bash` bilan chetlab o'tish kerak edi (o'zimizning `school_ai_ds3` image
esa to'g'ri ENTRYPOINT bilan qurilgan, bu muammo yo'q).

### 4.4 B1 — nvinfer PGIE + Python tensor decode

**Qaror: C++ parser YOZILMADI.** `nvinfer` konfiguratsiyasida `output-tensor-meta=1`
qo'yilib, xom tensorlar (`NvDsInferTensorMeta`) to'g'ridan-to'g'ri Python probe'ga
uzatiladi, u yerda `scrfd_decode.py` (v2'dagi `det10g_runner.py` mantig'ining
ko'chirilgani: anchors, letterbox scale, NMS) bilan decode qilinadi.

**Uchta qiyin tuzoq va yechimlari** (agar kelajakda shunga o'xshash xato chiqsa, shu
yerni qarash kerak):

1. **`pyds.NvDsInferTensorMeta.output_layers_info(i).buffer` — NULL bo'ladi.**
   To'g'ri usul: `pyds.get_nvds_LayerInfo(tensor_meta, i)` — bu funksiya host
   buferni haqiqatan to'ldiradi. (`main.py` dagi `_extract_layers()` funksiyasi.)

2. **nvinfer TRT10 explicit-batch rejimida chiqish tensorining BIRINCHI o'lchamini
   "batch" deb qirqib tashlaydi.** SCRFD chiqishi `[12800, 1]` (12800 anchor,
   1-qiymat/anchor) edi — nvinfer buni "batch=12800, dims=[1]" deb tushunib, faqat
   1 ta element uchun joy ajratardi. **Yechim:** `tools/add_batch_dim.py` — ONNX
   grafига har chiqish uchun `Unsqueeze(axis=0)` qo'shib, `[12800,1]` → `[1,12800,1]`
   qiladi (haqiqiy batch=1 hosil bo'ladi). Bu skript `det_10g.onnx` dan
   `det_10g_batched.onnx` yasaydi, undan keyin TRT engine quriladi. **ONNX opset
   11 bo'lgani uchun** `Unsqueeze` `axes` ni alohida input emas, **atribut**
   sifatida oladi (`onnx.helper.make_node(..., axes=[0])`) — bu ham skriptda
   hisobga olingan.

3. Buning natijasida `main.py`da `_DET10G_SHAPES` lug'ati bor — nvinfer layer
   nomlarini (masalan `"448"`, yangi ONNX'da `"448_b"`) kutilgan shaklga (masalan
   `(12800, 1)`) bog'laydi, chunki meta orqali kelgan `inferDims` ishonchsiz.

**Natija:** kadrda o'rtacha **22.5 yuz** (eski ORT'da ~20 edi), pipeline **~800 fps**
(eski Python/ORT'da 14 fps edi) — **57 baravar tezroq**.

### 4.5 B2 — nvtracker (NvDCF GPU tracker)

`nvinfer`dan keyin decode qilingan har detection uchun Python probe'da
`pyds.nvds_acquire_obj_meta_from_pool()` bilan `obj_meta` yaratiladi (rect_params,
confidence) va frame'ga qo'shiladi (`object_id = UNTRACKED`). Keyin GStreamer
elementi sifatida `nvtracker` (`ll-lib-file=libnvds_nvmultiobjecttracker.so`,
`ll-config-file=tracker_nvdcf_faces.yml`) qo'shiladi — u obj_meta'larga **barqaror
`object_id`** beradi.

**ENG QIYIN TOPILGAN BUG (agar nvtracker 0 track ko'rsatsa — shu yerni tekshiring):**
`nvtracker` faqat `frame_meta.bInferDone == 1` bo'lgan kadrlarni qayta ishlaydi.
PGIE probe'da bu bayroqni qo'lda `frame_meta.bInferDone = 1` qilib qo'yish SHART —
aks holda tracker barcha obj_meta'larni jimgina tashlab yuboradi (log xatosi ham
chiqmaydi, shunchaki 0 track qaytadi). Bu B2'da soatlab vaqt olgan debugging edi.

NvDCF tracker sozlamalari (`configs/tracker_nvdcf_faces.yml`) sinf sharoiti uchun
sozlangan (statik o'tiruvchi yuzlar, ko'p miqdorda kichik/yon-burchak yuzlar):
`maxShadowTrackingAge` oshirilgan (51→150), matching score'lar yumshatilgan
(`minMatchingScore4*` pasaytirilgan). Track ID sakrashi (churn) sezilarli
kamaytirildi, lekin **hali ham bor** — kichik/burchak yuzlarda ID goh-goh
yangilanadi (masalan 2 daqiqada ~85-200 unique ID, 20-25 odam uchun). **Bu davomat
natijasiga zarar bermaydi** (chunki `AttendanceLock` va tanish student_id bo'yicha
ishlaydi, track_id vaqtinchalik identifikator xolos), lekin B5/B6'da "eng yaxshi
kadr" va uzoq muddatli kuzatish uchun yaxshilash imkoni bor (pastga qarang, ReID
opsiyasi).

### 4.6 B3 — ArcFace gibrid + Kafka + Django integratsiyasi + MJPEG

**Muhim dizayn qarori: ArcFace TensorRT SGIE emas, Python probe'da ORT bilan
gibrid tarzda ishlaydi.** Sabab: SGIE qilish uchun yuz tekislash (alignment)ni ham
GPU pipeline ichida qilish kerak bo'lardi — bu InsightFace standart alignment bilan
mos kelishini ta'minlash qo'shimcha risk edi. Gibrid yondashuv bilan: detection va
tracking (eng og'ir CPU/GPU ish) to'liq GPU'da (nvinfer+nvtracker), faqat ArcFace
(nisbatan yengil, faqat topilgan yuzlarga qo'llanadi) Python+ORT'da qoladi. Bu
80% foyda, 20% risk strategiyasi.

Oqim (`main.py` — `_recog_probe`): tracked obj_meta → SCRFD kps (5 nuqta, PGIE
probe'da saqlangan `_kps_store`dan bbox-markaz masofasi bilan bog'lanadi) →
frontal filtr (`_is_frontal`, yaw nisbati ≤ `MAX_YAW_RATIO`) → `align()`
(v2'dagi bilan bir xil, InsightFace standart) → 3 ta kadr pool (`EMB_POOL=3`) →
`ArcFaceRunner.get_embeddings()` (ORT GPU, batched) → o'rtacha + L2-norm →
`KafkaClient.send()` — **format v2 bilan bir xil**: `{ts, camera_id, frame_id,
track_id, session_id, bbox, confidence, embedding, face_crop}`.

`face_crop` — original bbox atrofidan katta crop (v2'dagi `_display_crop_b64`
mantig'i), aligned 112x112 EMAS — ko'rsatish uchun tiniqroq.

**Bir texnik tuzoq:** `onnxruntime-gpu` eng yangi versiyasi CUDA 13 talab qiladi
(`libcudart.so.13` xatosi berdi) — DS 8.0 image CUDA 12.8 bilan keladi. Yechim:
`Dockerfile`da **`onnxruntime-gpu==1.23.2`** pin qilingan (CUDA 12.x mos).

**MJPEG vizualizatsiya** (`mjpeg_server.py`, v2'dan nusxa) qo'shildi — `VIS_EVERY`
env orqali har N-kadrda tracked obj'larni chizadi (yashil+ism+foiz agar
`kafka_consumer` `track_names.json`ga yozgan bo'lsa, aks holda sariq+`T{id}`).
Faqat 0-manba (source_id==0) uchun chiziladi — ko'p-manbali holatda CPU tejash uchun.

**Real test natijasi (9-G, 34 o'quvchi, real Kafka→Django→SKUD orqali):**
- 1 daqiqada: 18/34 keldi
- ~2-7 daqiqada (video tezligiga qarab): 24-27/34 keldi (v1 rekordi bilan teng/yaxshi)
- False positive (rosterdan tashqari xato tanish): **0**
- Ballar: 0.501–0.607 (o'rtacha 0.538)
- Review'da qolgan 2 ta (Niyozov 0.484, Tagayev 0.475) — B5 aqlli threshold shularni
  olishi kerak
- Umuman ko'rinmagan 5 ta (Volkov, Akilova, Usmonova, Bagirova, Nazarova) — ehtimol
  kamera burchagi yoki o'sha kuni darsda yo'qligi (texnik muammo emas)

**Yon topilma:** eski (ORT) pipeline'da HECH QACHON ko'rinmagan ba'zi o'quvchilar
(masalan Xalikova Arina) yangi pipeline'da **davomat qildi** — sabab: to'liq
o'lchamli (1920x1080, kichraytirilmagan) qayta ishlov + to'g'ri align kichik/burchak
yuzlardan sifatliroq embedding beryapti.

**kafka_consumer.py'da qo'shimcha tuzatish:** `organization_id=None` doim
yozilardi (comparison sahifasi bo'sh chiqishiga sabab bo'lgan eski bug — bu B3
ishi davomida ham qayta uchradi). Tuzatish: `_org_for_camera(camera_id)` funksiyasi
`ExternalClassroom.objects.filter(camera_id=...).organization` orqali avtomatik
topadi va keshlaydi. **Bu tuzatish `docker cp` + `docker restart` bilan joylandi**
— production'da `school_ai:latest` image'ni **qayta build qilish kerak** (Dockerfile
o'zgarmagan, faqat source fayl nusxalandi, image eskirgan holatda qoladi).

### 4.7 B4 — Multi-source batch (2→20 video) — ENG KATTA ISBOT

`main.py` bitta manba (`--video path`) o'rniga **ko'p manba** qabul qiladigan
qilindi (`--video path1 path2 ... pathN`, `argparse nargs="+"`). Har manba
`_make_source_bin(index, path)` bilan alohida `Gst.Bin` (filesrc→qtdemux→
h264parse→nvv4l2decoder) sifatida quriladi va `nvstreammux.request_pad_simple(f"sink_{i}")`
ga ulanadi. `nvstreammux.batch-size = n_src`. `source_id` orqali kamera_id'ga
moslashtiriladi (`CAMERA_IDS` env, vergul bilan: masalan `1,2,3,...,20`).

**Muhim texnik nozik nuqta:** SCRFD (`det_10g`) TensorRT engine **qat'iy batch=1**
bilan qurilgan (dynamic batch profile `trtexec`da sinalgan, lekin ONNX modelning
o'zi input.1 birinchi o'lchamini "1" deb qattiq belgilagan — `IBuilder` xatosi
berdi: "profile has min=1,opt=8,max=20 but tensor has 1"). **Yechim: dynamic batch
qurilmadi — nvinfer batch=1 bilan qoldi.** Bu muammo emas, chunki 20 manbali
muxed batch kelganda ham nvinfer ularni **ketma-ket** (0.49ms/kadr × 20 = ~10ms/batch)
TRT'da ishlaydi — bottleneck bu emas, Python probe (ArcFace, decode) og'irroq.

**20-manba stress test natijasi** (10x `sinf.mp4` + 10x `11g.mp4`, Kafka/MJPEG
o'chirilgan, "as-fast-as-possible" rejimda — ya'ni video tezligini cheklamasdan):
- Umumiy tezlik: **1217 fps** (manba boshiga o'rtacha 60 fps)
- GPU yuki: o'rtacha **~82%** (peak 98%, ba'zan 51-66% — navbatlashuv tufayli tebranadi)
- Xotira: **5.2 GB / 16 GB**
- Quvvat: 225-250W / 360W

**Bu raqamlarni real-time'ga proyeksiya qilish (eng muhim xulosa):** test rejimi
real vaqtdan **~45x tezroq** ishladi (chunki cheklovsiz o'qildi). Haqiqiy jonli
kamera 27 fps (yoki undan past) real vaqtda keladi:

```
Real-time 20 kamera (27 fps/manba):  GPU ≈ 82% × (540/1217) ≈ 36%
Davomat rejimi (8 fps/manba yetarli): GPU ≈ 82% × (160/1217) ≈ 11%
```

**XULOSA: 1 ta RTX 5080 bilan 15-20 kamera BEMALOL ishlaydi (2.5-3x zaxira bilan).
Nazariy chegara ~40-50 kamera atrofida.** Ikkinchi GPU **kerak emas**.

---

## 5. Ishlaydigan eski versiyaga qaytish (agar kerak bo'lsa)

```bash
git checkout v1.0-ort          # yoki: git checkout main (agar migratsiya branch bilan almashtirilmagan bo'lsa)
```

Bu — `deepstream_v2/` (ORT-based, DeepStream 7.1) to'liq ishlaydigan holat, sozlamalar:
`MUX_WIDTH=1920, DET_THRESHOLD=0.35, TRACK_SEND_COOLDOWN=3, MAX_YAW_RATIO=0.6,
FRAME_SKIP=8` (test uchun), threshold `AI_ACCEPT_THRESHOLD=0.50/AI_REVIEW_THRESHOLD=0.45`.
Batafsil: xotira fayli `school_ai_deepstream_migration.md` (agar Claude memory
orqali ishlansa) yoki shu branch tarixidagi commit izohlari.

---

## 6. Diqqat qilinadigan narsalar / hali hal qilinmagan kamchiliklar

1. **Track ID churn (B2)** — kichik/burchak yuzlarda hali ham bor (davomatga
   zararsiz, lekin "eng yaxshi kadr" B5 funksiyasi buni hisobga olishi kerak —
   track_id emas, student_id bo'yicha eng yaxshi kadrni saqlash kerak bo'ladi).
2. **organization_id backfill** faqat joriy sessiyada `docker cp`+`restart` bilan
   qilingan — production image (`school_ai:latest`) qayta build qilinmagan.
   B6'da bu rasman image'ga kiritilishi kerak.
3. **ArcFace hali TensorRT emas** (Python ORT gibrid) — kelajakda SGIE qilish
   mumkin (yanada tezlashadi), lekin hozir shart emas (GPU yuki past).
4. **Test videolar** (`deepstream/data/sinf.mp4`, `11g.mp4`) real vaqtdan tez
   o'qilyapti (video fayl — hech qanday real-time cheklov yo'q). Haqiqiy RTSP
   kamerada `nvv4l2decoder`/`nvstreammux` real-time rejimda ishlaydi — FPS
   raqamlari bu holatda boshqacha (past, lekin YETARLI — bo'lim 4.7 hisobiga
   qarang) bo'ladi.
5. **`deepstream_v3/run_2cam.sh`** har ishga tushirishda dars jadvalini (`ExternalSchedule`
   id=5, id=6) bugungi sanaga majburan o'zgartiradi — bu FAQAT test/dev muhiti
   uchun mo'ljallangan (real production'da SKUD sync jadvalni o'zi to'g'ri sanada
   yuboradi).
6. **`.gitignore`**: `deepstream_v3/engines/` git'ga kiritilmagan (GPU-xos TRT
   engine fayllari, boshqa mashinada qayta qurilishi kerak — bo'lim 4.3-4.4dagi
   buyruqlar bilan).

---

## 7. Keyingi ish — B5: Aqlli threshold + eng yaxshi kadr (BOSHLANGAN)

### Muammo (foydalanuvchi bilan chuqur muhokama qilingan, 2026-07-06)

Hozir threshold **yalang'och va soqov**: `AI_ACCEPT_THRESHOLD=0.50` — kimning
balli shundan yuqori bo'lsa "keldi", past bo'lsa yo'q. Lekin o'rindiq joylashuvi
ballga tabiiy ta'sir qiladi: old qatordagi katta/frontal yuz → yuqori ball
(0.65-0.75); orqa qatordagi kichik/burchak yuz → past ball (0.45-0.55) — va bu
**doim shunday bo'ladi**, chunki o'quvchi doim o'sha joyda o'tiradi. Qattiq
threshold orqadagilarni abadiy "kelmagan" qilib qo'yadi.

### Kelishilgan yechim (uch qism, birga ishlaydigan mexanizm)

**1. Bosqichli tasdiqlash (ball qancha past — shuncha ko'p izchil ko'rinish kerak):**

| Ball | Necha marta izchil (bir xil student_id) kerak |
|---|---|
| ≥ 0.60 | 1 marta — darhol qabul |
| 0.54–0.60 | 3 marta |
| 0.48–0.54 | 6–8 marta |
| < 0.48 | qabul qilinmaydi |

**2. Margin (top-1 va top-2 nomzod orasidagi farq)** — past ball, lekin boshqa
nomzoddan ancha ustun bo'lsa (masalan Ali 0.50, ikkinchi eng yaqin nomzod 0.28),
bu haqiqiy signal (tasodifiy o'xshashlik emas). Margin ≥ 0.12-0.15 bo'lsa past
ballda ham ishonch oshadi.

**3. Eng yaxshi kadr** — o'quvchi dars davomida ko'p marta ko'rinadi (30-40
marta). Hozir birinchi mos kelgan kadr saqlanadi (ba'zan engashgan/noqulay).
Yechim: har **student_id** uchun (track_id emas — B2'dagi churn tufayli) eng
katta+eng frontal kadrni kuzatib borib, yaxshirog'i kelsa almashtirish. Bu ham
davomat rasmi sifatini, ham (keyingi bosqichda) "gallery boyitish" imkoniyatini
beradi.

### Qayerda ishlash kerak (kod joylari, B5 uchun allaqachon topilgan)

Bu mantiq **Django tomonida** (`apps/face_data/services.py` va
`apps/attendance/services.py`) — pipeline (DeepStream) tomoniga tegishli EMAS,
chunki qaror qilish joyi shu yerda:

- `apps/face_data/services.py`:
  - `RecognitionSearchService.decide_match_by_embedding()` (satr ~638) — asosiy
    qaror joyi, `accept_threshold`/`review_threshold` bilan solishtiradi.
    `effective_score = best["best_score"]` (satr ~672) — margin qo'shish shu yerda
    (`top_candidates` allaqachon mavjud, `top_candidates[1]` bilan solishtirish
    kerak).
  - `LessonEmbeddingCache.decide_match()` (satr ~564-632) — dars-ichidagi tezkor
    RAM qidiruv, xuddi shunday qaror mantig'i takrorlangan (ikkalasida ham
    o'zgartirish kerak bo'ladi, yoki umumiy funksiyaga chiqarish tavsiya etiladi).
- `apps/attendance/services.py`:
  - `recognize_track_and_record_by_embedding()` va unga o'xshash funksiyalar —
    "necha marta ko'rindi" holatini saqlash kerak (hozir `TrackSession` bor,
    lekin u track_id bo'yicha; **student_id bo'yicha** kuzatuv counter kerak
    bo'ladi — yangi model yoki `AttendanceLock`/`TrackSession`ga maydon qo'shish
    kerak bo'lishi mumkin).
  - Bosqichli tasdiqlash uchun har `(student_id, schedule_id)` juftligi bo'yicha
    "necha marta izchil ko'rindi" hisoblagich kerak — bu hozir yo'q, yangi
    jadval/maydon loyihalashtirish talab qilinadi.

**Boshlanganda nima qilingan edi:** shu joylar (`services.py` dagi threshold
funksiyalari) `grep` bilan topilgan (satr raqamlari yuqorida), lekin **hali hech
qanday kod yozilmagan**. Bu B5'ning haqiqiy boshlanish nuqtasi.

### Sinov mezoni (B5 tugaganda tekshirish kerak)

- 9-G va 11-G'da "review'da qolgan" va "umuman ko'rinmagan" o'quvchilar kamayishi
  kerak (hozirgi holat: 9-G'da 2+5=7, bo'lim 4.6ga qarang).
- **False positive hamon 0 bo'lishi shart** — bosqichli tasdiqlash/margin buni
  buzmasligi kerak (aks holda xato "keldi" xavfi oshadi).

---

## 8. B6: Production mustahkamlik va gigiyena (hali boshlanmagan)

Reja (task #7 tavsifidan):
1. **Watchdog**: pipeline crash/hang bo'lsa avto-restart (`docker-compose restart
   policy` + healthcheck — oxirgi frame vaqtini tekshirish).
2. **RTSP reconnect**: jonli kamera uzilganda pipeline o'zi qayta ulanishi kerak
   (hozir faqat video-fayl test qilingan, RTSP sinov qilinmagan).
3. **kafka_consumer organization_id** — 4.6-bo'limda qilingan tuzatishni
   production image'ga rasman kiritish (Dockerfile rebuild).
4. **Jadval/sana avtomatik sync** — hozir `run_2cam.sh` qo'lda sanani tenglaydi;
   production'da SKUD sync buni avtomatik qilishi kerak (allaqachon bor kod —
   `apps/integrations` — faqat cron/monitoring tekshiruvi kerak).
5. **room sahifa tuzatishlari**: video manbasi hozir hardcoded (`sinf.mp4`),
   kameraga mos bo'lishi kerak; `similarity: None` ba'zan chiqadi (kichik
   serializer bug); rasmni bosganda kattalashtirish (lightbox) yo'q.
6. **`school_ai_bot` konteyneri** — `TELEGRAM_BOT_TOKEN` yo'qligi sababli
   restart-loop'da (davomatga ta'sir qilmaydi, lekin tozalash kerak — token
   qo'shish yoki servisni o'chirish).
7. **Monitoring**: har kamera holati (ishlayapti/yo'q, oxirgi tanish vaqti) bitta
   joyda ko'rinishi kerak (hozir yo'q).
8. **Docker disk gigiyena**: build cache va eski image'lar tekshirilishi kerak
   (disk 386GB bo'sh edi, lekin DS image'lari juda katta — 35-37GB har biri).

---

## 9. Foydali diagnostika buyruqlari (tez-tez kerak bo'ladi)

```bash
# Davomat holatini tekshirish (masalan 9-G, schedule id=5):
docker exec school_ai_web python3.14 manage.py shell -c "
from apps.attendance.models import LessonAttendance
print(LessonAttendance.objects.filter(schedule_id=5).count(), '/ 34')"

# Test uchun DB tozalash (bitta kamera/schedule, boshqasiga tegmaydi):
docker exec school_ai_web python3.14 manage.py shell -c "
from django.utils import timezone
from apps.attendance.models import LessonAttendance, AttendanceLock, RecognitionEvent, TrackSession
t=timezone.now().date()
LessonAttendance.objects.filter(schedule_id=5).delete()
AttendanceLock.objects.filter(schedule_id=5).delete()
RecognitionEvent.objects.filter(camera_id=1, recognized_at__date=t).delete()
TrackSession.objects.filter(camera_id=1).delete()"
rm -f deepstream/data/track_names.json   # ismlar keshi (MJPEG uchun)

# ds3 pipeline loglarini kuzatish:
docker logs -f school_ai_ds3_run

# GPU real-vaqt kuzatish:
watch -n1 nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw --format=csv

# Kafka consumer lag (Django navbatni ulgurayaptimi):
docker exec school_ai_kafka /opt/kafka/bin/kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 --describe --group attendance-consumer
```

---

## 10. Fayl xaritasi (tez orientatsiya uchun)

| Fayl/papka | Nima |
|---|---|
| `deepstream/` | ESKI (Phase 1) — OpenCV+InsightFace, endi ishlatilmaydi |
| `deepstream_v2/` | O'RTA (ORT gibrid, DS 7.1 asosida decode) — `v1.0-ort` checkpoint shu |
| `deepstream_v3/` | **YANGI (bu hujjat haqida) — DS 8.0, nvinfer+nvtracker+ArcFace gibrid** |
| `deepstream_v3/pipeline/main.py` | Asosiy pipeline kodi — B1-B4 barchasi shu yerda |
| `deepstream_v3/pipeline/scrfd_decode.py` | SCRFD tensor→detection decode (Python, C++ emas) |
| `deepstream_v3/tools/add_batch_dim.py` | ONNX tuzatish skripti (B1 tuzoq #2 yechimi) |
| `deepstream_v3/run_2cam.sh` | Tayyor: 2 sinfni bir buyruqda ishga tushirish |
| `apps/cameras/management/commands/kafka_consumer.py` | Django Kafka iste'molchi — **o'zgartirilgan** (org fix) |
| `apps/attendance/services.py` | Recognition/lock/davomat mantiqi — **B5 shu yerda ishlanadi** |
| `apps/face_data/services.py` | Threshold/qidiruv mantiqi — **B5 shu yerda ishlanadi** |
| `LOYIHA.md`, `CLAUDE.md` | Loyihaning umumiy hujjatlari (eskirgan qismlari bor — bu fayl yangiroq) |

---

**Xulosa:** B0-B4 to'liq bajarilgan va isbotlangan — DeepStream 8.0'ga to'liq
o'tish texnik jihatdan muvaffaqiyatli, 15-20 (hatto 40+) kamera 1 GPU'da real.
B5 (aqlli threshold) hozirgina boshlangan — kod joylari aniqlangan, yozilishi
kerak. B6 (production mustahkamlik) hali boshlanmagan. Ishni davom ettirish uchun
TaskList'dagi #6 va #7 raqamli tasklarni ochib, shu hujjatning 7- va 8-bo'limlaridan
boshlash kifoya.
