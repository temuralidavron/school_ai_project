# Jonli dars sinovi — maktabda ishlatish qo'llanmasi

225-maktab (org_id=16). Bolalar bir xonaga yig'ilganda to'liq zanjirni sinash:
tanish -> davomat -> SKUD push -> CSV hisobot + ikki video (xom va AI).

Hamma buyruq `~/school_ai_project` ichida bajariladi.

---

## 0. Bir marta: kodni yangilash

```bash
cd ~/school_ai_project
git checkout -- Dockerfile          # local sed tuzatishi remote da bor
git pull origin deepstream8-migration
docker compose build web            # kesh bor, ~15 soniya
docker compose up -d web && sleep 25
docker compose exec -T web python3.14 manage.py help | grep -E "setup_test_lesson|lesson_report"
```

Oxirgi buyruq ikkala nomni ko'rsatsa — kod tayyor.

---

## 1. Bir marta: ma'lumot tayyorlash (~15 daqiqa)

**Darsdan OLDIN tugashi shart** — busiz bolalar tanilmaydi.

```bash
# tashkilotlar (toza bazada birinchi qadam)
docker compose exec -T web python3.14 manage.py sync_organizations --check 16

# sinf / xona / talaba / jadval
docker compose exec -T web python3.14 manage.py sync_full --org-id 16 --with-photos

# rasmlar — partiyali, remaining 0 bo'lguncha (~8 daqiqa)
until docker compose exec -T web python3.14 manage.py sync_full --org-id 16 --with-photos 2>&1 \
      | grep -q "'remaining_estimate': 0"; do echo -n "."; done; echo " TUGADI"

# embedding — AI_DET_SIZE=640 SHART (1280 da sifatsiz rasmlarda yuz topilmaydi)
docker compose exec -T -e AI_DET_SIZE=640 web python3.14 manage.py \
    sync_all_organizations --org-id 16 --step embeddings --embed-limit 2000
```

Tekshirish — **etalonli=314** bo'lishi kerak (325 talabadan 11 tasida SKUD da rasm yo'q):

```bash
docker compose exec -T web python3.14 manage.py shell -c "
from apps.face_data.models import StudentEmbedding, EnrollmentPhoto
from apps.integrations.models import ExternalStudent
from django.db.models import Count
n=ExternalStudent.objects.filter(organization__organization_id=16).count()
em=StudentEmbedding.objects.filter(student__organization__organization_id=16).values('student_id').distinct().count()
st=dict(EnrollmentPhoto.objects.filter(student__organization__organization_id=16).values_list('status').annotate(c=Count('id')))
print(f'talaba={n} etalonli={em} foto={st}')"
```

`no_face` chiqsa — embedding `AI_DET_SIZE=640` siz bajarilgan, yuqoridagi buyruqni qayta bajaring.

---

## 2. SINF va KAMERA ni tanlash

### Qaysi sinflar bor va nechta bolada etalon bor

```bash
docker compose exec -T web python3.14 manage.py shell -c "
from apps.integrations.models import ExternalClass, ExternalStudent
from apps.face_data.models import StudentEmbedding
for k in ExternalClass.objects.filter(organization__organization_id=16).order_by('class_name'):
    j = ExternalStudent.objects.filter(class_obj=k).count()
    e = StudentEmbedding.objects.filter(student__class_obj=k, is_active=True).values('student_id').distinct().count()
    print(f'  {k.class_name:8s} jami={j:3d}  etalonli={e:3d}')"
```

225-maktabda 9-sinflar: **9-A** (21 bola), **9-B** (38), **9-V** (28).

### Qaysi kameralar bor va qaysi xonaga bog'langan

```bash
docker compose exec -T web python3.14 manage.py shell -c "
from apps.cameras.models import Camera
from apps.integrations.models import ExternalClassroom
for c in Camera.objects.all().order_by('id'):
    r = ExternalClassroom.objects.filter(camera_id=c.id).first()
    print(f'  camera_id={c.id:3d}  {(c.name or \"\")[:26]:26s}  xona={r.class_room_name if r else \"BOG_LANMAGAN\"}')"
```

**MUHIM:** kamera `xona=BOG'LANMAGAN` bo'lsa, SKUD push ishlamaydi
(`skip:no_classroom_for_camera`). Bog'lanish `Camera.skud_device_id` orqali
`sync_full` da avtomatik bo'ladi.

---

## 3. SINOVNI ISHGA TUSHIRISH

Bitta buyruq — hammasini o'zi qiladi:

```bash
bash deploy/run_lesson_test.sh --camera-id 3 --class 9-A --subject "Tarix" --duration 45
```

**Parametrlarni xohlagancha o'zgartiring:**

| Parametr | Nima | Misol |
|---|---|---|
| `--class` | sinf nomi | `9-A`, `9-B`, `9-V`, `10-A` |
| `--camera-id` | 2-bo'limdagi ro'yxatdan | `3`, `5`, `7` |
| `--subject` | fan nomi (hisobotga yoziladi) | `"Tarix"`, `"Matematika"` |
| `--duration` | daqiqa | `45`, `20`, `10` |

Misollar:
```bash
# 9-B sinfi, boshqa kamera, Matematika, 20 daqiqa
bash deploy/run_lesson_test.sh --camera-id 5 --class 9-B --subject "Matematika" --duration 20

# 9-V, 10 daqiqalik qisqa sinov
bash deploy/run_lesson_test.sh --camera-id 3 --class 9-V --subject "Fizika" --duration 10
```

Skript nima qiladi:
1. Vaqtinchalik dars yozuvi yaratadi (hozirgi vaqtdan `--duration` gacha)
2. AI pipeline'ni jonli kamera bilan ko'taradi
3. Ikki video yozadi — **xom** (kameradan) va **AI** (bbox/ism belgilari bilan)
4. Har 30 soniyada davomat sonini ko'rsatib turadi
5. Tugagach hammasini to'xtatadi, SKUD navbatini yuboradi, CSV hisobot chiqaradi

**Erta tugatish:** `Ctrl+C` — xavfsiz to'xtaydi, videolar to'g'ri yopiladi,
hisobot baribir chiqadi.

**Jonli kuzatish** (boshqa terminal yoki brauzer):
```
http://127.0.0.1:8000/monitoring/live/<camera-id>/
http://127.0.0.1:8554/mjpeg/0
```

---

## 4. NATIJALAR

Hammasi `logs/lesson_test/<sana_vaqt>/` papkasida:

| Fayl | Nima |
|---|---|
| `hisobot.csv` | Kim keldi, qachon, qanday ball, SKUD ga ketdimi, etaloni bormi |
| `xom_video.mp4` | Kameradan to'g'ridan, AI belgilarisiz |
| `ai_video.mp4` | Bbox, track ID, tanilgan ism bilan |

Ko'rish:
```bash
ls -la logs/lesson_test/*/
column -s, -t < logs/lesson_test/*/hisobot.csv | head -30
```

Hisobotni qayta chiqarish (schedule_id skript boshida ko'rsatiladi):
```bash
docker compose exec -T web python3.14 manage.py lesson_report --schedule-id 12 --subject "Tarix"
```

---

## 5. SINOVDAN KEYIN — test darsini o'chirish

Sinov tugagach vaqtinchalik dars yozuvini olib tashlang, aks holda u haqiqiy
jadvalga aralashadi:

```bash
docker compose exec -T web python3.14 manage.py setup_test_lesson \
    --org-id 16 --class-name 9-A --camera-id 3 --cleanup
```

**Eslatma:** SKUD ga yuborilgan davomat qaytarilmaydi — SKUD API push-only,
retract endpoint yo'q. Ya'ni sinov davomati `edu.devel.uz` da qoladi.

---

## 6. Muammo bo'lsa

**Pipeline ko'tarilmadi**
```bash
docker logs school_ai_ds3_run 2>&1 | tail -20
```
Ko'p uchraydigan sabab: TensorRT engine yo'q. Tuzatish:
```bash
bash deploy/build_engines.sh
```

**Bolalar tanilmayapti (davomat 0)**
```bash
# 1. Sinfda etalon bormi
docker compose exec -T web python3.14 manage.py shell -c "
from apps.face_data.models import StudentEmbedding
print(StudentEmbedding.objects.filter(student__class_obj__class_name='9-A', is_active=True).values('student_id').distinct().count())"

# 2. Kadr oqyaptimi
docker logs school_ai_ds3_run 2>&1 | grep -E "frame#|fps" | tail -3

# 3. Consumer ishlayaptimi
docker compose --profile deepstream up -d kafka kafka_consumer
docker compose logs kafka_consumer --tail 20
```

**Video yozilmadi**
```bash
docker logs lesson_rec_raw 2>&1 | tail -10
docker logs lesson_rec_ai  2>&1 | tail -10
```

**SKUD ga ketmadi**
```bash
docker compose exec -T web python3.14 manage.py retry_skud_push --org-id 16 --limit 500
```
`skip:no_classroom_for_camera` chiqsa — kamera xonaga bog'lanmagan (2-bo'limga qarang).
