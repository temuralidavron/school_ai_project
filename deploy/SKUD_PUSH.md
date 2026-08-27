# Davomat → SKUD push — alohida qism qo'llanmasi

Yozilgan: 2026-08-27. Davomat yozilgandan keyin SKUD (`edu.devel.uz`) ga
avtomatik yuborib turish tizimi: qanday ishlaydi, qanday yoqiladi, qanday
kuzatiladi. Kod tayyor — bu hujjat boshqarish va tekshirish uchun.

---

## 1. Zanjir (hammasi avtomatik)

```
yuz tanildi (accept >= chegara)
   -> AttendanceLockService     bir darsda bir talaba = 1 marta (lock)
   -> LessonAttendance          bazaga yoziladi (mahalliy panel shuni ko'rsatadi)
   -> SkudAttendancePushService DARHOL yuboriladi (AI_SKUD_PUSH_WORKERS=4 oqim)
        |- pushed        -> skud_pushed_at yoziladi, TAMOM
        |- skip:...      -> doimiy skip (talaba/xona yo'q) — qayta urinilmaydi
        |- failed        -> vaqtincha xato (internet uzuq...) — navbatda qoladi
   -> cron har 5 daqiqada: retry_skud_push --limit 200
        internet qaytishi bilan navbatdagilar ketadi — HECH NARSA YO'QOLMAYDI
```

Qo'shimcha cron ishlari: har kuni 00:30 da `sync_schedule --today-and-tomorrow`
(ertangi dars jadvali SKUD dan olinadi), har 10 daq `mark_absent`.

## 2. Push bo'lishi uchun 4 shart

| # | Shart | Bo'lmasa nima bo'ladi |
|---|---|---|
| 1 | `decision=accepted` (>= chegara 0.50) | review/rejected yuborilmaydi (to'g'ri) |
| 2 | Kamera<->xona bog'langan (`Camera.skud_device_id` = xona `deviceId`) | `skip:no_classroom_for_camera` |
| 3 | SKUD da HAQIQIY dars jadvali (shu xona, shu vaqt) | davomat umuman yozilmaydi |
| 4 | SKUD rejimi `real` | izolyatsiyada bazada qoladi, tashqariga chiqmaydi |

## 3. Rejimni boshqarish

```bash
bash deploy/start.sh status                     # hozirgi rejim ko'rinadi
bash deploy/start.sh rtsp --skud real           # HAQIQIY push YOQISH
bash deploy/start.sh rtsp --skud izolyatsiya    # sinov (tashqariga chiqmaydi)
```

**2026-08-27 tuzatildi:** izolyatsiya endi `kafka_consumer` BILAN BIRGA
`cron` ni ham qamraydi. Avval cron real URL da qolardi va har 5 daqiqada
retry qilib **sinov davomatini prodga oqizardi** — 2026-08-20 dagi 72 ta
yolg'on yozuv katta ehtimol shu yo'ldan ketgan. Endi bu yo'l yopiq.

Izolyatsiyada `sync_schedule` cron'i ham SKUD ga bora olmaydi (jadval
yangilanmaydi) — bu sinov rejimida normal; `--skud real` hammasini qaytaradi.

## 4. Kuzatish buyruqlari

```bash
# Navbat holati: nechta yuborildi / kutyapti / doimiy skip
docker compose exec -T web python3.14 manage.py shell --no-imports <<'PY'
from apps.attendance.models import RecognitionEvent as E
from django.utils import timezone
bugun = E.objects.filter(recognized_at__date=timezone.localdate(), decision="accepted")
print("bugun accepted:", bugun.count())
print("  pushed:", bugun.filter(skud_pushed_at__isnull=False).count())
print("  navbatda (retry):", bugun.filter(skud_pushed_at__isnull=True)
      .exclude(skud_push_error__startswith="skip:").count())
for r in (bugun.filter(skud_pushed_at__isnull=True)
          .values_list("skud_push_error", flat=True).distinct()[:8]):
    print("  sabab:", r)
PY

# Qo'lda qayta yuborish (cron kutmasdan) / faqat ko'rish:
docker compose exec web python3.14 manage.py retry_skud_push --dry-run
docker compose exec web python3.14 manage.py retry_skud_push --limit 200

# Cron ishlayaptimi:
docker exec school_ai_cron tail -20 /app/logs/cron.log
```

## 5. Tez-tez uchraydigan `skip:` sabablari

| Sabab | Yechim |
|---|---|
| `skip:no_classroom_for_camera` | `Camera.skud_device_id` xona `deviceId` siga mos emas — RTSP_MAKTAB.md 5-bo'lim |
| `skip:no_student` | Talaba bazada yo'q — `sync_full` qayta bajaring |
| jadval yo'q (davomat yozilmagan) | SKUD da dars jadvali kiritilsin — bu maktab ma'muriyati ishi |

## 6. Maktabda birinchi REAL push kuni — tartib

1. Ertalab: `bash deploy/start.sh status` — SKUD rejimi, kameralar OK
2. SKUD da bugungi jadval borligini tekshiring (4-bo'lim scripti yoki
   `get_today_schedule`) — bo'sh bo'lsa push baribir ishlamaydi
3. `bash deploy/start.sh rtsp --skud real`
4. Birinchi dars o'tgach 4-bo'limdagi navbat holatini qarang:
   `pushed` soni o'sayotgan bo'lsa — tizim ishlayapti
5. `navbatda (retry)` ko'payib borsa — internet/SKUD token muammosi,
   `docker logs school_ai_kafka_consumer | grep -i skud` ni qarang.
   Internet qaytsa navbat o'zi bo'shaydi, yozuvlar yo'qolmaydi.

**QOIDA (o'zgarmas): sinov = izolyatsiya. Soxta jadval bilan real push
HECH QACHON.** Yuborilgan davomat qaytmaydi.
