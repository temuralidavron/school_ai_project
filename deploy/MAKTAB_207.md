# 207-maktab — o'rnatish rejasi

Yozilgan: 2026-08-27, SKUD API dan jonli tekshirilgan. Umumiy tartib:
[YANGI_MAKTAB.md](YANGI_MAKTAB.md). Konveyer 49-maktab bilan bir xil —
[MAKTAB_49.md](MAKTAB_49.md) 4-bo'lim (A/B/C), faqat quyidagi raqamlar bilan.

## 0. Identifikator (jonli tasdiqlangan)

| Narsa | Qiymat |
|---|---|
| SKUD `org_id` | **24** |
| INN | **300424286** |
| Manzil | region=1 (Toshkent shahar), district=2 (Mirzo Ulug'bek tumani) |
| `.env` | `BOT_ORG_ID=24` |

Sync buyrug'i (INN 300424286 chiqishi SHART):

```bash
docker compose exec web python3.14 manage.py sync_organizations --region-id 1 --district-id 2 --check 24
```

## 1. Ma'lumot holati (2026-08-27)

- Talaba: **146**, rasmli **144 (99%)**
- Sinflar: 6 · Xonalar: 7
- Bugungi jadval: 0 — ma'muriyat SKUD ga jadval kiritsin (busiz davomat yozilmaydi)

**Rasmsiz 2 talaba (TANILMAYDI — ma'muriyatga oldindan):**

| Sinf | Talaba |
|---|---|
| 10-A | Timofeyev Sergey |
| 10-B | Timofeyev Vasiliy |

(aka-uka bo'lsa kerak — ikkalasining ham rasmi yo'q.)

## 2. Xona -> deviceId (kamera CSV uchun)

deviceId lar bu yerda ham IP EMAS — CSV 3-ustuni AYNAN shulardan bo'lsin:

| Xona | deviceId |
|---|---|
| 5-xona | `dev_207_5` |
| 19-xona | `dev_207_19` |
| 20-xona | `dev_207_20` |
| 21-xona | `dev_207_21` |
| 27-xona | `dev_207_27` |
| 28-xona | `dev_207_28` |
| Sport Zali | `dev_207_sz` |

CSV fayl: `deploy/cameras_207.csv` (format: `name;stream_url;skud_device_id`,
gitignore'da — ichida parol bo'ladi).

## 3. Qadamlar

MAKTAB_49.md 4-bo'lim bilan AYNAN bir xil, faqat almashtirish:
`--org-id 36` -> `--org-id 24` · `--check 36` -> `--check 24` ·
`BOT_ORG_ID=36` -> `24` · `cameras_49.csv` -> `cameras_207.csv` ·
`dev_49_XX` -> `dev_207_XX`.

Kutilgan natijalar: sync'da 6 sinf / 7 xona / 146 talaba; rasm ~720 ta
(144 x 5); embedding'dan keyin 144 talabada etalon.

MUHIM eslatmalar o'z kuchida: `docker compose up minio_init` (bucket'lar),
enrollment `AI_DET_SIZE=640`, birinchi start FAQAT `--skud izolyatsiya`,
server IP netplan bilan doimiy, papka nomi `school_ai_project`.
