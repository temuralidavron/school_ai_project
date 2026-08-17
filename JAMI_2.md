# JAMI_2 — 2026-yil iyul sessiyasi: to'liq holat va davom ettirish qo'llanmasi

> JAMI.md (B0-B4 migratsiya) ning davomi. Maqsad: keyingi sessiya (yoki odam)
> hech narsani qayta kashf qilmasdan aynan shu nuqtadan davom etishi.
> Yozilgan: 2026-07-14. Branch: `deepstream8-migration`.

---

## 1. HOZIRGI HOLAT (eng muhim) — YANGILANDI 2026-07-16

| Narsa | Holat |
|---|---|
| Git HEAD | `00c0ca5` — **F2b** (bosqichli tasdiqlash + elimination, flag-o'chiq). GitHub'da |
| Qaytish nuqtasi | **tag: `evrika`** (`f97d8b0`) — "evrikaga qayt" = `git reset --hard evrika` + image rebuild, savolsiz. Oraliq: `evrika-2` |
| Barcha yangi mantiq | **flag ostida, DEFAULT O'CHIQ** — .env'da flag yo'q bo'lsa xulq evrika bilan bir xil |
| `.env` | `AI_ACCEPT_THRESHOLD=0.50`, `AI_REVIEW_THRESHOLD=0.45`, **hech qanday B5_ flag yo'q (hammasi o'chiq)** |
| Image'lar | `school_ai:latest` + `school_ai_ds3:latest` — HEAD kodi bilan qurilgan |
| Migratsiya | `attendance/0014_staged_count` qo'llangan (staged_counts jadvali bor) |

**Ishlaydigan flaglar (.env'ga qo'yiladi, hammasi mustaqil):**
- `B5_MARGIN=1` — margin qabul yo'llari (top1≥0.48 & margin≥0.15, yoki ≥0.45 & ≥0.22)
- `B5_ELIM=1` — dars ichida qabul qilinganlarni top-5 nomzoddan chiqarish (top-1 locked bo'lsa tegilmaydi)
- `B5_STAGED=1` — past-ball, N marta izchil (default 5) → qabul; hisoblagich `StagedCount` (DB)
- `SIGHTING_LOG=0` — jurnalni o'chirish (default yoniq)
- `GALLERY_CANDIDATES=1` — F3c galereya-nomzod jurnali (temir darvoza: 0.60/0.20/80px/blur60); qo'shish faqat `gallery_enrich --apply` bilan, rollback `--rollback`

**Keyingi ishlar:** F2c (SKUD savollari — matn tayyor, YUBORILISHI kerak), F3c (galereya boyitish — kod + jonli smoke TASDIQLANDI 2026-07-21; qoldi: avgust dry-run/chegara kalibratsiya, keyin --apply). Staged jonli sentabrda sinaladi (o'tirgan holatda video'da hosil kam). F3 (review UI) — BEKOR: admin panel yetarli deb qaror qilindi, 2026-07-20.

---

## 1b. 2026-07-16 SESSIYASI (F0b→F2b + tajribalar)

Kommitlar ketma-ketligi (evrika-2 dan keyin):
| Commit | Ish |
|---|---|
| `096b665` | Gigiena: bot opt-in; (.env) AI_DET_SIZE 640→1280; 42 892 junk event o'chirildi |
| `4e3092e` | **F1 jonli manba**: nvurisrcbin, watchdog, export_ds_sources, compose ds3 |
| `17d741f` | **F2 sighting-jurnal**: logs/sightings-*.jsonl |
| `b5490fd` | Testlash+log spec + `deepstream_v3/tests/smoke.sh` (T1/T2) |
| `00c0ca5` | **F2b**: elimination + bosqichli tasdiqlash (flag-off) |

**Test to'plami bor:** `bash deepstream_v3/tests/smoke.sh` (fayl) / `--live` (cam16_2).
Har kod o'zgarishidan keyin ishga tushiriladi — PASS/FAIL. Spec:
`docs/superpowers/specs/2026-07-15-testlash-log-rejasi.md` (5 log qatlami, T1-T6).

**F2b sinov natijasi** (90s demo, flaglar YONIQ): 35/65 kelgan; qoidalar taqsimoti —
margin1=12, margin2=12, elim_margin2=2 (elimination haqiqiy qabullar berdi), review=7.
Consumer'da 0 xato. Flag-off T1 smoke PASS (regressiya yo'q).

**Galereya boyitish tajribasi** (F3c, scratchpad — GITGA KIRMAGAN, ataylab):
video A/B yarim split, 665 bolalik galereya. Natija: shablonli bolalar balli +0.054,
tabiiy drift 1/253 (threshold ostida, zararsiz). **ZAHAR-SINOV**: ataylab 1 noto'g'ri
shablon = 121 yuzdan 3 xato qabul → himoyasiz qilib BO'LMAYDI (isbotlangan). Temir
darvoza (≥0.60 + margin≥0.20 + ≥80px + Laplacian) dan noto'g'ri o'tish: 0/320.
Xulosa: F3c joriy qilinadi LEKIN himoya to'plami bilan, dry-run → sentabr jonli → yoqish,
source="camera" teg bilan bir-buyruqlik rollback. Batafsil: task #11 tavsifi.

**INFRA ESLATMASI (2026-07-16):** GPU drayveri buzilgan edi (kernel 7.0.0-28 ga yondi,
595.71 open modul kerak bo'ldi). Hal: `sudo apt install linux-modules-nvidia-595-open-$(uname -r)`
+ reboot. RTX 5080 uchun **open variant SHART**. Kelajakda GPU yo'qolsa — shu yerga qara.

---

## 1c. 2026-07-21 SESSIYASI (F3c jonli smoke + kalibratsiya)

**F3c kod-daraja verifikatsiya PASS:** 22 unit test (`apps/face_data/tests_gallery.py`),
migratsiyalar toza qo'llandi (face_data 0007/0008, monitoring 0001). Ulanish nuqtasi
`apps/attendance/services.py:591` — flag-off holatda haqiqiy no-op (barcha argument
scope'da, `RecognitionEvent.DECISION_ACCEPTED`/`best`/`bbox`/`margin` None-xavfsiz).

**Jonli smoke** (izolyatsiyalangan vaqtinchalik consumer + o'lik SKUD URL, ds3 demo replay):
- Flag-off: Traceback 0, davomat 27, sighting +336, gallery-candidates jurnal **yaratilmadi** — regressiya yo'q.
- Flag-on: JSONL yaratildi, qator to'liq (emb=512, crop_b64 real JPEG ~8.5KB, blur hisoblangan). 28/28 accept `log_candidate`'ga to'g'ri `score/margin/face` bilan yetdi.
- `gallery_enrich` dry-run real jurnalda: 10 nomzod, self_sim (real etalonlar), ismli hisobot, **DB'ga yozmadi**.

**KALIBRATSIYA — aniq raqam (avgust dry-run boshlanish nuqtasi):** jonli pipeline crop'lari
default darvozadan ANCHA past, chegara pasaytirilishi shart:
- `GALLERY_MIN_FACE=80` juda baland — o'tirgan sinfda yuzlar 30–60px (bittasi 87x98 chiqdi).
- `GALLERY_MIN_BLUR=60` juda baland — crop Laplacian ~4–56 (namuna 6.4). ENG bog'lovchi shart.
- `score≥0.60` va `margin≥0.20` erishsa bo'ladi; uch shart BIRGA hozircha 0 → MIN_FACE≈40, MIN_BLUR≈10-15 dan boshlab kalibrlansin.

**INCIDENT (SKUD leak, hal qilingan):** izolyatsiyada Kafka backlog e'tibordan qoldi —
prod consumer tiklanganda topic backlog'ini drenaj qilib 2 event (KIRAKOSYAN, UMIDJONOV,
11-G) real `edu.devel.uz`'ga push qildi. Consumer ~4s da to'xtatildi, mahalliy tozalandi
(event/davomat delete), group lag=0. SKUD API push-only (retract endpoint YO'Q). Kelajakda
replay izolyatsiyasida prod consumer tiklashdan OLDIN offset `--to-latest` reset SHART.

---

## 2. SESSIYA YUTUQLARI (raqamlar bilan)

| Ish | Natija | Qayerda |
|---|---|---|
| Jonli davomat sahifasi | `/monitoring/live/<id>/` — 2 video yonma-yon, foiz saralash, lightbox, tab | commit `4c0751f` (deepstream mvp) |
| Per-source MJPEG | `/mjpeg/0`, `/mjpeg/1` — har kamera alohida AI oqim | `4c0751f` |
| Consumer rasm bug'i | Eski konteyner kodi `save_base64=False` edi — tuzatildi, endi 1 bola = 1 rasm (~7KB JPEG, MinIO) | image'ga singdi |
| **Detection 640→1280** | **Attendance +53%** (17/65→26/65 teng kadrlarda), track churn ↓ (488→410), 9-G rekordi 29/34 | **evrika `f97d8b0`** |
| **B5 margin siyosati** | Simulyator: avto-qabul 45%→95% (320 event); "soxta bola" stress: **0/320 aldanish**; video A/B: +4 (42→46/65) | **stash@{0}** |
| Realtime video | `identity sync=true` per-source; 2 video = 49-52 agg fps (25/manba) — jonli kameradek | commit qilinmagan |
| Jonli kamera sinovi | cam16_2 (HLS 1080p30) — 1s da ulandi, decode OK, bo'sh xonada 0 FP | tekshirilgan |
| Virtual zoom tajribasi | 197 kichik yuz: o'rtacha delta +0.009 (nol), ~10% qutqarish, **shaxs almashish xavfi bor** — faqat himoya bilan ishlatiladi | xulosa pastda |
| Threshold 0.90 tajribasi | Foydalanuvchi talabiga sinaldi: **davomat = 0/65** (tarixiy max ball 0.723). 0.50 ga qaytarildi | isbot |
| Taqdimot materiallari | `~/Desktop/Davomat_Jarayoni_18_Qadam.html` — oflayn interaktiv doska boshliq uchun | Desktop |

---

## 3. B5 MARGIN — to'liq bilim (stash ochilganda kerak)

**Siyosat** (`apps/face_data/decision.py`, env bilan sozlanadi):
```
QABUL agar:  top1 >= accept_threshold (joriy 0.50)
       yoki: top1 >= 0.48 va margin >= 0.15    (B5_FLOOR1/B5_MARGIN1)
       yoki: top1 >= 0.45 va margin >= 0.22    (B5_FLOOR2/B5_MARGIN2)
margin = top1 - top2 (birinchi va ikkinchi nomzod farqi)
Yoqish: B5_MARGIN=1 (default O'CHIQ)
```
Ulanish nuqtalari: `LessonEmbeddingCache.decide_match` va
`RecognitionSearchService.decide_match_by_embedding` — ikkalasi bitta
`decide_margin()` ni chaqiradi; natijaga `decision_rule` va `margin` qo'shiladi.

**Isbot zanjiri:** (1) 320 haqiqiy eventda simulyatsiya — review 175→15;
(2) sezgirlik panjarasi — 0.15 atrofida barqaror plato; (3) "soxta bola" testi —
top-1 olib tashlanganda hech bir siyosat aldanmadi (0/320); (4) video A/B (teng
270s) — 42/65 → 46/65, margin yo'lidan o'tganlar sim 0.451-0.499, margin 0.23-0.27.

**Simulyator skriptlari:** sessiya scratchpad'ida edi (vaqtinchalik). Mantiq:
RecognitionEvent.meta_json.top_candidates (top-5 ball) ustida siyosatlarni replay
qilish. Kerak bo'lsa qayta yozish oson — meta_json'da hamma narsa bor.

---

## 4. REJA — F0-F5 (TaskList #1-10 da ham saqlangan)

| # | Faza | Mazmun | Muddat |
|---|---|---|---|
| 1 | **F0** | Realtime + B5 stash'ni flag-off commit, hujjatlar, `evrika-2` tag | darhol |
| 2 | **F0b** | Gigiena: 30-iyun junk (42892 event, student 262), **web det_size=640 siri** (.env'da 1280!), bot restart-loop | shu hafta |
| 3 | **F1** ⭐ | **Jonli manba**: v3'ga HLS/RTSP source + per-source reconnect + watchdog; cam16_2 bilan soak test. ENG USTUVOR — pipeline hali faqat MP4 o'qiydi! | iyul |
| 4 | **F2** | Qaror-jurnali (har sighting log — review dedup tarixni yo'qotadi, bosqichli tasdiqlashni sinash uchun shart) | iyul |
| 5 | **F2b** | B5 to'liq: bosqichli tasdiqlash + elimination (flag ostida) | avgust |
| 6 | **F2c** | SKUD rasm oynasi — AVVAL SKUD'ga 2 savol: arrived_at alohida maydonmi? photo update bormi? | savollar darhol |
| 7 | **F3** | Review UI: kamchilik hisoboti + bir-bosishli tasdiqlash | avgust |
| 8 | **F3b** | Track telemetriya, virtual PTZ (bolani bosib kuzatish), himoyali zoom 2-o'tish, ko'p-shablon galereya (front+left+right) | avgust |
| 9 | **F4** 🏁 | Sentabr: jonli pilot, joylashuv auditi (eshik zonasi!), ground-truth eval, 8 bola fotosini qayta olish | sentabr |
| 10 | **F5** | 20 kamera production, eski CameraStreamService pensiyasi, replikatsiya (1 maktab = 1 GPU) | kuz |

**Qoidalar:** o'lchamasdan o'zgartirmaymiz (simulyator/replay avval) · har faza = commit+tag ·
yangi mantiq flag bilan (default o'chiq) · demo e'lon qilinsa muzlatish.

---

## 5. MUHIM KASHFIYOTLAR VA TUZOQLAR

1. **Web InsightFace det_size=640 da ishlayapti** — .env'da `AI_DET_SIZE=1280` bo'lsa ham (log: "det_size=640x640"). Settings o'qilishini tekshirish kerak — enrollment embedding sifatiga ta'sir qilishi mumkin. (F0b)
2. **30-iyun anomaliyasi**: 42 892 event bitta bolaga (student 262) — eski lock-bug izi. Simulyatsiyalarda exclude qilingan; tozalash kerak. (F0b)
3. **Review eventlar dedup bo'ladi** (bola/kamera/kun boshiga bitta, yangilanadi) — sighting tarixi yo'qoladi. Bosqichli tasdiqlashni sinash uchun F2 jurnal shart.
4. **`docker cp` = mina**: konteyner recreate bo'lsa yo'qoladi. Bir marta shunday bug qaytib kelgan (consumer rasm). Endi qoida: kod o'zgarsa image rebuild.
5. **Kosinus shkala ≠ foiz ishonch**: tarixiy max ball 0.723; 0.90 threshold = davomat 0. Ishonch o'lchovi — margin, ball emas.
6. **Virtual zoom** faqat himoya bilan: top-1 shaxs ikkala o'tishda bir xil + margin + max(ball). Himoyasiz — shaxs almashish xavfi.
7. Video fayllar: `deepstream/data/sinf.mp4` (9-G, 34 bola) + `11g.mp4` (11-G, 31). Desktop'da to'liq 2-3 soatlik yozuvlar ham bor (kirish lahzalari uchun tekshirilmagan).
8. Hozir yozgi ta'til — jonli sinov (bolalar bilan) sentabrgacha yo'q; replay/simulyator — asosiy usul.

---

## 6. ISHGA TUSHIRISH / TO'XTATISH (tezkor ma'lumotnoma)

```bash
cd /home/user02/Desktop/school_full/school_ai_project

# YOQISH
docker compose up -d web kafka kafka_consumer minio_init
until curl -sf http://127.0.0.1:8000/monitoring/live/1/ >/dev/null; do sleep 2; done
bash deepstream_v3/run_demo.sh          # 1280 + realtime, DB reset bilan

# KO'RISH
#   http://localhost:8000/monitoring/live/1/   (9-G)
#   http://localhost:8000/monitoring/live/2/   (11-G)

# O'CHIRISH
docker stop school_ai_ds3_run           # faqat AI
docker compose --profile deepstream down  # hammasi (ma'lumot saqlanadi)

# Tez A/B/test uchun: REALTIME=0 env bilan pipeline eski "as-fast-as-possible"
```

Diagnostika: `docker logs -f school_ai_ds3_run` · `nvidia-smi` ·
davomat tozalash — run_demo.sh [1-2] qadamlari.

---

## 7. FOYDALANUVCHI KONVENTSIYALARI (sessiyada o'rnatilgan)

- **"evrikaga qayt"** = savolsiz `evrika` tag'iga qaytarish (kod stash'ga, image rebuild, .env toza)
- Bitta kamera/xona — qo'shimcha kamera byudjeti YO'Q (eshik kamerasi rad etilgan; yechim — bitta kameraning eshik zonasini qamrashi)
- Har dars mustaqil — video/footage "yodlash" yo'q; enrollment etalon — yagona doimiy xotira
- Davomat dars boshida tez yozilishi shart; rasm sifati keyin yaxshilanishi mumkin, lekin SKUD'ga ham tiniq rasm ketishi kerak (F2c oyna yechimi)
