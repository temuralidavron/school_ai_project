# 225-maktab serverida jonli test — to'liq tartib (0 dan)

> Yozilgan: 2026-08-21. Maqsad: ertangi test XATOSIZ o'tishi.
> Har qadamda KUTILGAN NATIJA yozilgan — u chiqmasa TO'XTANG va keyingi
> qadamga o'tmang. "Xato bo'lsa" bo'limi har qadamning ostida.
>
> O'tgan safargi uzilishning sababi: eski `cameras` va yangi `ds3` bir
> kameraga IKKI ulanish ochardi + qayta ulanish halqasi. Bu endi tuzatilgan
> (cameras profil ostida) — lekin faqat git pull qilingandan keyin!

---

## 0-QADAM: OLIB BORISH KERAK

- [ ] USB disk: `~/Desktop/school_ai_images_<sana>.tar.gz` (~30 GB, ds3 + web)
      — bu ds3 image; maktabda NGC dan 36.8 GB yuklamaslik uchun
- [ ] Shu hujjat (git pull bilan ham keladi, lekin oflayn nusxa foydali)

---

## 1-QADAM: GPU (5 daqiqa) — ENG MUHIM TEKSHIRUV

```bash
nvidia-smi -L
```

**KUTILGAN:** `GPU 0: NVIDIA GeForce RTX 5080`

**Xato bo'lsa** (`driver not loaded` / `No devices were found`):
kernel yangilangan, open modul yangi kernelga o'rnatilmagan. Tuzatish:
```bash
sudo apt install -y linux-modules-nvidia-595-open-$(uname -r)
sudo modprobe nvidia && sudo modprobe nvidia_uvm && nvidia-smi -L
# ishlamasa: sudo reboot, keyin qayta nvidia-smi -L
```

**KEYIN ALBATTA — kelajak himoyasi** (dev mashinada 2 marta qaytdi shu muammo):
```bash
sudo apt install -y linux-modules-nvidia-595-open-generic-hwe-24.04
```
Bu metapaket har kernel yangilanishida open modulni AVTOMATIK o'rnatadi.

**Docker ichidan ham tekshiring:**
```bash
docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi
```
**KUTILGAN:** RTX 5080 jadvali. Bu chiqmasa GPU bilan hech narsa ishlamaydi.

---

## 2-QADAM: Kodni yangilash (5 daqiqa)

```bash
cd ~/school_ai_project
git fetch origin && git checkout -- . && git pull origin deepstream8-migration
git log --oneline -1
```

**KUTILGAN:** `afd2f41 Soddalashtirish: bitta yo'l (DeepStream)...` yoki yangiroq.

Bu pull bilan keladi: cameras profil ostida (ikki ulanish muammosi yo'q),
sozlamalar moslashtirilgan, run_lesson_test tuzatishlari, shu hujjat.

```bash
docker compose build web && docker compose up -d
docker compose config --services
```

**KUTILGAN:** build ~15-60s (kesh bor). Servislar ro'yxati:
`cron db minio minio_init web` — **cameras BO'LMASLIGI KERAK** (bu to'g'ri!).

---

## 3-QADAM: ds3 image (USB dan, ~15 daqiqa)

```bash
docker images | grep ds3
```

**Bor bo'lsa** (38.1GB) — o'tkazib yuboring. **Yo'q bo'lsa:**
```bash
# USB ni ulang, faylni toping (masalan /media/user01/USB/...)
gunzip -c /media/*/school_ai_images_*.tar.gz | docker load
docker images | grep -E "school_ai"
```

**KUTILGAN:** `school_ai_ds3:latest 38.1GB` va `school_ai:latest 25.1GB`.

---

## 4-QADAM: TensorRT engine (2 daqiqa)

Engine GPU ga bog'langan — maktab serverida qurilishi shart:
```bash
ls deepstream_v3/engines/det_10g_1280_fp16.engine 2>/dev/null || bash deploy/build_engines.sh
```

**KUTILGAN:** `PASSED TensorRT.trtexec` + `TAYYOR: ... 11.2 MB` (~42 soniya).

**Xato bo'lsa** (`Network And Config setup failed`): skript eski — 2-qadam
(git pull) bajarilmagan.

---

## 5-QADAM: Ma'lumot tekshiruvi (5 daqiqa)

```bash
docker compose exec -T web python3.14 manage.py shell -c "
from apps.integrations.models import ExternalStudent
from apps.face_data.models import StudentEmbedding, EnrollmentPhoto
from django.db.models import Count
n = ExternalStudent.objects.filter(organization__organization_id=16).count()
em = StudentEmbedding.objects.filter(student__organization__organization_id=16).values('student_id').distinct().count()
st = dict(EnrollmentPhoto.objects.filter(student__organization__organization_id=16).values_list('status').annotate(c=Count('id')))
print(f'talaba={n} etalonli={em} foto={st}')"
```

**KUTILGAN:** `talaba=325 etalonli=314 foto={'embedded': 1504}`

**Kam bo'lsa** (masalan etalonli=55 yoki no_face bor) — rasmlar/embedding
tugallanmagan. To'ldirish (~15 daqiqa):
```bash
until docker compose exec -T web python3.14 manage.py sync_full --org-id 16 --with-photos 2>&1 \
      | grep -q "'remaining_estimate': 0"; do echo -n "."; done; echo " RASMLAR OK"
docker compose exec -T -e AI_DET_SIZE=640 web python3.14 manage.py \
    sync_all_organizations --org-id 16 --step embeddings --embed-limit 2000
```
**DIQQAT: `AI_DET_SIZE=640` SHART** — usiz 520 foto `no_face` bo'ladi
(o'lchangan). Yakunda yuqoridagi tekshiruvni qaytaring.

---

## 6-QADAM: Kameralar (10 daqiqa)

### 6a. DB ga qo'shish
```bash
docker compose exec -T web python3.14 manage.py shell -c "
from apps.cameras.models import Camera
print('kameralar:', Camera.objects.filter(is_active_stream=True).count())"
```
`0` chiqsa:
```bash
docker compose exec -T web python3.14 manage.py add_cameras --org-id 16 \
    --csv deploy/cameras_225.csv --activate
```
**KUTILGAN:** 10 kamera qo'shildi.

### 6b. Xona bog'lanishi (SKUD push ishlashi uchun SHART)
```bash
docker compose exec -T web python3.14 manage.py sync_full --org-id 16
docker compose exec -T web python3.14 manage.py shell -c "
from apps.integrations.models import ExternalClassroom
q = ExternalClassroom.objects.filter(organization__organization_id=16)
print('xonalar:', q.count(), '| kamerasiz:', q.filter(camera__isnull=True).count())"
```
**KUTILGAN:** `xonalar: 10 | kamerasiz: 0`. Kamerasiz > 0 bo'lsa —
o'sha xonalarda SKUD push `skip:no_classroom_for_camera` bo'ladi.

### 6c. Kamera OQIMI tirikmi (pipeline'dan OLDIN!)
```bash
for c in cam16_1 cam16_2 cam16_9; do
  printf "  %-10s: " "$c"
  timeout 10 curl -s -o /dev/null -w "%{http_code}\n" -L "https://edu-api.devel.uz/$c/index.m3u8"
done
```
**KUTILGAN:** hammasi `200`.

**MUHIM OGOHLANTIRISH — gap.mp4 bug'i:** kamera oqim bermasa (bo'sh xona,
o'chiq kamera) HLS playlistda `gap.mp4` paydo bo'ladi va pipeline JIM O'LADI:
konteyner `running` ko'rinadi, lekin kadr 0, GPU 0%. Belgisi:
`docker logs school_ai_ds3 | grep gap.mp4`. Shuning uchun testni BOLALAR
XONada, KAMERA YONIQ paytda boshlang. Server maktab tarmog'ida bo'lgani
uchun lokal RTSP ham variant — lekin u sinalmagan, HLS bilan boshlang.

---

## 7-QADAM: Pipeline ishga tushirish (5 daqiqa)

```bash
docker compose exec -T web python3.14 manage.py export_ds_sources --org-id 16 \
    --out /app/logs/sources.json
cp logs/sources.json deepstream_v3/configs/sources.json
cat deepstream_v3/configs/sources.json      # 10 kamera URL ko'rinsin

docker compose --profile deepstream up -d
sleep 40
docker logs school_ai_ds3 2>&1 | grep -viE "gst-plugin|WARNING" | tail -10
```

**KUTILGAN:** `sources.json: 10 manba`, `deserialized trt engine`,
va ~30-60s dan keyin `frame# ... fps` qatorlari.

**Tekshirish — 3 ta belgi birga bo'lsin:**
```bash
docker logs school_ai_ds3 2>&1 | grep -E "frame#" | tail -2   # kadr oqyapti
nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader  # GPU > 0%
docker logs school_ai_kafka_consumer 2>&1 | tail -5           # xabar kelyapti
```

**Kadr yo'q bo'lsa:** `docker logs school_ai_ds3 | grep -iE "gap.mp4|404|error"`
— gap.mp4 chiqsa kamera oqim bermayapti (6c ga qarang).

---

## 8-QADAM: DAVOMAT TESTI

**DIQQAT: bu HAQIQIY SKUD PUSH — edu.devel.uz ga yozadi, QAYTARIB BO'LMAYDI.**
Bolalar yig'ilgan, dars belgilangan holatda bajaring.

Jadval bo'lmasa (ta'til) — vaqtinchalik dars:
```bash
docker compose exec -T web python3.14 manage.py setup_test_lesson \
    --org-id 16 --class-name 9-V --camera-id <KAMERA_ID> --duration 45 --subject "Tarix"
```
(`<KAMERA_ID>` — bolalar yig'ilgan xona kamerasi; 6a ro'yxatidan)

Kuzatish: `http://127.0.0.1:8000/monitoring/live/<KAMERA_ID>/`
(boshqa kompyuterdan kerak bo'lsa: share qatlami, SINOV_QOLLANMA.md 3-bo'lim)

Har 30s davomatni ko'rish:
```bash
docker compose exec -T web python3.14 manage.py shell -c "
from apps.attendance.models import LessonAttendance
from django.utils import timezone
print('davomat:', LessonAttendance.objects.filter(schedule__date=timezone.now().date()).count())"
```

Test tugagach — hisobot va tozalash:
```bash
docker compose exec -T web python3.14 manage.py lesson_report --schedule-id <ID> --subject "Tarix"
docker compose exec -T web python3.14 manage.py setup_test_lesson \
    --org-id 16 --class-name 9-V --camera-id <KAMERA_ID> --cleanup
```

---

## AGAR HAMMASI YOMON KETSA — zaxira yo'l

Eski OpenCV yo'li saqlangan (bitta-ikki kamera uchun yetadi):
```bash
docker compose --profile deepstream down
docker compose --profile legacy up -d cameras
```
Bu sekin (14 fps) lekin ishlaydi — davomat mantiqi bir xil.

---

## XULOSA — vaqt rejasi

| Qadam | Vaqt | Kritiklik |
|---|---|---|
| 1. GPU | 5 daq | usiz hech narsa ishlamaydi |
| 2. git pull + build | 5 daq | usiz eski xatolar qaytadi |
| 3. ds3 image (USB) | 15 daq | usiz pipeline yo'q |
| 4. TensorRT engine | 2 daq | usiz pipeline ishga tushmaydi |
| 5. Ma'lumot | 5-20 daq | usiz hech kim tanilmaydi |
| 6. Kameralar | 10 daq | usiz manba yo'q |
| 7. Pipeline | 5 daq | |
| 8. Test | dars vaqti | |

Jami tayyorgarlik: **~45-60 daqiqa** (ma'lumot to'liq bo'lsa 30).
