# macOS'da davom etish — holat fayli

Yozilgan: 2026-08-25 kech. Muallif: Claude (Ubuntu serverdagi sessiya).

**Bu fayl kim uchun:** Aliyer macOS'da Claude Code ochganda Claude SHU FAYLNI
va [CLAUDE.md](CLAUDE.md) ni birinchi o'qisin. Bu yerda oxirgi sessiyaning
holati va ertangi ish rejasi.

---

## Claude'ga (macOS sessiyasi uchun qoidalar)

Sen shu loyihaning davomini olib borasan. Ubuntu serverdagi sessiyada
kelishilganlar:

1. Til — o'zbek (lotin), straight apostrof. Kod ichida emoji yo'q, kommentariy
   faqat WHY.
2. **Ishlab turgan tizimni buzmaslik** — mavjud kodga tegma, yangi narsa
   alohida fayl/skript bo'lsin.
3. **Muammolarni OLDINDAN aytish** — Aliyer talabi: "kelajakda muammo bo'ladi"
   deganlarini ish boshlanmasdan ayt.
4. **SKUD push-only** — yuborilgan davomat QAYTMAYDI. Sinovda har doim
   izolyatsiya (`SKUD_API_BASE_URL=http://127.0.0.1:9`). 2026-08-20 da 72 ta
   yolg'on davomat prod'ga ketgan — ikkinchi marta bo'lmasin.
5. macOS'da GPU pipeline ISHLAMAYDI (DeepStream = NVIDIA). macOS'dan kod
   yozasan, commit/push qilasan; ishga tushirish faqat Ubuntu serverda
   (`git pull` bilan oladi).

---

## Hozirgi holat (2026-08-25)

**Tizim to'liq bir buyruqqa keltirildi** — `deploy/start.sh`:

```bash
bash deploy/start.sh hls  --threshold 0.50    # proxy orqali (internet kerak)
bash deploy/start.sh rtsp --threshold 0.50    # kamera IP ga to'g'ridan (lokal tarmoq)
bash deploy/start.sh rtsp --url "rtsp://admin:admin@IP/Streaming/Channels/101" --cameras 9
bash deploy/start.sh status                   # nima ishlayapti
bash deploy/start.sh stop                     # AI to'xtaydi, baza/web qoladi
```

Skript o'zi tekshiradi (disk, GPU, engine, baza, manbalar jonliligi) va
muammo bo'lsa BOSHLAMAYDI; ko'targach zanjirni tasdiqlaydi:
kadr -> Kafka -> consumer -> baza.

- `--threshold N` — qabul chegarasi; `.env` ga tegmaydi,
  `.threshold.override.yml` qatlamida saqlanadi; `--threshold reset` bekor qiladi.
- `--skud real | izolyatsiya` — SKUD rejimi; bermasangiz hozirgisi saqlanadi.
- Hozir: **chegara 0.50, SKUD IZOLYATSIYADA** (sinov holati).

**Disk o'zicha to'lmaydi** — `deploy/cleanup.sh`:
- docker-compose'ga log rotation qo'shildi (100 MB x 3 fayl har servisga)
- `cleanup.sh --install-cron` — 03:00 da: eski sinov videolari (7 kun),
  eski lock/track (30 kun), eski event base64 (7 kun), VACUUM
- Davomat natijalari va etalonlar HECH QACHON o'chirilmaydi

## Ertangi test — 10-V sinf

To'liq qo'llanma: [deploy/ERTAGA_10V.md](deploy/ERTAGA_10V.md).

- 10-V: 40 talaba, 38 tasi etalonli. Ikkitasi SKUD'da rasmsiz — TANILMAYDI
  (Abdug'anieva Fotima, Ермаков Герман) — bu xato emas, oldindan ma'lum.
- Dars jadvali SKUD'da yo'q — `run_lesson_test.sh` vaqtinchalik yozuv yaratadi:

```bash
bash deploy/run_lesson_test.sh --camera-id <XONA_ID> --class 10-V --subject Tarix --duration 45
```

## RTSP haqida bilish shart bo'lganlar

1. **225-maktab kameralarining IP lari bazada YO'Q.** RTSP uchun yo
   `deploy/camera_ips.csv` ni to'ldirish (namuna ichida), yo tayyor link
   bilan `--url` ishlatish kerak.
2. Hikvision yo'llari: `/Streaming/Channels/101` = asosiy oqim (1080p),
   `102` = kichik oqim (past sifat). **Yuz tanish uchun 101 ishlatilsin** —
   102 da uzoq partadagi yuz 30-40 px bo'lib tanilmaydi.
3. Server kamera tarmog'ida bo'lishi shart: `ip a | grep 192.168`
   (yoki maktab tarmog'i qanday bo'lsa). Aks holda skript `554 YOPIQ` deb
   to'g'ri to'xtaydi.
4. 64-maktab (10.144.0.x) — faqat VPN orqali, VPN hali ulanmagan
   (403 xato, protokol noma'lum). PTZ ham proxy orqali O'TMAYDI — faqat
   to'g'ridan IP bilan (`ptz_control.py`).

## Bilib turish kerak bo'lgan xavflar

- **web image eski bo'lishi mumkin.** `export_ds_sources --mode rtsp` yangi
  kod — u web konteyner ICHIDA ishlaydi. Agar serverda `start.sh rtsp`
  "unrecognized arguments: --mode" desa: image qayta build qilinmagan.
  Yechim: `docker compose build web && docker compose up -d web` (~20 daq)
  YOKI rebuild kutmasdan `--url` rejimi (u bazasiz ishlaydi, eski image bilan ham).
- **Kernel yangilansa GPU yo'qoladi** (DKMS proprietary modul open'ni bosadi):
  `sudo apt install -y linux-modules-nvidia-595-open-$(uname -r)`
- **docker cp ishlatma** — konteyner recreate bo'lganda fayl yo'qoladi.
- Compose'da `ports` qatlamlar orasida BIRLASHADI — override uchun `!override`.

## Fayllar xaritasi (bu sessiyada yaratilgan/o'zgargan)

| Fayl | Nima |
|---|---|
| `deploy/start.sh` | bir buyruq: hls/rtsp/status/stop, threshold, skud rejimi |
| `deploy/cleanup.sh` | disk: check/apply/install-cron |
| `deploy/ERTAGA_10V.md` | ertangi test qo'llanmasi |
| `deploy/camera_ips.csv` | RTSP IP jadvali (namuna, to'ldirilmagan) |
| `deploy/run_lesson_test.sh` | dars sinovi: davomat + 2 video + CSV |
| `apps/cameras/management/commands/export_ds_sources.py` | +rtsp rejim, +ip-map |
| `apps/cameras/management/commands/ptz_control.py` | PTZ boshqaruv (7 format) |
| `docker-compose.yml` | +log rotation (x-logging anchor) |
