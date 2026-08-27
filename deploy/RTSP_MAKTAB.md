# Maktabda RTSP ga o'tish — 225-maktab (org 16)

Yozilgan: 2026-08-26; **shu kuni Aliyer maktabdagi jonli ulanish ma'lumotini
tasdiqladi** (quyida). Umumiy ishga tushirish: [DAVOM.md](../DAVOM.md).

---

## 0. TASDIQLANGAN ma'lumot (Aliyer, 2026-08-26)

Maktab serveri: kamera tarmog'i `10.144.4.249` (eno1, **vaqtinchalik IP —
reboot'da o'chadi, 6-bo'limga qarang**), Mikrotik LAN `192.168.1.101`,
internet/SKUD telefon hotspot orqali.

Kameralar: `admin/admin`, 1920x1080, yo'l **`/stream1`**
(masalan `rtsp://10.144.4.5:554/stream1`), web paneli `http://<IP>`.

| Xona | Kamera id | IP | MJPEG |
|---|---|---|---|
| 1-xona | 1 | 10.144.4.5 | :8554/mjpeg/0 |
| 2-xona | 2 | 10.144.4.6 | :8554/mjpeg/1 |
| 9-xona | 3 | 10.144.4.7 | :8554/mjpeg/2 |
| 10-xona | 4 | 10.144.4.3 | :8554/mjpeg/3 |
| 11-xona | 5 | 10.144.4.4 | :8554/mjpeg/4 |
| 13-xona | 6 | 10.144.4.10 | :8554/mjpeg/5 |
| 4-xona | 7 | 10.144.4.9 | :8554/mjpeg/6 |
| 3-xona | 8 | 10.144.4.8 | :8554/mjpeg/7 |
| 3a-xona | 9 | 10.144.4.11 | :8554/mjpeg/8 |
| 12-xona | 10 | 10.144.4.2 | :8554/mjpeg/9 |

Bu bazadagi `Camera.ip_address` (SKUD deviceId) bilan AYNAN mos — baza
TO'G'RI. Eski `camera_ips.csv` dagi `10.144.0.x` yozuvlar noto'g'ri bo'lib
chiqdi (fayl yangilandi, tarix izohda qoldi). `start.sh rtsp` defaulti ham
`/stream1` ga qaytarildi.

## 1. Manba ustuvorligi (bilib tur)

`bash deploy/start.sh rtsp` manbalarni shu tartibda oladi:

```
Camera.ip_address + Camera.path (baza)   <- USTUVOR
       ^
       | bo'sh bo'lsagina
deploy/camera_ips.csv + --rtsp-path (default /stream1)
```

[export_ds_sources.py:123](../apps/cameras/management/commands/export_ds_sources.py:123).
225-maktabda baza to'g'ri, shuning uchun nazariy jihatdan `bash deploy/start.sh rtsp`
darhol ishlashi kerak. Lekin `Camera.path` bazada bo'sh — yo'l defaultdan
olinadi. Boshqa maktabda (boshqa brend kamera) yo'l boshqa bo'lishi mumkin —
shuning uchun baribir avval zondlash tavsiya etiladi (2-bo'lim): u yo'lni
haqiqiy kadr o'qib aniqlaydi va bazaga yozadi.

## 2. Bitta buyruq — zondlash

Maktab serverida, kamera tarmog'ida:

```bash
bash deploy/rtsp_tayyorla.sh
```

Har nomzod IP uchun: 554-port -> **haqiqiy kadr o'qish** (8 ta RTSP yo'l
varianti, tasdiqlangan `/stream1` birinchi). Hisobot beradi,
bazaga hech nima yozmaydi.

IP lar butunlay noma'lum bo'lsa butun tarmoqni skanerlaydi:

```bash
bash deploy/rtsp_tayyorla.sh --scan 10.144.4
```

Login boshqa bo'lsa: `--user admin --pass PAROL`.

## 3. Bazaga yozish

Hisobot to'g'ri bo'lsa:

```bash
bash deploy/rtsp_tayyorla.sh --apply
bash deploy/start.sh rtsp --threshold 0.50
```

`--apply` faqat `ip_address`, `path`, `port`, `username`, `password` ni
yangilaydi. **`skud_device_id` ga TEGMAYDI** — kamera<->xona bog'lanishi
o'sha maydon orqali ishlaydi, u o'zgarsa SKUD push `skip:no_classroom_for_camera`
bilan to'xtaydi.

`add_cameras --csv` ISHLATMANG: u `stream_url` bo'yicha `update_or_create`
qiladi, ya'ni RTSP url bilan YANGI kamera qatorlari yaratadi. Bazada ikki
nusxa paydo bo'ladi va id lar siljiydi.

## 4. Ikki IP ham javob bersa

Skript o'zi tanlamaydi — `MUAMMO: cam N ... qaysi biri ekanini MJPEG da
ko'rib qo'lda tanlang` deb yozadi. Sabab: qaysi IP qaysi xona ekanini tarmoq
ayta olmaydi, taxmin qilish = davomatni boshqa sinfga yozish.

Tekshirish yo'li: bitta kamerani ko'taring va tasvirga qarang.

```bash
bash deploy/start.sh rtsp --url "rtsp://admin:admin@10.144.4.4:554/stream1" --cameras 5
# http://127.0.0.1:8554/mjpeg/0 — qaysi xona ekani ko'rinadi
```

## 5. Davomat yozilishi uchun SHART

RTSP ishlashi = kadr kelishi. Davomat yozilishi uchun yana ikkitasi kerak:

1. **Kamera<->xona bog'lanishi** — `Camera.skud_device_id` =
   `ExternalClassroom.device_id`. Tekshirish:

   ```bash
   docker compose exec -T web python3.14 manage.py shell --no-imports <<'PY'
   from apps.cameras.models import Camera
   from apps.integrations.models import ExternalClassroom, ExternalOrganization
   org = ExternalOrganization.objects.get(organization_id=16)
   for x in ExternalClassroom.objects.filter(organization=org).order_by("id"):
       cam = Camera.objects.filter(skud_device_id=x.device_id).first()
       print(x.class_room_name, x.device_id, "->", cam.id if cam else "YO'Q")
   PY
   ```

2. **Bugungi dars jadvali** — `ExternalSchedule` da `classroom` + bugungi sana
   + `start_at <= hozir <= end_at` ([services.py:107](../apps/attendance/services.py:107)).
   Jadval bo'lmasa: kadr keladi, yuz topiladi, tanish ishlaydi, lekin
   **davomat yozilmaydi va SKUD ga ham hech nima ketmaydi**.

   SKUD da jadval bor-yo'qligini tekshirish:

   ```bash
   docker compose exec -T web python3.14 manage.py shell --no-imports <<'PY'
   from apps.integrations.services import SkudClient
   r = SkudClient().get_today_schedule(16)
   print("SKUD jadval yozuvlari:", len(r.get("items", [])))
   PY
   ```

   Bo'sh bo'lsa (2026-08-26 da shunday edi) — SKUD da jadval yo'q.
   `run_lesson_test.sh` vaqtinchalik yozuv yaratadi.

## 6. XAVF: soxta jadval + real SKUD push

`run_lesson_test.sh` yaratgan vaqtinchalik jadval **SKUD da mavjud emas**.
Agar consumer real rejimda bo'lsa, tanilgan har bola mavjud bo'lmagan darsga
qatnashgan deb prodga yoziladi va **qaytarib bo'lmaydi**.
2026-08-20 dagi 72 ta yolg'on yozuv aynan shundan.

Qoida: **soxta jadval bilan sinov = izolyatsiya SHART.**

```bash
bash deploy/start.sh status                     # hozirgi SKUD rejimi ko'rinadi
bash deploy/start.sh rtsp --skud izolyatsiya    # bazaga yoziladi, tashqariga ketmaydi
bash deploy/start.sh rtsp --skud real           # faqat SKUD da haqiqiy jadval bo'lganda
```

## 6b. XAVF: server IP vaqtinchalik — reboot'da o'chadi

Aliyer tasdiqladi: kamera tarmog'idagi `10.144.4.249` **vaqtinchalik**
(qo'lda `ip addr add` bilan qo'yilgan). Server reboot bo'lsa kamera tarmog'i
YO'QOLADI — davomat jim to'xtaydi (pipeline SOURCE DOWN, hech kim sezmaydi).

Doimiy qilish (Ubuntu 24.04, netplan). Maska/interfeys nomini joyida
tekshirib moslang (`ip a`, `ip route`):

```bash
sudo tee /etc/netplan/60-cameras.yaml >/dev/null <<'YAML'
network:
  version: 2
  ethernets:
    eno1:
      dhcp4: false
      addresses:
        - 10.144.4.249/24      # kamera tarmog'i (maska joyida tekshirilsin!)
        - 192.168.1.101/24     # Mikrotik LAN
      # gateway/DNS faqat internet shu interfeysdan bo'lsa kerak.
      # Internet hotspot (Wi-Fi) orqali bo'lsa bu yerga gateway YOZMANG —
      # aks holda SKUD trafigi noto'g'ri yo'lga ketadi.
YAML
sudo netplan try     # 120s ichida tasdiqlanmasa o'zi qaytaradi (xavfsiz)
```

Tekshirish: `reboot` dan keyin `ip a | grep 10.144` chiqishi shart.

## 7. Tarmoq yo'q bo'lsa

`554 YOPIQ` — kamera tarmog'i yo'q. Tartib bilan:

```bash
ip a | grep 10.144          # server kamera tarmog'idami
ping 10.144.4.5             # kamera yoqilganmi
curl -I http://10.144.4.5   # veb-interfeys (RTSP manzili odatda o'sha yerda)
```

PTZ proxy orqali O'TMAYDI — faqat to'g'ridan IP:
`manage.py ptz_control --ip 10.144.4.5 --detect`
