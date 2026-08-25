# Ertangi sinov — 10-V sinf, 225-maktab

Sana: 2026-08-26 · tashkilot 16 · sinf 10-V

---

## 1. Bitta buyruq

```bash
cd ~/Desktop/school_full/school_ai_project

# HLS — proxy orqali (hozir ishlaydigan yo'l, internetga bog'liq)
bash deploy/start.sh hls --threshold 0.50

# RTSP — kamera IP ga to'g'ridan (kechikish <1s, internetsiz)
bash deploy/start.sh rtsp --threshold 0.50 --ip-map deploy/camera_ips.csv
```

Ikkalasi ham butun zanjirni ko'taradi:
kamera → DeepStream → Kafka → consumer → PostgreSQL → SKUD.

Skript o'zi tekshiradi va **muammo bo'lsa boshlamaydi**:
disk → GPU → TensorRT engine → baza/kafka → chegara → manbalar jonliligi →
yuk hisobi. Keyin zanjir butunligini tasdiqlaydi: kadr → Kafka → consumer → baza.

| Buyruq | Nima qiladi |
|---|---|
| `bash deploy/start.sh status` | hozir nima ishlayapti, disk holati |
| `bash deploy/start.sh stop` | AI pipeline to'xtaydi (baza/web qoladi) |
| `bash deploy/start.sh hls --dry-run` | hech nima ko'tarmaydi, faqat tekshiradi |
| `bash deploy/start.sh hls --cameras 9` | faqat bitta kamera |

### Chegara (threshold)

`--threshold` — qabul chegarasi. Past = ko'proq taniydi, lekin xato xavfi
ortadi (haykalni bolaga o'xshatish shundan). Yuqori = kam taniydi, ishonchli.

```bash
bash deploy/start.sh hls --threshold 0.45              # yumshoq
bash deploy/start.sh hls --threshold 0.55 --review 0.50  # qattiq
bash deploy/start.sh hls --threshold reset             # .env dagiga qaytadi
```

Chegara `.env` ga **yozilmaydi** — `.threshold.override.yml` qatlamiga
tushadi va keyingi ishga tushirishlarda ham saqlanadi.

### RTSP uchun kerak bo'ladigan narsa

225-maktab kameralarining IP lari bazada **yo'q** — RTSP shusiz ishlamaydi.
Maktabda IP larni to'ldiring: [deploy/camera_ips.csv](camera_ips.csv) ichida
namuna bor, izohni olib tashlab haqiqiy IP yozing. Yo'l brendga qarab
farq qiladi:

```bash
--rtsp-path /stream1                              # umumiy
--rtsp-path "/cam/realmonitor?channel=1&subtype=0"  # Dahua
--rtsp-path /Streaming/Channels/101               # Hikvision
```

Server kamera tarmog'ida bo'lishi shart (`ip a | grep 10.144` yoki `192.168`).

---

## 2. Dars sinovi (10-V)

```bash
bash deploy/run_lesson_test.sh --camera-id <XONA> --class 10-V \
     --subject Tarix --duration 45
```

Dars jadvali SKUD da yo'q — skript vaqtinchalik yozuv o'zi yaratadi.
Natija `logs/lesson_test/<sana>/` ichida: `hisobot.csv`, `xom_video.mp4`, `ai_video.mp4`.

Ctrl+C — istalgan payt xavfsiz to'xtatadi, hisobot baribir chiqadi.

**Kamera raqamini oldindan aniqlang** — 10-V qaysi xonada dars qiladi:

| id | xona | id | xona |
|---|---|---|---|
| 5 | 1-xona | 11 | 13-xona |
| 6 | 2-xona | 12 | 4-xona |
| 8 | 9-xona | 13 | 3-xona |
| 9 | 10-xona | 14 | 3a-xona |
| 10 | 11-xona | 15 | 12-xona |

---

## 3. Sinovdan OLDIN bilib qo'ying

**10-V: 40 talaba, 38 tasi tanilishi mumkin.**
Bu ikkisida SKUD da rasm yo'q — ertaga **tanilmaydi**, bu tizim xatosi emas:

- Abdug'anieva Fotima Zamirbekovna
- ЕРМАКОВ ГЕРМАН АЛЕКСАНДРОВИЧ

Qolgan 38 tasida 4-5 tadan etalon rasm bor — bu yaxshi ko'rsatkich.

**SKUD hozir IZOLYATSIYADA.** Ya'ni davomat bazaga yoziladi, lekin
`edu.devel.uz` ga **ketmaydi**. Sinov uchun to'g'ri holat.

Haqiqiy push kerak bo'lsa, sinovdan oldin:

```bash
docker compose up -d --force-recreate kafka_consumer
bash deploy/start.sh status        # "SKUD: https://edu.devel.uz" ko'rinsin
```

> Ogohlantirish: SKUD push-only — yuborilgan davomatni **qaytarib bo'lmaydi**.
> 2026-08-20 da 9-V ning 12 bolasi uchun 72 ta yolg'on davomat shunday ketgan.
> Sinov bo'lsa izolyatsiyada qoldiring.

---

## 4. Sinov paytida kuzatish

```
Jonli AI tasvir:  http://127.0.0.1:8554/mjpeg/0
Monitoring:       http://127.0.0.1:8000/monitoring/
```

Skript har 30 soniyada davomat sonini chiqaradi.

Tanish kam bo'lsa chegarani pasaytirib qayta urinib ko'ring:

```bash
bash deploy/run_lesson_test.sh --camera-id 9 --class 10-V --threshold 0.45
```

---

## 5. Disk to'lib qolmasligi

```bash
bash deploy/cleanup.sh --check          # nima joy yeyapti
bash deploy/cleanup.sh --apply          # tozalash
bash deploy/cleanup.sh --install-cron   # har kuni 03:00 avtomatik
```

Cron o'rnatilgan bo'lsa disk barqaror turadi: docker log 100 MB x 3 fayl
bilan cheklangan, sinov videolari 7 kundan keyin, oraliq baza yozuvlari
30 kundan keyin o'chadi. Davomat natijalari va etalon rasmlar hech qachon
o'chirilmaydi.

---

## 6. Nimadir ishlamasa

| Belgi | Sabab | Yechim |
|---|---|---|
| `start.sh` "disk kam" deydi | build cache to'lgan | `bash deploy/cleanup.sh --apply` |
| `nvidia-smi` ishlamaydi | kernel yangilangan, DKMS modul qaytgan | `sudo apt install -y linux-modules-nvidia-595-open-$(uname -r)` |
| "engine yo'q" | TensorRT fayllar o'chgan | `bash deploy/build_engines.sh` (~15 daq) |
| Konteyner tirik, kadr 0 | manba jim o'lgan (gap segment) | `start.sh` buni oldindan topadi; kamera qayta yoqing |
| RTSP "554 YOPIQ" | server kamera tarmog'ida emas | `ip a \| grep 10.144` — VPN/lokal ulanish kerak |
| Davomat bazada bor, SKUD da yo'q | consumer izolyatsiyada | `docker compose up -d --force-recreate kafka_consumer` |
