# F3c — Galereya boyitish: himoya to'plami bilan dry-run (dizayn)

> Sana: 2026-07-20. Holat: dizayn tasdiqlangan (Aliyer, 3 bo'lim bo'yicha).
> Kontekst: JAMI_2.md 1b-bo'lim (galereya tajribasi + zahar-sinov natijalari).
> Eslatma: F3 (Review UI) BEKOR qilindi — mavjud Django admin yetarli deb qaror qilindi.

## Maqsad

Kamera kadrlaridan olingan yuqori sifatli embeddinglarni o'quvchi galereyasiga
qo'shimcha shablon sifatida qo'shish — tanish ballini oshirish uchun (tajribada
shablonli bolalar balli +0.054). Zahar-sinov isbotlagan: himoyasiz qilib
BO'LMAYDI (1 noto'g'ri shablon = 121 yuzdan 3 xato qabul), shuning uchun butun
dizayn himoya to'plami atrofida qurilgan.

## Tanlangan yondashuv: C — Gibrid

Jonli oqim faqat nomzod yig'adi (JSONL), qo'shish qarori oflayn buyruqda.
Sabab: embedding faqat jonli oqimda qo'lda bo'ladi (sighting-jurnal va
RecognitionEvent'da saqlanmaydi); tanlov esa kun yakunida "eng yaxshisi"dan
bo'lishi kerak. Rad etilgan muqobillar: A (jonli darhol yozish) — auditsiz,
birinchi o'tgan olinadi; B (faqat batch) — saqlangan 7KB display-crop'dan qayta
embedding sifat riski.

## Arxitektura

```
kafka_consumer (jonli oqim, flag: GALLERY_CANDIDATES=1, default O'CHIQ)
   |  qaror "accepted" bo'lgan sighting
   v
Temir darvoza: score >= GALLERY_MIN_SCORE  +  margin >= GALLERY_MIN_MARGIN
             + yuz >= GALLERY_MIN_FACE px  +  Laplacian >= GALLERY_MIN_BLUR
   v
logs/gallery-candidates-YYYY-MM-DD.jsonl  (append-only, sighting_log uslubi:
   xato jim yutiladi, hot-path buzilmaydi, DB'ga tegilmaydi)
   qator: {ts, student_id, camera_id, schedule_id, score, margin,
           yuz o'lchami, blur, embedding[512], face_crop_b64}
   v
manage.py gallery_enrich --date YYYY-MM-DD [--apply | --rollback [--hard]]
   dry-run (default): har bola uchun eng yaxshi nomzod HISOBOTI
   --apply: StudentEmbedding yoziladi (source="camera", is_primary=False)
```

Muhim nuqtalar:
- Embedding Kafka xabaridan (EMB_POOL=3 o'rtacha, L2-norm) — qayta hisoblanmaydi.
- Darvoza qattiq — nomzod kam, JSONL ichida embedding + crop b64 hajm muammosi
  emas; jurnal o'z-o'zidan to'liq (audit shu yerdan, crop DB/MinIO'ga yozilmaydi).
- B5_ELIM bilan to'qnashuv yo'q: "top-1 locked bo'lsa tegilmaydi" qoidasi tufayli
  qabul qilingan bola top-1 bo'lib ko'rinaveradi — nomzod oqimi uzilmaydi.
- Har bola uchun maksimum 1 faol kamera-shablon. Ko'p-shablon (front+left+right)
  — F3b, bu ishga kirmaydi.
- Blur (Laplacian) faqat qolgan uch shart o'tgandagina hisoblanadi (kam va arzon).

## DB o'zgarishi (bitta migratsiya, face_data)

`StudentEmbedding`:
- `enrollment_photo` FK -> `null=True` (kamera-shablonda SKUD fotosi yo'q;
  sun'iy EnrollmentPhoto/ExternalStudentPhoto yaratilmaydi. `enrollment_photo`
  o'zi ForeignKey, lekin `EnrollmentPhoto.external_photo` -> ExternalStudentPhoto
  bog'lanishi OneToOne — sun'iy yozuv shu OneToOne'ni ham buzardi, shuning uchun
  FK'ni null qilish to'g'ri yechim).
- Yangi maydon `source`: `"enrollment"` (default — mavjud yozuvlar shundayligicha
  qoladi) yoki `"camera"`.
- Yangi maydon `source_meta` (JSON): {score, margin, camera_id, schedule_id,
  sana, jurnal_fayli}.

Yozish qoidalari (--apply):
- `is_primary=False` doim — kamera-shablon hech qachon asosiy etalon emas.
- Bitta faol kamera-shablon/bola: yaxshiroq nomzod kelsa eskisi `is_active=False`,
  yangisi yoziladi ("yaxshiroq bo'lsa almashtir" — idempotentlikni ham ta'minlaydi).
- HNSW indeksga avtomatik tushadi — qidiruv kodiga tegilmaydi.

Rollback (bir buyruq):
- `gallery_enrich --rollback` -> `filter(source="camera").update(is_active=False)`
  — qidiruvdan bir zumda chiqadi, iz qoladi.
- `--rollback --hard` -> delete. Jurnal fayllari qoladi — qayta apply mumkin.

## Himoya (2 devor)

1. Temir darvoza (jonli, zahar-sinovda 0/320 noto'g'ri o'tish):
   `GALLERY_MIN_SCORE=0.60`, `GALLERY_MIN_MARGIN=0.20`, `GALLERY_MIN_FACE=80`,
   `GALLERY_MIN_BLUR=60` (boshlang'ich; dry-run hisobotlarida kalibrlanadi).
   Hammasi env orqali sozlanadi.
2. O'z-o'ziga o'xshashlik (gallery_enrich ichida): nomzod embedding bolaning
   mavjud primary etaloni bilan solishtiriladi; o'xshashlik
   `GALLERY_MIN_SELF_SIM=0.35` dan past bo'lsa "shubhali" — hisobotda belgilanadi,
   --apply'da ham qo'shilmaydi. Bu "1 noto'g'ri shablon" stsenariysiga qarshi
   ikkinchi devor.

## Xatolarga chidamlilik

- Jurnal yozuvchisi: istalgan xato jim yutiladi (sighting_log bilan bir xil
  falsafa) — davomat oqimi hech qachon buzilmaydi.
- `gallery_enrich` idempotent: bir sana ustida qayta ishga tushirish natijani
  o'zgartirmaydi.
- Dry-run hisobot: har bola bo'yicha — ism, score, margin, blur, self-sim,
  hukm (qo'shilardi / mavjuddan yaxshi emas / shubhali) + umumiy sanoq.

## Test rejasi

1. Flag-o'chiq regressiya: `deepstream_v3/tests/smoke.sh` T1 PASS (xulq
   o'zgarmasligi isboti).
2. Flag-yoniq smoke: sinf.mp4 replay -> jurnal paydo bo'ladi, har qator darvoza
   shartlariga mos.
3. `gallery_enrich` to'liq tsikl: dry-run hisobot -> --apply (test DB) ->
   --rollback -> qayta apply.
4. Zahar-replay: jurnalga ataylab noto'g'ri bola qatori qo'shib, self-sim devori
   uni rad etishini tekshirish.

## Joriy etish tartibi

1. Hozir (iyul): kod + video replay sinovlari, flag default o'chiq.
2. Avgust: flag yoniq DRY-RUN (video/cam16_2), hisobotlar bilan chegara
   kalibrlash (ayniqsa GALLERY_MIN_BLUR va GALLERY_MIN_SELF_SIM).
3. Sentabr: jonli dry-run 1-2 hafta -> hisobotlar toza bo'lsa --apply.
4. Har qadam JAMI_2 qoidalariga bo'ysunadi: flag default o'chiq, o'lchamasdan
   o'zgartirmaymiz, rollback bir buyruq.

## Tegishli kod joylari

- `apps/attendance/services.py` — accepted qaror nuqtasi (log_sighting yonida)
  -> nomzod-yozuvchi shu yerdan chaqiriladi.
- `apps/attendance/sighting_log.py` — yozuvchi uslubi shundan andoza oladi
  (alohida modul: `apps/face_data/gallery_candidates.py` tavsiya).
- `apps/face_data/models.py` — StudentEmbedding migratsiyasi.
- `apps/face_data/management/commands/gallery_enrich.py` — yangi buyruq.
