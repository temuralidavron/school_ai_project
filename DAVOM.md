# DAVOM — yangi Claude sessiyasi uchun to'liq kontekst

Yozilgan: 2026-08-25; 2026-08-26 va **2026-08-27 (maktabga yo'l oldidan) yangilandi**.
**Bu faylni yangi ochilgan har qanday Claude sessiyasi (maktab serveri,
macOS, istalgan joy) BIRINCHI o'qisin.**

---

## 2026-08-27 ABED — MAKTABGA KETISH OLDIDAN. MACOS SESSIYASI, SHU YERDAN BOSHLA

Aliyer maktabga ketdi, yonida macOS noutbuk. Sen ehtimol o'sha macOS'dasan.

**1. Avval qayerdaligingni aniqla:** `uname -a` (Darwin = macOS noutbuk,
Linux = server). macOS'da bo'lsang — docker/GPU/baza BU YERDA YO'Q, hamma
ish buyruqlari MAKTAB SERVERIDA bajariladi: `ssh <user>@<server_ip>` orqali
(server IP ni Aliyerdan so'ra, odatda kamera tarmog'ida yoki Mikrotik LAN da).
Sen macOS'da faqat kod o'qiysan, maslahat berasan, buyruq tayyorlaysan —
Aliyer ularni serverda bajaradi yoki ssh sessiyada o'zing bajarasan.

**2. Bugungi holat (uy serverida qilib qo'yildi, hammasi GitHubda):**
- GitHub `main` = `deepstream8-migration` = **948a4dc** — hamma narsa ichida.
- **SKUD API v3 ga moslashuv TUGADI va jonli sinaldi** (yuqoridagi 5-band).
- **Image chamadoni**: uy serverida `~/school_ai_project/dist_images/`
  (35 GB, 8 arxiv, SHA256 OK). Maktab serveriga rsync qilingan bo'lishi
  kerak — bo'lmasa Aliyerda USB nusxasi bo'lishi mumkin, so'ra.
- Uy serverida ds3 HLS rejimda izolyatsiyada ishlab turgan edi (tegma).

**3. Maktabdagi VAZIFA — qaysi server ekaniga qarab:**
- **Yangi server (49-maktab, org 36):** [deploy/MAKTAB_49.md](deploy/MAKTAB_49.md) —
  A-qism (uyda qancha tugagan bo'lsa davomidan) keyin B-qism (tarmoq, kamera,
  start). org 36, INN 204903379, region=1, district=2. org 67 BOSHQA maktab!
- **225-maktab serveri (org 16):** RTSP ga o'tish — [deploy/RTSP_MAKTAB.md](deploy/RTSP_MAKTAB.md).

**4. Tez-tez kerak bo'ladigan raqamlar:**
| Narsa | Qiymat |
|---|---|
| 49-maktab | org **36**, INN 204903379, region 1, district 2, 261 talaba (7 rasmsiz) |
| 225-maktab | org **16**, kameralar 10.144.4.x, yo'l /stream1, admin/admin |
| Chegara | accept 0.50, review 0.45 |
| SKUD sync (v3) | `sync_organizations --region-id 1 --district-id 2 --check <org>` |
| Enrollment | DOIM `AI_DET_SIZE=640` bilan |

**5. QAT'IY esla:** sinov = `--skud izolyatsiya`. SKUD da haqiqiy jadval
bo'lmagunча `--skud real` YO'Q. `.env` gitda yo'q — sirlarni Aliyer biladi.
Git: faqat Aliyer aytsa commit/push.

---

## 2026-08-26 — yangi serverda (172.16.125.150) sozlash va 4 tuzatish

Bu server kamera tarmog'ida EMAS — HLS bilan sinaldi, SKUD izolyatsiyada.
ds3 image (14 GB) + TensorRT engine (676 qps @1280) shu yerda qurildi.
O'lchangan: 9 manba, 183 fps agg, consumer xatosiz, embedding zanjiri ishladi.

Topilgan va TUZATILGAN xatolar (hammasi commit qilinmagan — Aliyer ko'radi):

1. **face_align.py: RANSAC -> Umeyama.** estimateAffinePartial2D(RANSAC)
   tasodifiy va nuqta tashlaydi — etalon (InsightFace) bilan solishtirganda
   kosinus o'rtacha 0.9888, eng yomoni 0.823 (40 rasmda o'lchandi).
   Umeyama bilan 1.0000. Etalonlarni qayta hisoblash KERAK EMAS.
2. **main.py bus handler: bitta o'lik kamera hammasini o'ldirardi.**
   Xato ichki elementdan keladi (masalan 404 da "source" nomli GstSoupHTTPSrc),
   eski tekshiruv "src-" prefiksni ko'rardi -> loop.quit -> crash-loop.
   Endi OTA zanjiri tekshiriladi. O'lik RTSP esa baribir xavfsiz (o'lchangan).
3. **start.sh: o'lik HLS manba sources dan chiqariladi.** 404/qotgan HTTP
   manba pipeline'ni to'xtatardi. O'lik RTSP qoladi (nvurisrcbin o'zi ulanadi).
   DIQQAT: logs/ papka root egaligida — filtr web konteyner ichida bajariladi.
4. **main.py: SELF-RESTART watchdog.** DS 8 nvurisrcbin+hlsdemux2 gst_bus_post
   mutex DEADLOCK (gdb bilan tasdiqlandi) — beqaror proxy'da pipeline JIM
   qotadi (xato yo'q, EOS yo'q). Docker unhealthy'ni O'ZI restart qilmaydi!
   Endi kadr 90s+ to'xtasa (yoki 180s da birinchi kadr kelmasa) jarayon
   os._exit(42) qiladi, restart policy qayta ko'taradi. Bu deadlock FAQAT
   HLS yo'lida — maktabdagi RTSP rejimga TA'SIR QILMAYDI.
   Qo'shimcha: unmap_nvds_buf_surface qo'shildi (map leak), _emb_buffer
   tozalash qo'shildi (xotira o'sishi).

Yana bilib tur:
- SKUD get_today_schedule(16) bugun uchun BO'SH — jadval yo'q kunlarda
  davomat yozilmaydi (bu to'g'ri xatti-harakat), sinov uchun
  run_lesson_test.sh vaqtinchalik jadval yaratadi = IZOLYATSIYA SHART.
- org 16: 325 talaba, 1403 embedding, 308 talabada etalon bor, 17 tasida yo'q.
- Kamera<->xona bog'lanishi 10/10 to'g'ri (skud_device_id orqali).
- **RTSP ga o'tish maktabda:** `bash deploy/rtsp_tayyorla.sh` (yangi skript,
  [deploy/RTSP_MAKTAB.md](deploy/RTSP_MAKTAB.md) o'qi). Aliyer 2026-08-26 da
  TASDIQLADI: kameralar 10.144.4.x (baza TO'G'RI), yo'l /stream1, admin/admin.
  camera_ips.csv yangilandi, start.sh defaulti /stream1. Eski 10.144.0.x va
  "Hikvision 101" ma'lumoti NOTO'G'RI edi. Server IP 10.144.4.249 VAQTINCHALIK
  (reboot'da o'chadi) — RTSP_MAKTAB.md 6b-bo'lim (netplan) bajarilsin.
- cam 2 proxy'da 404 (chiqarilgan), cam 10 stream_url'i rtsp (bu yerdan o'lik).

## 2026-08-27 — SKUD push teshigi, image to'plami, 49-maktab tayyorgarligi

1. **KRITIK TUZATISH: cron izolyatsiyani chetlab o'tardi.** Consumer
   izolyatsiyada bo'lsa ham cron (retry_skud_push, har 5 daq) real URL da
   qolib sinov davomatini prodga oqizardi — 2026-08-20 dagi 72 yozuv shu
   yo'ldan ketgan bo'lishi ehtimol. demo-isolated.yml va start.sh endi cron
   ni ham qamraydi. Batafsil: [deploy/SKUD_PUSH.md](deploy/SKUD_PUSH.md).
2. **.env.example YARATILDI** (yo'q edi — hujjatlar unga yo'llardi).
   .gitignore: .env.bak ham yopildi (ichida sirlar bor edi, himoyasiz edi).
3. **Image to'plami**: `bash deploy/image_tarqatish.sh export` -> dist_images/
   (18 GB, SHA256 tekshirilgan): hamma image + buffalo_l + onnx + engine.
   Maktabda: `import` — build o'rniga ~10 daqiqa, internetsiz.
4. **Audit (18 agent)**: 13 tasdiqlangan muammo tuzatildi — start.sh (logs/
   egalik, filtr xato tekshiruvi, --url endi --cameras talab qiladi, CSV
   faqat org 16 da avtomatik), rtsp_tayyorla.sh (sort crash, port/login
   solishtirish, is_active_stream/stream_url ta'minlash), main.py (dict
   poyga, file:// restart sikli), kafka_consumer (None kesh), run_lesson_test
   (tarmoq nomi dinamik), ERTAGA_10V eski id jadvali.
5. **SKUD API v3 (2026-08-27, JONLI):** /organizations endi regionId+districtId
   TALAB QILADI (paramsiz 400 — eski sync_organizations buzilgan edi).
   Yangi: /regions, /districts. Qolgan 8 endpoint AYNAN o'zgarishsiz.
   Moslandi: SkudClient.get_regions/get_districts, get_organizations(region,
   district) — parametrsiz eski xatti-harakat saqlanadi (hamma tumanni
   aylanadi). sync_organizations --region-id/--district-id. Ikkala maktab ham:
   region=1 (Toshkent sh.), district=2 (Mirzo Ulug'bek t.). Sinovdan o'tdi.
6. **49-maktab** = org 36 (INN 204903379; org 67 BOSHQA maktab — adashtirmang!):
   261 talaba, 254 rasmli, 10 xona. deviceId IP EMAS (dev_49_XX) — kamera
   qadmlari boshqacha: [deploy/MAKTAB_49.md](deploy/MAKTAB_49.md).
   Yangi server tartibi: [deploy/YANGI_MAKTAB.md](deploy/YANGI_MAKTAB.md).

---

## Sen kimsan va kim bilan gaplashyapsan

Sen — Claude, shu loyihaning doimiy yordamchisisan. Foydalanuvchi —
**Aliyer Temur**, CV/Python/Django muhandisi. U sen bilan boshqa mashinada
uzoq ishlagan; sen o'sha suhbatning davomisan, o'zingni yangi tanishtirma,
ishni davom ettir.

Loyiha — **225-maktab AI davomat tizimi**: kameralar bolalarni yuzidan
taniydi, davomatni PostgreSQL ga yozadi va SKUD (`edu.devel.uz`) ga yuboradi.
Stack: Django + DRF, PostgreSQL 16 + pgvector, MinIO, Kafka,
DeepStream 8 (RTX 5080, TensorRT), InsightFace buffalo_l.

## Qat'iy qoidalar (Aliyer bilan kelishilgan)

1. Til — o'zbek (lotin), straight apostrof ('). Kod ichida emoji YO'Q,
   kommentariy faqat WHY. Loglar inglizcha.
2. **Ishlab turgan tizimni buzma.** Yangi narsa — alohida fayl/skript.
   Mavjud kodni o'zgartirishdan oldin har doim o'qib chiq.
3. **Muammoni OLDINDAN ayt.** Aliyerning talabi: "kelajakda shu muammo
   chiqadi" deganlarini ish boshlanmasdan aytish. U ikki marta maktabda
   sharmanda bo'lgan — uchinchisi bo'lmasin.
4. **SKUD push-only — yuborilgan davomat QAYTMAYDI.** Sinovda har doim
   izolyatsiya (`SKUD_API_BASE_URL=http://127.0.0.1:9` bo'lsa izolyatsiya).
   2026-08-20 da 72 ta yolg'on davomat prodga ketib qolgan.
5. `docker cp` ishlatma (konteyner recreate bo'lsa yo'qoladi).
   `.env` ga tegma — override qatlamlar ishlat.
6. Git: Aliyer aytsa commit qilasan, o'zingcha emas.

## MAKTABDA — bitta buyruq

```bash
cd <loyiha papkasi>
git pull
bash deploy/start.sh rtsp
```

Shu bitta buyruq HAMMASINI o'zi qiladi:
disk/GPU tekshiradi -> **docker image yo'q bo'lsa BUILD qiladi** (bir
martalik, ~30-50 daq; keyin sekundlar) -> **TensorRT engine yo'q bo'lsa
build qiladi** (~15 daq, bir martalik) -> baza/kafka/web ko'taradi ->
kamera IP larni `deploy/camera_ips.csv` dan oladi (avtomatik) -> RTSP
manbalar jonliligini zondlaydi -> pipeline ko'taradi -> zanjirni tasdiqlaydi
(kadr -> Kafka -> consumer -> baza).

Yangi serverda oldindan kerak bo'ladigan yagona narsalar: docker +
nvidia-container-toolkit + `.env` fayli (gitda yo'q — `.env.example` dan
nusxalab SKUD/DB parollarini yozish) va birinchi buildda internet.
Server noldan bo'lsa: `bash deploy/server_setup.sh` hammasini tayyorlaydi.

- Kameralar: 10 ta, `10.144.4.x`, login `admin/admin` (2026-08-26 tasdiqlandi;
  eski "10.144.0.x / Hikvision 101" yozuvi NOTO'G'RI edi).
  Yo'l: `/stream1` (default). Kichik oqim ishlatma — yuz 30-40 px TANILMAYDI.
- Server kamera tarmog'ida bo'lishi shart: `ip a | grep 10.144`.
  Skript "554 YOPIQ" desa — tarmoq yo'q, kabel/VLAN/VPN ni tekshir.
- Web image eski bo'lsa ham ishlaydi (skriptda host-zaxira yo'l bor).

Dars sinovi (davomat + 2 video + CSV hisobot):

```bash
bash deploy/run_lesson_test.sh --camera-id <XONA_ID> --class 10-V --subject Tarix --duration 45
```

10-V: 40 talaba, 38 etalonli. Ikkitasi SKUDda rasmsiz — TANILMAYDI
(Abdug'anieva Fotima, Ермаков Герман). Bu xato emas, oldindan ma'lum.
Dars jadvali SKUDda yo'q — skript vaqtinchalik yozuv o'zi yaratadi.

Boshqa buyruqlar:

```bash
bash deploy/start.sh status              # nima ishlayapti
bash deploy/start.sh stop                # AI to'xtaydi (baza/web qoladi)
bash deploy/start.sh hls                 # RTSP bo'lmasa proxy orqali (internet)
bash deploy/start.sh rtsp --threshold 0.45   # chegara (past=ko'p taniydi)
bash deploy/start.sh rtsp --skud real        # SKUDga HAQIQIY push (ehtiyot!)
bash deploy/start.sh rtsp --url "rtsp://admin:admin@IP:554/stream1" --cameras 9
                                         # bitta tayyor link bilan
bash deploy/cleanup.sh --check           # disk nima yeyapti
bash deploy/cleanup.sh --install-cron    # har kuni 03:00 avto tozalash
```

## Hozirgi holat (2026-08-25 kech)

- Uy serverda HLS rejim ishlab turibdi: 10 kamera, 270 fps, chegara 0.50,
  SKUD **izolyatsiyada**. Consumer xatosiz, Kafka oqimi bor.
- `--threshold` `.env` ga yozilmaydi — `.threshold.override.yml` qatlamida
  (gitda YO'Q; yangi serverda default .env dan olinadi: 0.50/0.45 — bir xil).
- SKUD rejimi serverga qarab: `bash deploy/start.sh status` ko'rsatadi.
  Izolyatsiyani boshqarish: `--skud real` / `--skud izolyatsiya`.

## Bilib tur — kutilayotgan muammolar

1. **Kernel yangilansa GPU yo'qoladi** (DKMS proprietary modul open modulni
   bosadi): `sudo apt install -y linux-modules-nvidia-595-open-$(uname -r)`
   keyin reboot. `nvidia-smi` ishlamasa — birinchi shuni tekshir.
2. **TensorRT engine** boshqa GPU da qayta build talab qiladi:
   `bash deploy/build_engines.sh` (~15 daq). `start.sh` yo'qligini o'zi aytadi.
3. **Proxy HLS jim o'lishi**: HTTP 200 qaytadi lekin oqim yo'q (gap segment).
   `start.sh` buni ko'tarishdan OLDIN topadi (MEDIA-SEQUENCE zondlash).
4. **Docker log** endi 100 MB x 3 bilan cheklangan (compose x-logging).
   Eski serverlarda cheksiz — `cleanup.sh --apply` tuzatadi.
5. **RTSP autentifikatsiya**: kamera admin/admin qabul qilmasa 401 bo'ladi —
   `--rtsp-user/--rtsp-pass` bilan ber. Kamera web UI: `http://IP` da tekshir.
6. Kameralar PTZ: `manage.py ptz_control --ip IP --detect` (7 format sinaydi).
   PTZ proxy orqali O'TMAYDI — faqat to'g'ridan IP.

## Fayllar xaritasi

| Fayl | Nima |
|---|---|
| `deploy/start.sh` | BIR BUYRUQ: hls/rtsp/status/stop + barcha tekshiruvlar |
| `deploy/camera_ips.csv` | kamera id -> IP (10 kamera to'ldirilgan) |
| `deploy/run_lesson_test.sh` | dars sinovi: davomat + 2 video + CSV |
| `deploy/cleanup.sh` | disk: --check/--apply/--install-cron |
| `deploy/build_engines.sh` | TensorRT engine build |
| `deploy/server_setup.sh` | yangi serverni noldan tayyorlash |
| `deploy/ERTAGA_10V.md` | ertangi 10-V test bosqichma-bosqich |
| `apps/cameras/management/commands/export_ds_sources.py` | sources.json generator (hls/rtsp) |
| `apps/cameras/management/commands/ptz_control.py` | PTZ boshqaruv |
| `JAMI_3.md` | avgustdagi 6 bug tafsiloti |
| `CLAUDE.md` | umumiy loyiha konteksti |
