# Yangi maktabga o'rnatish — to'liq tartib (10 000 maktab uchun shablon)

Har maktab = alohida server, alohida `org_id`, o'z kameralari. SKUD
(`edu.devel.uz`) umumiy. Bu hujjat 0 dan ishlaydigan davomatgacha bo'lgan
BARCHA qadamlarni beradi. 225-maktab (org 16) misolida sinalgan.

Vaqt: image to'plami bilan **~30-40 daqiqa** (to'plamsiz +40-60 daq build).

---

## 0. Oldindan kerak

| Narsa | Izoh |
|---|---|
| Server | Ubuntu 24.04, NVIDIA GPU (RTX 5080 sinalgan), 100+ GB bo'sh disk |
| `org_id` | SKUD dagi maktab raqami. Aniqlash: 4-qadamdagi `--check` |
| SKUD parollari | `SKUD_CLIENT_SECRET`, `SKUD_ACCESS_TOKEN` |
| Image to'plami | USB da `dist_images/` (bosh serverda `bash deploy/image_tarqatish.sh export` bilan yasaladi) |
| Kamera tarmog'i | Server kameralar bilan bitta tarmoqda (kabel) |

Server noldan bo'lsa (docker/nvidia yo'q): `bash deploy/server_setup.sh`.

## 1. Kod va image'lar

```bash
git clone <repo> school_ai_project && cd school_ai_project
bash deploy/image_tarqatish.sh import /media/usb/dist_images
```

Import: image'lar + buffalo_l modellari + onnx (internet KERAK EMAS).
GPU to'plamdagi bilan bir xil bo'lsa TensorRT engine ham tayyor; boshqa
bo'lsa `start.sh` o'zi quradi (~1-2 daq).

## 2. .env

```bash
cp .env.example .env && chmod 600 .env
```

Majburiy o'zgartirishlar: `SECRET_KEY` (yangi), `DB_PASSWORD`,
`MINIO_ACCESS_KEY/SECRET_KEY`, `SKUD_CLIENT_SECRET`, `SKUD_ACCESS_TOKEN`,
**`BOT_ORG_ID=<org_id>`**. `AI_ACCEPT_THRESHOLD=0.50` boshlang'ich —
sinovdan keyin sozlanadi.

## 3. Server IP ni DOIMIY qilish

Kamera tarmog'idagi IP qo'lda qo'yilgan bo'lsa reboot'da o'chadi va davomat
jim to'xtaydi. [RTSP_MAKTAB.md](RTSP_MAKTAB.md) 6b-bo'lim (netplan) —
**MAJBURIY qadam**, 225-maktabda ham shu muammo bor edi.

## 4. Baza va SKUD sync (birinchi marta, internet kerak)

```bash
docker compose up -d db minio web
docker compose exec web python3.14 manage.py migrate
docker compose exec web python3.14 manage.py createsuperuser

# TOZA BAZADA ENG BIRINCHI SKUD QADAMI — busiz sync_full yiqiladi:
docker compose exec web python3.14 manage.py sync_organizations --check <ORG_ID>
#   -> "org_id=N: <maktab nomi> (INN ...)" chiqishi SHART. Chiqmasa org_id noto'g'ri!

# Sinf -> xona -> talaba -> jadval:
docker compose exec web python3.14 manage.py sync_full --org-id <ORG_ID>

# Rasmlar PARTIYALI (bir chaqiruv ~20 ta) — remaining_estimate 0 bo'lguncha:
docker compose exec web python3.14 manage.py sync_all_organizations --org-id <ORG_ID> --with-photos
```

## 5. Embedding (etalon) yaratish

**MUHIM: enrollment uchun `AI_DET_SIZE=640`** (1280 da portret rasmlarda
yuz topilmay qoladi — [DEPLOY_14_MAKTAB.md](DEPLOY_14_MAKTAB.md) 7a):

```bash
docker compose exec -e AI_DET_SIZE=640 web python3.14 manage.py build_all_embeddings --org-id <ORG_ID>

# Tekshiruv — rasmsiz/etalonsiz talabalar soni:
docker compose exec web python3.14 manage.py audit_enrollment --org-id <ORG_ID>
```

**Rasmsiz talaba TANILMAYDI** — bu texnik emas, tashkiliy muammo (225 da
5%, 14-maktabda 33% edi). Ro'yxatni maktab ma'muriyatiga oldindan bering.

## 6. Kameralar

```bash
bash deploy/rtsp_tayyorla.sh --org-id <ORG_ID>            # zondlash (hisobot)
bash deploy/rtsp_tayyorla.sh --org-id <ORG_ID> --apply    # bazaga yozish
```

Zond har IP da 8 xil RTSP yo'lni haqiqiy kadr o'qib sinaydi, ishlaganini
`Camera` jadvaliga yozadi (IP/yo'l/port/login + faollashtirish). IP lar
noma'lum bo'lsa: `--scan 10.144.4` (554-port bo'ylab /24 skaner). Login
boshqa bo'lsa: `--user admin --pass PAROL`.

Kamera<->xona bog'lanishi SKUD `deviceId` orqali avtomatik (`sync_full`).
`deviceId` kamera IP siga mos kelmasa — SKUD ma'muriga xabar bering,
bog'lanishsiz davomat SKUD ga ketmaydi (`skip:no_classroom_for_camera`).

## 7. Ishga tushirish va sinov

```bash
# Avval IZOLYATSIYADA (SKUD ga hech nima ketmaydi):
bash deploy/start.sh rtsp --org-id <ORG_ID> --skud izolyatsiya

# Zanjir o'zi tasdiqlanadi: kadr -> Kafka -> consumer -> baza.
# Jonli ko'rish: http://127.0.0.1:8554/mjpeg/0
# Dars sinovi (vaqtinchalik jadval bilan — FAQAT izolyatsiyada!):
bash deploy/run_lesson_test.sh --camera-id <ID> --class <SINF> --duration 45
```

Natija to'g'ri bo'lgach (bolalar tanilyapti, xato yo'q) — real push:

```bash
bash deploy/start.sh rtsp --org-id <ORG_ID> --skud real
```

**QOIDA: SKUD da haqiqiy dars jadvali bo'lmagunча real push YOQILMAYDI**
(soxta jadval + real push = qaytarib bo'lmaydigan yolg'on davomat;
2026-08-20 da 72 ta shunday yozuv ketgan).

## 8. Yakuniy tekshirish ro'yxati

| # | Tekshiruv | Buyruq / belgi |
|---|---|---|
| 1 | GPU | `nvidia-smi` |
| 2 | Doimiy IP | reboot -> `ip a | grep 10.144` |
| 3 | Servislar | `bash deploy/start.sh status` |
| 4 | Talaba/etalon | `audit_enrollment` — etalonsizlar ro'yxati ma'muriyatga berildi |
| 5 | Kamera 100% | `rtsp_tayyorla.sh` hisobotida hamma kamera KADR OK |
| 6 | Xona bog'lanish | RTSP_MAKTAB.md 5-bo'lim skripti — hamma xonada kamera |
| 7 | Jadval | SKUD `get_today_schedule` bo'sh emas |
| 8 | Disk cron | `bash deploy/cleanup.sh --install-cron` (03:00 avto tozalash) |
| 9 | SKUD rejimi | `start.sh status` — kutilgan rejim (izolyatsiya/real) |

## Bilib turing (ko'lam bo'yicha ochiq masalalar)

- **Markaziy monitoring yo'q** — server o'lsa hech kim ko'rmaydi. Pipeline
  o'zini tiklaydi (SELF-RESTART), lekin GPU/disk/tarmoq muammosini hozircha
  joyida turib aniqlash kerak. Keyingi bosqich ishi.
- Kernel yangilanishi GPU drayverni sindirishi mumkin —
  [DAVOM.md](../DAVOM.md) "kutilayotgan muammolar" 1-band.
- 10k maktab sync bosimi SKUD API tomonda tekshirilmagan.
