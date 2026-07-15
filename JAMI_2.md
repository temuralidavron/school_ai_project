# JAMI_2 — 2026-yil iyul sessiyasi: to'liq holat va davom ettirish qo'llanmasi

> JAMI.md (B0-B4 migratsiya) ning davomi. Maqsad: keyingi sessiya (yoki odam)
> hech narsani qayta kashf qilmasdan aynan shu nuqtadan davom etishi.
> Yozilgan: 2026-07-14. Branch: `deepstream8-migration`.

---

## 1. HOZIRGI HOLAT (eng muhim)

| Narsa | Holat |
|---|---|
| Git HEAD | **tag: `evrika-2`** — realtime video + B5 margin (flag-o'chiq) + JAMI_2 + F1 spec. GitHub'da ham bor |
| Qaytish nuqtasi | **tag: `evrika`** (`f97d8b0`) — "evrikaga qayt" deyilsa: `git reset --hard evrika` + image rebuild, savolsiz |
| B5 margin | **Kodda** (`apps/face_data/decision.py` + `services.py`), lekin **B5_MARGIN=1 bo'lmaguncha uxlaydi** — xulq evrika bilan bir xil |
| `.env` | `AI_ACCEPT_THRESHOLD=0.50`, `AI_REVIEW_THRESHOLD=0.45`, B5_MARGIN yo'q (o'chiq) |
| F1 jonli manba | **BAJARILDI (2026-07-15)**: nvurisrcbin (file/rtsp/HLS), live-source=1, bus-fix (bitta manba xatosi loopni o'ldirmaydi — sinalgan), watchdog+healthcheck, `export_ds_sources` komandasi, compose `ds3` servisi, DEPLOY.md. cam16_2 bilan jonli sinov: 30fps, bo'sh xonada 0 FP, tarmoq uzilishiga chidadi. run_demo.sh regressiya o'tdi |
| Image'lar | `school_ai:latest` va `school_ai_ds3:latest` — evrika-2 kodi bilan qurilgan |

**Yangi sessiyada birinchi ish:** F2 — qaror-jurnali (har sighting log; qancha erta yoqilsa kuzga shuncha ko'p ma'lumot). Parallel: SKUD'ga 2 savol yuborilganmi — tekshirish (F2c bloklovchisi).

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
