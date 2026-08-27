# 49-maktab — borishdan oldin tayyorlangan reja

Yozilgan: 2026-08-27, uy serveridan SKUD API orqali oldindan tekshirildi.
Umumiy o'rnatish tartibi: [YANGI_MAKTAB.md](YANGI_MAKTAB.md). Bu fayl faqat
49-maktabga xos raqamlar va tuzoqlar.

## 0. DIQQAT — SKUD da "49" nomli IKKITA maktab bor

| org_id | Nomi | INN | Holati |
|---|---|---|---|
| **36** | **49-maktab** | **204903379** | 261 talaba, 10 xona — HAQIQIYSI SHU |
| 67 | 49-sonli umumiy o'rta ta'lim maktabi | 206915963 | 65 talaba, 0 rasm, 0 xona — BOSHQA maktab |

`.env` da `BOT_ORG_ID=36`. Serverda birinchi tekshiruv:

```bash
docker compose exec web python3.14 manage.py sync_organizations --check 36
# -> "org_id=36: 49-maktab (INN 204903379)" chiqishi SHART
```

## 1. Ma'lumot holati (2026-08-27 SKUD dan)

- Talaba: **261**, rasmli **254 (97%)** — 225-maktabdan ham yaxshi
- Sinflar: 10 · Xonalar: 10 (Sport zali, 15,16,17,24,25,32,34,35,36-xona)
- Bugungi jadval: 0 yozuv — **borishdan oldin ma'muriyat jadvalni SKUD ga
  kiritsin**, aks holda real davomat yozilmaydi (SKUD_PUSH.md 2-bo'lim)

**Rasmsiz 7 talaba (TANILMAYDI — ro'yxatni maktabga oldindan bering):**

| Sinf | Talaba |
|---|---|
| 9-A | Salohiddinov Saidaʼlohon |
| 9-B | Muxiddinov Shahinbek |
| 9-V | Turayeva Mashkura |
| 10-A | Baik Akbar |
| 10-B | To'raqulov Ulug'bek |
| 10-B | Abdumuminova Xusniya |
| 11-A | Xushvakova Parizoda |

## 2. MUHIM FARQ: deviceId bu yerda IP EMAS

225-maktabda xona `deviceId` = kamera IP edi. 49-maktabda esa:
`dev_49_sz`, `dev_49_15`, `dev_49_16`, `dev_49_17`, `dev_49_24`,
`dev_49_25`, `dev_49_32`, `dev_49_34`, `dev_49_35`, `dev_49_36` — mantiqiy
identifikatorlar. Oqibatlari:

- `setup_cameras_from_skud` ({ip} shablon) ISHLAMAYDI — ip o'rniga dev_49_x tushardi
- Bazadagi `Camera.ip_address` avtomatik to'lmaydi — IP larni joyida topamiz
- Kamera<->xona bog'lash uchun CSV da `skud_device_id` ustuni AYNAN
  `dev_49_XX` bo'lishi shart (`sync_full` shu orqali bog'laydi)

## 3. Maktabdagi kamera qadmlari (aynan shu tartibda)

```bash
# 1. IP larni topish (kamera tarmog'ida): 554-port skaner + haqiqiy kadr
bash deploy/rtsp_tayyorla.sh --org-id 36 --scan <kamera_tarmog'i, masalan 10.144.9>
#    Bazada org 36 kamerasi hali yo'q — natija "BOG'LANMAGAN: <ip> ..."
#    ro'yxati bo'ladi: tirik IP lar + ishlagan RTSP yo'l.

# 2. Qaysi IP qaysi xona? Bittalab ko'rib aniqlang:
bash deploy/start.sh rtsp --org-id 36 --url "rtsp://admin:admin@<IP>:554<yo'l>" --cameras 1
#    http://127.0.0.1:8554/mjpeg/0 da tasvir — qaysi xona ekani ko'rinadi.

# 3. CSV yozing: deploy/cameras_49.csv  (gitignore'da — parol bo'ladi)
#    Format: name;stream_url;skud_device_id
#    15-xona;rtsp://admin:admin@<IP>:554<yo'l>;dev_49_15
#    ...10 qator (Sport zali = dev_49_sz)

# 4. Bazaga qo'shish + xonaga bog'lash + ishga tushirish:
docker compose exec web python3.14 manage.py add_cameras --org-id 36 \
    --csv deploy/cameras_49.csv --activate
docker compose exec web python3.14 manage.py sync_full --org-id 36   # camera<->xona
bash deploy/start.sh rtsp --org-id 36 --skud izolyatsiya             # avval sinov!
```

Tekshiruv — har xonada kamera bog'langanmi (RTSP_MAKTAB.md 5-bo'lim
skripti, org=36). `skip:no_classroom_for_camera` chiqsa — CSV dagi
`dev_49_XX` noto'g'ri yozilgan.

## 4. MUKAMMAL KETMA-KETLIK

### A. UYDA — server yoningizda (internet bor, hammasi shu yerda qilinadi)

```bash
# A1. OS tayyorlash (drayver + docker + nvidia-container-toolkit; reboot so'rasa qiling)
bash deploy/server_setup.sh

# A2. Kod
git clone <repo> school_ai_project && cd school_ai_project

# A3. Image'lar (USB yoki eski serverdan scp bilan dist_images/ ko'chirilgan)
bash deploy/image_tarqatish.sh import <dist_images yo'li>
#    DeepStream shu yerda "o'rnatiladi" — u school_ai_ds3 image ichida.
#    GPU RTX 5080 bo'lsa TensorRT engine ham tayyor keladi.

# A4. Sozlama
cp .env.example .env && chmod 600 .env
#    To'ldiring: SECRET_KEY, DB/MinIO parollari, SKUD sirlari, BOT_ORG_ID=36

# A5. Baza
docker compose up -d db minio web
docker compose exec web python3.14 manage.py migrate
docker compose exec web python3.14 manage.py createsuperuser

# A6. SKUD ma'lumotlari (INN 204903379 chiqishi SHART):
docker compose exec web python3.14 manage.py sync_organizations --check 36
docker compose exec web python3.14 manage.py sync_full --org-id 36
docker compose exec web python3.14 manage.py sync_all_organizations --org-id 36 --with-photos
#    (remaining_estimate 0 bo'lguncha qayta-qayta — ~254 rasm, partiyali)

# A7. Etalonlar (enrollment DOIM 640 bilan!)
docker compose exec -e AI_DET_SIZE=640 web python3.14 manage.py build_all_embeddings --org-id 36
docker compose exec web python3.14 manage.py audit_enrollment --org-id 36
#    Kutilgan: ~254 talabada etalon. 7 rasmsiz — 1-bo'limdagi ro'yxat.

# A8. Umumiy sinov (kamerasiz, zanjir butunligini ko'rish uchun) — ixtiyoriy:
bash deploy/start.sh hls --org-id 36 --skud izolyatsiya --dry-run
```

Uyda A1-A7 tugagach serverda HAMMASI bor: kod, image'lar (DeepStream ichida),
modellar, 261 talaba, etalonlar. Maktabda faqat kamera + tarmoq qoladi.

### B. MAKTABDA — kamera va ishga tushirish

```bash
# B1. Tarmoq: serverga kamera tarmog'idan IP (keyin DOIMIY qiling —
#     RTSP_MAKTAB.md 6b netplan; vaqtinchalik IP reboot'da o'chadi!)

# B2. Kameralarni topish (554-port skaner + haqiqiy kadr):
bash deploy/rtsp_tayyorla.sh --org-id 36 --scan <tarmoq, masalan 10.144.9>

# B3. Har IP qaysi xona? Bittalab ko'rib chiqing:
bash deploy/start.sh rtsp --org-id 36 --url "rtsp://admin:admin@<IP>:554<yo'l>" --cameras 1
#    http://127.0.0.1:8554/mjpeg/0 — tasvirga qarab xonani aniqlang.
#    Bu faqat KO'RISH uchun (kamera hali bazada yo'q — davomat yozilmaydi).

# B4. deploy/cameras_49.csv yozing (name;stream_url;skud_device_id):
#    stream_url: proxy'da 49-maktab oqimi BO'LSA proxy URL yozing (HLS rejim
#    ham ishlaydi), BO'LMASA rtsp:// URL (faqat RTSP ishlaydi):
#      15-xona;https://edu-api.devel.uz/cam36_15;dev_49_15     <- proxy bor bo'lsa
#      15-xona;rtsp://admin:admin@<IP>:554<yo'l>;dev_49_15     <- bo'lmasa

# B5. Qo'shish + xonaga bog'lash:
docker compose exec web python3.14 manage.py add_cameras --org-id 36 --csv deploy/cameras_49.csv --activate
docker compose exec web python3.14 manage.py sync_full --org-id 36
bash deploy/rtsp_tayyorla.sh --org-id 36 --apply    # IP/yo'l/login bazaga

# B6. ISHGA TUSHIRISH (avval izolyatsiya!):
bash deploy/start.sh rtsp --org-id 36 --skud izolyatsiya
#    Skript o'zi tasdiqlaydi: kadr -> Kafka -> consumer -> baza.

# B7. Hammasi to'g'ri bo'lgach — REAL:
bash deploy/start.sh rtsp --org-id 36 --skud real
```

### C. REJIM ALMASHTIRISH — har biri BIR buyruq

```bash
bash deploy/start.sh rtsp --org-id 36     # RTSP: kamera IP ga to'g'ridan (<1s, internetsiz)
bash deploy/start.sh hls  --org-id 36     # HLS:  proxy orqali (internet kerak)
bash deploy/start.sh status               # hozir qaysi rejim, nima ishlayapti
bash deploy/start.sh stop                 # AI to'xtaydi (baza/web qoladi)
```

Har buyruq manbalarni qaytadan yig'adi va zanjirni qayta tasdiqlaydi —
qo'shimcha hech nima kerak emas. DIQQAT: `hls` faqat edu-api proxy'da
49-maktab kameralari mavjud bo'lsa ishlaydi (B4 dagi stream_url proxy
bo'lsa). Proxy'da yo'q bo'lsa — proxy ma'muridan qo'shishni so'rang;
ungacha yagona yo'l RTSP.

Birinchi real kun tartibi: [SKUD_PUSH.md](SKUD_PUSH.md) 6-bo'lim.
