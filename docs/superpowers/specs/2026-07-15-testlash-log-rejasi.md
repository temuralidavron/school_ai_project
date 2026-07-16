# Testlash va log rejasi

> Sana: 2026-07-15 · Branch: `deepstream8-migration` · Bog'liq: JAMI_2.md F2/F2b/F4
> Maqsad: har o'zgarish O'LCHANADIGAN bo'lsin — "ishlayaptimi?" savoli hech qachon
> taxmin bilan javob olmasin. Kuzgi jonli pilotgacha dalil to'planib borsin.

---

## 1. LOG QATLAMLARI (nima, qayerga, nima uchun)

| # | Qatlam | Qayerga | Holat |
|---|---|---|---|
| L1 | **Qaror-jurnali** — har sighting: ts, cam, sched, track, decision, rule, margin, top-5 | `logs/sightings-YYYY-MM-DD.jsonl` | ✅ BOR (F2) |
| L2 | **Run-sarlavha** — har consumer start: thresholdlar, B5 flag, vaqt. Busiz jurnal qatorlari "qaysi qoidada yozilgan?" savoliga javobsiz | o'sha jsonl'ga `"type":"run"` qatori | 🔨 shu bugun |
| L3 | **Pipeline oqim loglari** — frame#/fps/kafka har 300 kadrda, SOURCE DOWN, WATCHDOG | docker logs (ds3) | ✅ BOR |
| L4 | **Salomatlik** — so'nggi kadr vaqti | `/tmp/ds3_health` + compose healthcheck | ✅ BOR (F1) |
| L5 | **Natija** — RecognitionEvent (meta_json.track_key bilan L1 ga bog'lanadi), LessonAttendance | PostgreSQL | ✅ BOR |

**Kalit bog'lam:** `track_key` — L1 jurnal ↔ L5 baza. Har qabul yozuvini uning
butun sighting-ketma-ketligiga ulash mumkin.

**Hajm/retention:** demo 30s ≈ 200 qator (60KB). 20 jonli kamera to'liq o'quv kuni
≈ 50-100MB/kun. Qoida: 7 kundan eski `sightings-*.jsonl` gzip qilinadi (cron,
F4 gacha qo'lda ham bo'ladi). Jurnal HECH QACHON o'chirilmaydi — bu kuzgi dataset.

---

## 2. TEST TO'PLAMI (nomlangan, takrorlanadigan)

| Test | Qachon | Qadamlar | O'tdi mezoni |
|---|---|---|---|
| **T1 Smoke (fayl)** | har kod o'zgarishidan keyin | `tests/smoke.sh` — demo 60s | kadr oqadi; davomat ≥ 5; jurnal ≥ 50 qator; log'da Traceback yo'q |
| **T2 Smoke (jonli)** | pipeline o'zgarganda | `tests/smoke.sh --live` (cam16_2) | ulanish < 10s; fps 25-35; bo'sh xonada 0 accepted; health fayl < 30s eski |
| **T3 Chidamlilik** | pipeline o'zgarganda | jonli rejimda tarmoqni 20s uzish | loop tirik qoladi (konteyner Up); SOURCE DOWN/WATCHDOG log chiqadi |
| **T4 Siyosat A/B** | B5/threshold o'zgarishida | teng oyna (270s yoki 12k kadr), flag OFF vs ON, DB reset oraliqda | kelganlar soni taqqoslanadi; har qabul margin bilan; FP da'vosi faqat lightbox tekshiruvi bilan |
| **T5 Jurnal-replay** | F2b yozilganda | sightings fayllardan ketma-ketlik simulyatsiyasi (bosqichli counter, elimination) | yangi qoida eski qoidadan kam bola YO'QOTMAYDI va yangi xato QO'SHMAYDI |
| **T6 Tungi soak** | F4 dan oldin, katta o'zgarishlardan keyin | `compose --profile deepstream up -d ds3` (cam16_2) 8+ soat | restart soni ≤ 2; bo'sh xonada accepted = 0; xotira o'smaydi (docker stats) |

**Qoidalar:**
- Natija raqamlarsiz "ishladi" deyilmaydi — har test o'z mezonini chiqaradi.
- A/B har doim teng sharoit: bir xil kadrlar/oyna, oraliqda DB reset.
- Har muhim natija JAMI_2.md ga sana bilan yoziladi.

---

## 3. DARHOL QILINADIGAN ISHLAR (shu spec bilan birga)

1. `sighting_log.log_run()` — consumer startda run-sarlavha (L2).
2. `deepstream_v3/tests/smoke.sh` — T1/T2 avtomatlashtirilgan, PASS/FAIL chiqaradi.
3. JAMI_2.md ga "test to'plami bor" eslatmasi.

Keyinga (F2b bilan): T5 replay skripti (`tests/replay_policies.py`).
Keyinga (F4 oldidan): T6 soak + gzip cron.
