# DAVOM — yangi Claude sessiyasi uchun to'liq kontekst

Yozilgan: 2026-08-25 kech, uy serverdagi sessiya yakunida.
**Bu faylni yangi ochilgan har qanday Claude sessiyasi (maktab serveri,
macOS, istalgan joy) BIRINCHI o'qisin.**

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

- Kameralar: 10 ta, `10.144.0.x`, login `admin/admin`, Hikvision.
  Yo'l: `/Streaming/Channels/101` (asosiy oqim, default).
  **102 ishlatma** — kichik oqim, yuzlar 30-40 px bo'lib TANILMAYDI.
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
bash deploy/start.sh rtsp --url "rtsp://admin:admin@IP/Streaming/Channels/101" --cameras 9
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
