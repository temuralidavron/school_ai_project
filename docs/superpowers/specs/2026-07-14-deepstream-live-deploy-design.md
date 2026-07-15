# DeepStream v3 — Jonli kamera + Deploy dizayni

> Sana: 2026-07-14 · Branch: `deepstream8-migration` · Muallif: Aliyer Temur + Claude
> Bog'liq: [JAMI_2.md](../../../JAMI_2.md) F1 fazasi, [JAMI.md](../../../JAMI.md) B6.

## 1. Maqsad va ko'lam

DeepStream v3 pipeline hozir faqat **MP4 fayl** o'qiydi (`filesrc`). Uni **jonli
kameraga** (HTTPS-HLS / RTSP) ulanadigan, uzilishga chidamli va **deploy qilinadigan
servis** holatiga keltirish. Yakuniy tekshiruv — `cam16_2` bilan haqiqiy run.

**Ko'lamda (bu spec):**
- `nvurisrcbin` asosidagi universal manba: `file://`, `rtsp://`, `https://…m3u8`.
- Jonli manba uchun `nvstreammux live-source=1`.
- Chidamlilik: RTSP reconnect (nvurisrcbin ichida) + watchdog + konteyner healthcheck.
- Kamera manzillari yagona haqiqat manbasi = Django `Camera.stream_url`; undan
  `sources.json` generatsiya qiluvchi management command.
- docker-compose'ga `ds3` servisi (`profiles: ["deepstream"]`, `restart: unless-stopped`).
- `deploy/DEPLOY.md`'ga DeepStream jonli deploy bo'limi.
- `cam16_2` bilan sinov.

**Ko'lamdan TASHQARI (YAGNI — F1b / F5, kuz):**
- Jonli `nvstreammux`'da per-manba issiq qayta qurish (dinamik add/remove).
- 10 kamera to'liq rollout, systemd unit, nginx, monitoring dashboard.
- Eski `CameraStreamService`'ni pensiyaga chiqarish.

## 2. Tekshirilgan faktlar (grounding — 2026-07-14)

| Fakt | Holat |
|---|---|
| ds3 image gst plaginlari | `souphttpsrc`, `hlsdemux`/`hlsdemux2`, `nvurisrcbin`, `rtspsrc` ✅ |
| HTTPS TLS backend | `libgiognutls.so` + `glib-networking 2.80` ✅ — Dockerfile o'zgarmaydi |
| cam16_2 jonli | `https://edu-api.devel.uz/cam16_2/index.m3u8` → HTTP 200, H.264 1080p30 HLS ✅ |
| URL normalizatsiya | bare URL 301 redirect — `/index.m3u8` qo'shish shart |
| Camera DB holati | Faqat 2 yozuv (71-maktab, org 32). **cam16_2 (org 16) DB'da YO'Q** — qo'shish kerak |
| `Camera.stream_url` format | Allaqachon `rtsp://` / `file://` sxemasida (nvurisrcbin bilan mos) |
| v3 `main.py` cheklovi | `_make_source_bin` faqat `filesrc`; bus har EOS/ERROR'da butun loop'ni to'xtatadi (bug) |
| v2 manba kodi | `rtsp://` + `file://` bor, **HLS yo'q** — HLS bu loyihada DeepStream orqali hali sinalmagan |

## 3. Arxitektura

```
                    KIRISH QATLAMI (o'zgaradi)          O'ZGARMAYDI (B1-B4)
configs/sources.json ─┐
{camera_id: uri}      │   ┌─ nvurisrcbin(0) ─┐
CLI --uri (fallback) ─┴──►├─ nvurisrcbin(1) ─┼─► nvstreammux ─► nvinfer ─► nvtracker
                          └─ nvurisrcbin(N) ─┘   (live-source=1)  (PGIE)     │
                             ├ file/rtsp/https-HLS                           ▼
                             ├ rtsp auto-reconnect              nvvideoconvert ─► probe
                             └ pad-added → sink_%u                            │
                                                                             ▼
                                          _pgie_probe / _recog_probe ─► Kafka + MJPEG
                            ▲
              CHIDAMLILIK: watchdog (last_frame_ts) + healthcheck fayli
```

Pipeline'ning **recognition / tracking / Kafka / MJPEG** qismiga tegilmaydi — faqat
**manba (ingestion)** va **chidamlilik** qatlami o'zgaradi. Kafka xabar formati
o'zgarmaydi → Django `kafka_consumer` teginilmaydi.

## 4. Komponentlar

### 4.1 Manba qatlami — `main.py` `_make_source_bin` qayta yozish
- Kirish: URI satri (`file://…`, `rtsp://…`, `https://…m3u8`).
- Element: `nvurisrcbin` (uridecodebin CPU-decoder muammosidan xoli, NVMM chiqaradi).
  - `uri` = normalizatsiyalangan manzil.
  - `source-id` = indeks (source_id → camera_id `CAMERA_IDS` bilan bog'lanadi — mavjud mantiq).
  - RTSP uchun: `rtsp-reconnect-interval` (masalan 5s), `select-rtp-protocol=4` (TCP),
    `latency` past.
  - `pad-added` signali → `nvstreammux.sink_%u` ga bog'lanadi (mavjud ghost-pad naqshi).
- `file://` uchun REALTIME rejimida hozirgi `identity sync=true` throttle mantig'i
  saqlanadi (A/B test uchun); jonli manbaga throttle QO'YILMAYDI (jonli o'zi real-time).
- `os.path.exists()` tekshiruvi (main.py:502) faqat `file://` uchun qoladi.

### 4.2 Manba konfiguratsiyasi yuklovchi
- Ustuvorlik: `--uri camera_id=uri …` (CLI) → yo'q bo'lsa `configs/sources.json` →
  yo'q bo'lsa `--video …` (orqaga moslik, hozirgi run_demo.sh buzilmaydi).
- `sources.json` format: `{"1": "https://…/index.m3u8", "2": "rtsp://…"}`.
- Yuklovchi `CAMERA_IDS` ni ham shu json'dan (kalitlardan) chiqaradi.

### 4.3 nvstreammux jonli rejim
- Jonli manba(lar) bo'lsa `mux.set_property("live-source", 1)` (wall-clock timing).
- `batched-push-timeout` jonli uchun moslashtiriladi (kadr kechiksa bloklab qolmasin).
- Klassik nvstreammux qoladi (`batch-size=n`, B4'da isbotlangan) — yangi nvstreammux
  hozir kiritilmaydi (YAGNI).

### 4.4 Chidamlilik (3 qatlam)
1. **RTSP reconnect** — `nvurisrcbin` ichida (qisqa uzilish o'zi tiklanadi).
2. **Bus handler tuzatish** — bitta manba EOS/ERROR'ida **butun loop to'xtamaydi**
   (hozirgi bug, main.py:480-486). Jonli rejimda EOS odatda bo'lmaydi; ERROR bo'lsa
   log + o'sha manbani "down" belgilash, boshqalari davom etadi. Qattiq nosozlikda
   konteyner healthcheck qayta ko'taradi.
3. **Watchdog + healthcheck** — har manba uchun `last_frame_ts` (probe'da yangilanadi).
   GLib periodik timer global "so'nggi kadr"ni healthcheck fayliga (`/tmp/ds3_health`)
   yozadi. `SOURCE_STALE_SEC` (masalan 30s) dan uzoq global to'xtash → docker
   healthcheck "unhealthy" → `restart: unless-stopped` qayta ishga tushiradi.

### 4.5 `export_ds_sources` management command (Django)
- Joylashuv: `apps/cameras/management/commands/export_ds_sources.py`.
- Vazifa: `Camera.objects.filter(organization_id=…, is_active…)` → `sources.json`
  yozadi (`{camera_id: normalized_uri}`).
- URL normalizatsiya (eski `CameraStreamService` mantig'i): `rtsp://`/`file://` —
  o'zgarmaydi; aks holda `.m3u8` bilan tugamasa `/index.m3u8` qo'shiladi.
- Argumentlar: `--org-id 16`, `--out deepstream_v3/configs/sources.json`, `--camera-id`
  (faqat bitta kamera, sinov uchun).

### 4.6 docker-compose `ds3` servisi
- `profiles: ["deepstream"]` (opt-in, mavjud naqsh), `restart: unless-stopped`.
- `build: deepstream_v3/` (yoki mavjud `school_ai_ds3:latest`).
- GPU reservation (mavjud web/cameras naqshi), `depends_on: kafka`.
- Volume: engines (ro), insightface models (ro), `configs/` + `sources.json` (ro),
  `deepstream/data` (ro, file:// A/B uchun).
- Env: `KAFKA_BOOTSTRAP`, `PGIE_CONFIG=…1280`, `DET_INPUT_SZ=1280`, `REALTIME=1`,
  `VIS_EVERY`, `SOURCE_STALE_SEC`.
- Port: `8554` (MJPEG).
- `healthcheck`: `/tmp/ds3_health` mtime tekshiruvi.
- Ishga tushirish: `docker compose --profile deepstream up -d ds3`.
- `run_demo.sh` **dev/A-B uchun qoladi** (MP4 + DB reset — production yo'liga aralashmaydi).

### 4.7 `deploy/DEPLOY.md` — yangi bo'lim
"DeepStream jonli deploy": (1) `export_ds_sources` → sources.json; (2) `compose
--profile deepstream up -d ds3`; (3) tekshirish (MJPEG, Kafka, davomat).

## 5. Ma'lumot oqimi

Faqat **kirish** o'zgaradi. Manba (nvurisrcbin) → decode (NVMM) → nvstreammux batch →
undan keyingi hamma narsa (PGIE, tracker, ArcFace, Kafka, MJPEG) **B1-B4'dagidek**.
Kafka xabar formati bir xil → Django tarafi teginilmaydi.

## 6. Xato boshqaruvi

| Nosozlik | Javob |
|---|---|
| RTSP qisqa uzilish | nvurisrcbin `rtsp-reconnect-interval` o'zi tiklaydi |
| Bitta kamera ERROR/EOS | Log + "down" belgilash; boshqa kameralar ishlaydi (loop to'xtamaydi) |
| Global kadr to'xtashi (>STALE) | healthcheck unhealthy → konteyner restart |
| HLS URL noto'g'ri format | `export_ds_sources` `/index.m3u8` qo'shadi; ishga tushishda validatsiya + aniq log |
| sources.json yo'q/bo'sh | Aniq xato log + `--video` fallback (dev) |

## 7. Sinov rejasi (cam16_2 — "test now")

1. cam16_2 uchun `Camera` yozuvi qo'shish (org 16, `stream_url=https://edu-api.devel.uz/cam16_2`)
   **yoki** birinchi smoke test uchun to'g'ridan `--uri 1=https://edu-api.devel.uz/cam16_2/index.m3u8`.
2. `ds3` servisini shu manbaga qaratib ishga tushirish.
3. Tekshirish:
   - Ulanish < ~2s, decode OK (log + MJPEG'da jonli video `http://localhost:8554/mjpeg/0`).
   - Kafka oqadi; **bo'sh xonada 0 recognition / 0 false-positive** (avval isbotlangan holat).
   - Qasddan uzish (network/URL) → reconnect yoki healthcheck-restart tiklanishini ko'rish.
4. Regressiya: `run_demo.sh` (file:// A/B) hamon ishlashini tasdiqlash.

## 8. Ochiq qarorlar (spec ichida hal qilingan)

- **Manba elementi:** `nvurisrcbin` (klassik nvstreammux + `live-source=1`). Sabab:
  HLS+RTSP+reconnect qutidan chiqadi, plaginlar image'da bor.
- **URL manbasi:** `sources.json` (Django DB'dan generatsiya) yagona haqiqat manbasi;
  CLI `--uri` — smoke test uchun tezkor yo'l.
- **Chidamlilik darajasi (v1):** konteyner-restart + RTSP reconnect. Jonli per-manba
  issiq qayta qurish **keyingi faza** (F1b) — hozir eng xavfli/keraksiz qism.
- **Birinchi sinov:** to'g'ridan `--uri` smoke test → keyin `Camera` yozuvi + `export`.

## 9. Muvaffaqiyat mezoni

- v3 pipeline `cam16_2` HLS'dan jonli o'qiydi, decode qiladi, Kafka'ga uzatadi.
- Kamera uzilib-ulanganda tizim o'zi tiklanadi (reconnect yoki restart).
- `docker compose --profile deepstream up -d ds3` bilan deploy bo'ladi; DEPLOY.md'da
  hujjatlashtirilgan.
- `run_demo.sh` (file:// dev/A-B) buzilmaydi.
