#!/bin/bash
# =============================================================================
# DAVOMAT TIZIMI — bitta buyruq bilan to'liq ishga tushadi.
#
#   bash deploy/start.sh hls  --threshold 0.50     proxy orqali (internet)
#   bash deploy/start.sh rtsp --threshold 0.50     kamera IP ga to'g'ridan
#   bash deploy/start.sh status                    hozir nima ishlayapti
#   bash deploy/start.sh stop                      AI to'xtaydi (baza/web qoladi)
#
# Ikkala rejimda ham butun zanjir ishlaydi:
#   kamera -> DeepStream (yuz topish) -> Kafka -> consumer (tanish) ->
#   PostgreSQL (davomat) -> SKUD push
#
# Qo'shimcha:
#   --threshold 0.45     qabul chegarasi. Past = ko'proq taniydi, xato xavfi
#                        ortadi. Yuqori = kam taniydi, lekin ishonchli.
#                        `--threshold reset` — .env dagi qiymatga qaytadi.
#   --review 0.40        ko'rib chiqish chegarasi (bu oraliq qo'lda tasdiqlanadi)
#   --skud real          SKUD ga HAQIQIY push (qaytarib bo'lmaydi!)
#   --skud izolyatsiya   bazaga yoziladi, tashqariga ketmaydi (sinov uchun)
#   --cameras 5,9,10     faqat shu kameralar (default: org ning hammasi)
#   --org-id 16          tashkilot (default 16 = 225-maktab)
#   --interval N         nvinfer interval (default: kamera soniga qarab)
#   --rtsp-path /yo'l    RTSP yo'li (default /stream1; Camera.path ustuvor)
#   --ip-map FAYL        RTSP uchun IP CSV (Camera.ip_address bo'sh bo'lsa)
#   --dry-run            hech nima ko'tarmaydi, faqat tekshiradi
#
# Ishga tushirishdan OLDIN tekshiradi (bittasi yiqilsa boshlamaydi):
#   disk, GPU, TensorRT engine, baza/kafka, manbalar jonliligi, yuk hisobi.
# KEYIN tasdiqlaydi: kadr -> Kafka -> consumer -> baza zanjiri butunmi.
# =============================================================================
set -u
cd "$(dirname "$0")/.."

MODE="${1:-}"; shift 2>/dev/null || true
# RTSP_PATH: 225-maktabda TASDIQLANGAN yo'l /stream1 (Aliyer, 2026-08-26:
# rtsp://10.144.4.5:554/stream1 ... — jonli ishlagan havolalar).
# Boshqa brend/maktabda yo'l boshqa bo'lsa: bash deploy/rtsp_tayyorla.sh
# haqiqiy kadr o'qib topadi va Camera.path ga yozadi (baza bu defaultdan ustuvor).
ORG_ID=16; CAMERAS=""; INTERVAL=""; RTSP_PATH="/stream1"; IP_MAP=""
RTSP_USER="admin"; RTSP_PASS="admin"; RTSP_PORT_DEF=554; DRY=0
ACCEPT=""; REVIEW=""; SKUD_REAL=""; URLS=""

while [ $# -gt 0 ]; do
  case "$1" in
    --org-id)    ORG_ID="$2"; shift 2 ;;
    --cameras)   CAMERAS="$2"; shift 2 ;;
    --interval)  INTERVAL="$2"; shift 2 ;;
    --threshold) ACCEPT="$2"; shift 2 ;;   # qabul chegarasi (.env: 0.50)
    --review)    REVIEW="$2"; shift 2 ;;   # ko'rib chiqish chegarasi (.env: 0.45)
    --rtsp-path) RTSP_PATH="$2"; shift 2 ;;
    --rtsp-user) RTSP_USER="$2"; shift 2 ;;
    --rtsp-pass) RTSP_PASS="$2"; shift 2 ;;
    --ip-map)    IP_MAP="$2"; shift 2 ;;
    --url)       URLS="$URLS $2"; shift 2 ;;  # tayyor rtsp:// link (bir nechta mumkin)
    --skud)      SKUD_REAL="$2"; shift 2 ;;  # real | izolyatsiya
    --dry-run)   DRY=1; shift ;;
    *) echo "Noma'lum argument: $1"; exit 1 ;;
  esac
done

DC="docker compose"
RUN="school_ai_ds3"
SRC="deepstream_v3/configs/sources.json"

# ─── status / stop ───────────────────────────────────────────────────────────
if [ "$MODE" = "status" ]; then
  echo "=== Konteynerlar ==="
  docker ps --format '  {{.Names}}\t{{.Status}}' | grep -E "school_ai|ds3" || echo "  (yo'q)"
  echo
  echo "=== Manbalar ($SRC) ==="
  if [ -s "$SRC" ]; then
    python3 -c "
import json,sys
d=json.load(open('$SRC'))
for k,v in d.items():
    if '@' in v: v=v.split('://')[0]+'://***@'+v.split('@',1)[1]
    print(f'  cam {k}: {v}')
print(f'  JAMI: {len(d)}')" 2>/dev/null || cat "$SRC"
  else
    echo "  (bo'sh)"
  fi
  echo
  echo "=== Pipeline sog'ligi ==="
  if docker ps --format '{{.Names}}' | grep -q "^${RUN}$"; then
    docker logs "$RUN" 2>&1 | grep -iE "fps|gap=|real=" | tail -3 | sed 's/^/  /'
    echo "  jonli ko'rish: http://127.0.0.1:8554/mjpeg/0"
  else
    echo "  ds3 ishlamayapti"
  fi
  echo
  echo "=== Disk ==="
  df -h / | tail -1 | awk '{print "  root:", $4, "bo'\''sh ("$5" band)"}'
  du -sh logs 2>/dev/null | sed 's/^/  logs: /'
  exit 0
fi

if [ "$MODE" = "stop" ]; then
  echo "AI pipeline to'xtatilmoqda (baza, web, kafka qoladi)..."
  docker rm -f "$RUN" school_ai_ds3_run >/dev/null 2>&1
  echo "  ds3 to'xtatildi. Davomat qabul qilish (kafka_consumer) ishlashda davom etadi."
  echo "  Hammasini to'xtatish: docker compose --profile deepstream down"
  exit 0
fi

if [ "$MODE" != "hls" ] && [ "$MODE" != "rtsp" ]; then
  sed -n '3,20p' "$0" | sed 's/^# \?//'
  exit 1
fi

echo "============================================================"
echo " ISHGA TUSHIRISH — rejim: $MODE   tashkilot: $ORG_ID"
echo "============================================================"
echo

# ─── 0. Old tekshiruvlar (bitta ham yiqilsa to'xtaydi) ───────────────────────
XATO=0
echo "[0/5] Old tekshiruv..."

# 0a. Disk — 25 GB dan kam bo'lsa boshlamaymiz. Pipeline log va MinIO rasm
# yozadi; disk to'lsa Postgres READ-ONLY ga o'tadi va davomat YO'QOLADI.
FREE_GB=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
if [ "${FREE_GB:-0}" -lt 25 ]; then
  echo "    XATO: diskda faqat ${FREE_GB}GB bo'sh (kamida 25GB kerak)"
  echo "          Tozalash: bash deploy/cleanup.sh --apply"
  XATO=1
else
  echo "    disk: ${FREE_GB}GB bo'sh  OK"
fi

# 0b. GPU
if nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader >/tmp/_gpu 2>&1; then
  echo "    gpu: $(cat /tmp/_gpu)  OK"
else
  echo "    XATO: nvidia-smi ishlamadi — GPU drayver yiqilgan."
  echo "          Yechim: sudo modprobe nvidia  yoki  server_setup.sh dagi GPU bo'limi"
  XATO=1
fi
rm -f /tmp/_gpu

# 0c. Docker image'lar — yangi serverda yo'q bo'ladi, O'ZI build qiladi.
# Bu bir martalik: keyingi ishga tushirishlarda sekundlarda o'tadi.
if ! docker image inspect school_ai:latest >/dev/null 2>&1; then
  echo "    school_ai image YO'Q — build boshlanmoqda (~20-30 daqiqa, bir martalik)..."
  $DC build web 2>&1 | tail -3 | sed 's/^/      /'
  docker image inspect school_ai:latest >/dev/null 2>&1 || { echo "      XATO: build o'tmadi"; XATO=1; }
else
  echo "    school_ai image: bor  OK"
fi
if ! docker image inspect school_ai_ds3:latest >/dev/null 2>&1; then
  echo "    ds3 image YO'Q — build boshlanmoqda (~10-20 daqiqa, bir martalik)..."
  $DC --profile deepstream build ds3 2>&1 | tail -3 | sed 's/^/      /'
  docker image inspect school_ai_ds3:latest >/dev/null 2>&1 || { echo "      XATO: build o'tmadi"; XATO=1; }
else
  echo "    ds3 image: bor  OK"
fi

# 0c2. TensorRT engine — yo'q bo'lsa O'ZI build qiladi (~15 daq, bir martalik).
# Engine GPU ga bog'liq: boshqa GPU li serverda qaytadan build bo'lishi normal.
if ls deepstream_v3/engines/*.engine >/dev/null 2>&1; then
  echo "    engine: $(ls deepstream_v3/engines/*.engine | wc -l) ta  OK"
else
  echo "    TensorRT engine YO'Q — build boshlanmoqda (~15 daqiqa, bir martalik)..."
  bash deploy/build_engines.sh 2>&1 | tail -4 | sed 's/^/      /'
  ls deepstream_v3/engines/*.engine >/dev/null 2>&1 || { echo "      XATO: engine build o'tmadi"; XATO=1; }
fi

# 0d. Asosiy servislar
for s in school_ai_db school_ai_kafka school_ai_web school_ai_kafka_consumer; do
  if docker ps --format '{{.Names}}' | grep -q "^${s}$"; then
    echo "    $s: ishlayapti  OK"
  else
    echo "    $s: YO'Q — ko'tarilmoqda..."
    $DC up -d "${s#school_ai_}" >/dev/null 2>&1
    sleep 4
    docker ps --format '{{.Names}}' | grep -q "^${s}$" || { echo "      XATO: ko'tarilmadi"; XATO=1; }
  fi
done

[ "$XATO" = "1" ] && { echo; echo "Tekshiruv o'tmadi — to'xtatildi."; exit 1; }
echo

# ─── 0f. Tanish chegarasi va SKUD rejimi (consumer'da hal bo'ladi) ───────────
# Tanish qarori kafka_consumer ichida qabul qilinadi, shuning uchun chegara
# O'SHA konteynerga berilishi kerak. .env ga TEGMAYMIZ (u prod sozlama) —
# vaqtinchalik compose qatlami yoziladi va keyingi ishga tushirishlarda ham
# saqlanadi. Bekor qilish: --threshold reset
THR_FILE=".threshold.override.yml"
if [ "$ACCEPT" = "reset" ]; then
  rm -f "$THR_FILE"; ACCEPT=""; REVIEW=""
  echo "[0b] Chegara bekor qilindi — .env dagi qiymat ishlaydi"
elif [ -n "$ACCEPT$REVIEW" ]; then
  {
    echo "services:"
    echo "  kafka_consumer:"
    echo "    environment:"
    [ -n "$ACCEPT" ] && echo "      AI_ACCEPT_THRESHOLD: \"$ACCEPT\""
    [ -n "$REVIEW" ] && echo "      AI_REVIEW_THRESHOLD: \"$REVIEW\""
  } > "$THR_FILE"
fi

THR_LAYER=""
[ -f "$THR_FILE" ] && THR_LAYER="-f $THR_FILE"

ISO_LAYER=""
CONS_URL=$(docker inspect school_ai_kafka_consumer \
  --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
  | grep '^SKUD_API_BASE_URL=' | tail -1 | cut -d= -f2-)
case "$SKUD_REAL" in
  izolyatsiya) ISO_LAYER="-f docker-compose.demo-isolated.yml" ;;
  real)        ISO_LAYER="" ;;
  *)  # berilmagan — hozirgi holat saqlanadi
      [ "$CONS_URL" = "http://127.0.0.1:9" ] && ISO_LAYER="-f docker-compose.demo-isolated.yml" ;;
esac

if [ -n "$THR_LAYER" ] || [ -n "$SKUD_REAL" ]; then
  echo "[0b] Consumer sozlanmoqda (chegara / SKUD rejimi)..."
  if [ "$DRY" = "0" ]; then
    # cron ham: retry_skud_push real URL da qolsa sinov davomatini prodga oqizadi
    docker compose -f docker-compose.yml $ISO_LAYER $THR_LAYER --profile deepstream \
        up -d --force-recreate kafka_consumer cron >/dev/null 2>&1
    sleep 6
  fi
fi

# Haqiqiy holatni konteynerdan o'qiymiz — taxmin qilmaymiz
ENVS=$(docker inspect school_ai_kafka_consumer \
  --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null)
CONS_URL=$(echo "$ENVS" | grep '^SKUD_API_BASE_URL=' | tail -1 | cut -d= -f2-)
CUR_ACC=$(echo "$ENVS" | grep '^AI_ACCEPT_THRESHOLD=' | tail -1 | cut -d= -f2-)
CUR_REV=$(echo "$ENVS" | grep '^AI_REVIEW_THRESHOLD=' | tail -1 | cut -d= -f2-)
echo "    chegara: accept=${CUR_ACC:-0.50 (.env)}  review=${CUR_REV:-0.45 (.env)}"
# review >= accept bo'lsa "ko'rib chiqish" oralig'i yo'qoladi: shubhali
# tanishlar qo'lda tasdiqlashga tushmay, to'g'ridan qabul/rad bo'ladi.
if [ -n "$CUR_ACC" ] && [ -n "$CUR_REV" ]; then
  if awk "BEGIN{exit !($CUR_REV >= $CUR_ACC)}"; then
    echo "    DIQQAT: review ($CUR_REV) >= accept ($CUR_ACC) — ko'rib chiqish"
    echo "            oralig'i yo'q. Odatda review accept dan 0.05 past bo'ladi."
  fi
fi
if [ "$CONS_URL" = "http://127.0.0.1:9" ]; then
  echo "    SKUD: IZOLYATSIYA — davomat bazaga yoziladi, edu.devel.uz ga KETMAYDI"
  echo "          Haqiqiy push uchun: --skud real"
else
  echo "    SKUD: ${CONS_URL:-.env dagi}  -> HAQIQIY PUSH (qaytarib bo'lmaydi)"
fi
echo

# ─── 1. Manbalar ─────────────────────────────────────────────────────────────
echo "[1/5] Manbalar tayyorlanmoqda ($MODE)..."
# logs/ konteyner (root) egaligida bo'lib qoladi — host'dagi rm/yozuvlar jim
# yiqilib eski fayl ishlatilib ketardi (2026-08-26 auditda tasdiqlandi).
# Web konteyner (root) orqali egalikni o'zimizga olamiz.
$DC exec -T web chown -R "$(id -u):$(id -g)" /app/logs >/dev/null 2>&1 || true
# Eskisini o'chiramiz: aks holda export yiqilsa oldingi ishga tushirishdan
# qolgan fayl ishlatilib ketadi va rtsp so'raganda hls bilan ko'tarilardi.
rm -f logs/sources_new.json
if [ -e logs/sources_new.json ]; then
  echo "    XATO: logs/sources_new.json o'chirilmadi (egalik muammosi) — eski"
  echo "          manbalar bilan ko'tarilib ketmaslik uchun to'xtatildi."
  exit 1
fi
CAM_ARGS=""
if [ -n "$CAMERAS" ]; then
  for c in ${CAMERAS//,/ }; do CAM_ARGS="$CAM_ARGS --camera-id $c"; done
fi

if [ -n "$URLS" ]; then
  # Tayyor link(lar) berilgan — baza umuman so'ralmaydi.
  # --cameras SHART: davomat qaysi kameraga yozilishini taxmin qilib bo'lmaydi
  # (eski default cam 9 "10-xona" degan izoh ham noto'g'ri edi — 9 = 3a-xona).
  if [ -z "$CAMERAS" ]; then
    echo "    XATO: --url bilan --cameras ham SHART (davomat qaysi kameraga yozilsin?)"
    echo "          Masalan: --url \"rtsp://...\" --cameras 4"
    exit 1
  fi
  python3 - "$CAMERAS" $URLS <<'PY'
import json, sys
ids = [i for i in sys.argv[1].replace(",", " ").split() if i]
urls = sys.argv[2:]
if len(ids) < len(urls):
    print(f"    XATO: {len(urls)} url uchun {len(ids)} ta camera id berildi")
    raise SystemExit(1)
data = {ids[n]: u for n, u in enumerate(urls)}
json.dump(data, open("logs/sources_new.json", "w"), indent=2)
for cid, u in data.items():
    if "@" in u and "://" in u:
        sx, q = u.split("://", 1); k, h = q.split("@", 1)
        u = f"{sx}://{k.split(':', 1)[0]}:***@{h}"
    print(f"    cam {cid}: {u}")
PY
  [ -s logs/sources_new.json ] || exit 1
elif [ "$MODE" = "rtsp" ]; then
  # --ip-map berilmasa deploy/camera_ips.csv avtomatik olinadi — FAQAT org 16:
  # fayl 225-maktabning haqiqiy IP lari bilan commit qilingan, boshqa maktabda
  # avtomatik olinsa noto'g'ri kameralarga ulanish xavfi bor.
  if [ -z "$IP_MAP" ] && [ "$ORG_ID" = "16" ] && grep -qE '^[^#]' deploy/camera_ips.csv 2>/dev/null; then
    IP_MAP="deploy/camera_ips.csv"
    echo "    ip-map: deploy/camera_ips.csv (avtomatik)"
  fi
  IPMAP_ARG=""
  if [ -n "$IP_MAP" ]; then
    # web konteyner deploy/ ni ko'rmaydi — mount qilingan logs/ orqali beramiz
    cp "$IP_MAP" logs/_camera_ips.csv
    IPMAP_ARG="--ip-map /app/logs/_camera_ips.csv"
  fi
  $DC exec -T web python3.14 manage.py export_ds_sources --mode rtsp \
      --org-id "$ORG_ID" $CAM_ARGS --rtsp-user "$RTSP_USER" --rtsp-pass "$RTSP_PASS" \
      --rtsp-path "$RTSP_PATH" $IPMAP_ARG --out /app/logs/sources_new.json 2>&1 \
    | sed 's/^/    /'

  # ZAXIRA YO'L: web image eski bo'lsa (--mode rtsp ni bilmaydi) yoki web
  # umuman ko'tarilmagan bo'lsa — sources.json ni HOST da CSV dan yig'amiz.
  # Bazasiz ishlaydi: kamera IP lar camera_ips.csv da, login admin/admin.
  if [ ! -s logs/sources_new.json ] && [ -n "$IP_MAP" ]; then
    echo "    web orqali bo'lmadi — host'da CSV dan yig'ilmoqda (zaxira yo'l)"
    python3 - "$IP_MAP" "$RTSP_USER" "$RTSP_PASS" "$RTSP_PORT_DEF" "$RTSP_PATH" "$CAMERAS" <<'PY'
import json, sys
csv, user, pwd, port, path, cams = sys.argv[1:7]
istalgan = set(cams.replace(",", " ").split()) if cams.strip() else None
if not path.startswith("/"):
    path = "/" + path
data = {}
for line in open(csv, encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    parts = [p.strip() for p in line.replace(",", ";").split(";") if p.strip()]
    if len(parts) < 2:
        continue
    cid, ip = parts[0], parts[-1]
    if istalgan and cid not in istalgan:
        continue
    data[cid] = f"rtsp://{user}:{pwd}@{ip}:{port}{path}"
if data:
    json.dump(data, open("logs/sources_new.json", "w"), indent=2)
    for cid in data:
        print(f"      cam {cid}: rtsp://{user}:***@...{path}")
PY
  fi
else
  $DC exec -T web python3.14 manage.py export_ds_sources \
      --org-id "$ORG_ID" $CAM_ARGS --out /app/logs/sources_new.json 2>&1 \
    | sed 's/^/    /'
fi

if [ ! -s logs/sources_new.json ]; then
  echo "    XATO: manba fayl yaratilmadi."
  [ "$MODE" = "rtsp" ] && cat <<'EOF'
    RTSP uchun kamera IP kerak. Ikki yo'l:
      1) Camera.ip_address ni to'ldiring
      2) CSV bering:  --ip-map deploy/camera_ips.csv
         format:  camera_id;IP     masalan   9;10.144.4.11
EOF
  exit 1
fi
CNT=$(python3 -c "import json;print(len(json.load(open('logs/sources_new.json'))))")

# ─── 2. Manbalar TIRIKMI (ko'tarishdan oldin) ────────────────────────────────
# gap.mp4 muammosi: proxy oqim bermasa ham HTTP 200 va to'g'ri ko'rinadigan
# playlist qaytaradi, DeepStream esa jim o'ladi (konteyner "running",
# RestartCount=0, lekin kadr 0). HTTP 200 ni tekshirish YETARLI EMAS.
#
# Ishonchli belgi: MEDIA-SEQUENCE 6 soniyada oshadimi. Oshsa — kamera
# haqiqatan yangi segment yozyapti. Oshmasa — oqim qotgan.
# DIQQAT: index.m3u8 master playlist, segmentlar ICHKI playlist'da.
#
# KETMA-KET so'raymiz, parallel EMAS. 2026-08-25 da o'lchandi: 10 ta bir
# vaqtdagi so'rovda proxy bo'g'ilib bo'sh playlist qaytaradi va sog'lom
# kameralar "o'lik" ko'rinadi. Ketma-ket — hammasi to'g'ri javob beradi.
# Tezlik yo'qolmaydi: avval hamma p1 olinadi (~3s), bir marta 6s kutiladi,
# keyin hamma p2 (~3s). Jami ~12s.
echo
echo "[2/5] Manbalar tirikmi tekshirilmoqda ($CNT ta, ~12s)..."

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

RTSP_YOQ=""
while IFS=$'\t' read -r cid uri; do
  [ -z "$cid" ] && continue
  if [ "${uri#rtsp}" != "$uri" ]; then
    HOST=$(echo "$uri" | sed -E 's|.*@([^:/]+).*|\1|')
    if timeout 5 bash -c "echo > /dev/tcp/$HOST/554" 2>/dev/null; then
      echo "1|$HOST:554 ochiq" > "$TMP/$cid"
    else
      echo "0|$HOST:554 YOPIQ" > "$TMP/$cid"
    fi
    continue
  fi
  # HLS — variant playlist manzilini topib, birinchi o'lchovni olamiz
  BAZA="${uri%/*}"
  VAR=$(timeout 8 curl -s "$uri" 2>/dev/null | grep -vE '^#|^$' | head -1)
  [ -n "$VAR" ] && [ "${VAR#http}" = "$VAR" ] && VAR="$BAZA/$VAR"
  [ -z "$VAR" ] && VAR="$uri"          # variant yo'q = playlist o'zi media
  P1=$(timeout 8 curl -s "$VAR" 2>/dev/null | grep -oE 'MEDIA-SEQUENCE:[0-9]+' | grep -oE '[0-9]+')
  if [ -z "$P1" ]; then
    echo "0|playlist bo'sh yoki xato" > "$TMP/$cid"
  else
    echo "$VAR|$P1" > "$TMP/.hls_$cid"
  fi
done < <(python3 -c "
import json
for k,v in json.load(open('logs/sources_new.json')).items(): print(f'{k}\t{v}')")

# Bitta umumiy kutish — har kamera uchun alohida emas
ls "$TMP"/.hls_* >/dev/null 2>&1 && sleep 6

for f in "$TMP"/.hls_*; do
  [ -e "$f" ] || continue
  cid=$(basename "$f" | sed 's/^\.hls_//')
  VAR=$(cut -d'|' -f1 "$f")
  P1=$(cut -d'|' -f2 "$f")
  IKKI=$(timeout 8 curl -s "$VAR" 2>/dev/null)
  P2=$(echo "$IKKI" | grep -oE 'MEDIA-SEQUENCE:[0-9]+' | grep -oE '[0-9]+')
  # EXT-X-GAP — HLS standartidagi "bu segment bo'sh" tegi.
  # DIQQAT: proxy har so'rovda yangi sessiya ochadi (sequence 1 dan
  # boshlanadi), va sessiya isiguncha boshida 1-2 gap bo'lishi NORMAL.
  # Haqiqiy o'lim belgisi — sequence umuman oshmasligi, yoki segmentlarning
  # yarmidan ko'pi gap bo'lishi.
  GAP=$(echo "$IKKI" | grep -c 'EXT-X-GAP' || true)
  SEG=$(echo "$IKKI" | grep -c '^#EXTINF' || true)
  if [ "${P2:-0}" -le "${P1:-0}" ]; then
    echo "0|seq ${P1} QOTGAN (yangi segment yo'q)" > "$TMP/$cid"
  elif [ "${SEG:-0}" -gt 0 ] && [ $(( GAP * 2 )) -ge "$SEG" ]; then
    echo "0|$SEG segmentdan $GAP tasi BO'SH (kamera oqim bermayapti)" > "$TMP/$cid"
  elif [ "${GAP:-0}" -gt 0 ]; then
    echo "1|seq $P1->$P2, $SEG segment ($GAP bo'sh — sessiya isimoqda)" > "$TMP/$cid"
  else
    echo "1|seq $P1->$P2, $SEG segment" > "$TMP/$cid"
  fi
  rm -f "$f"
done

TIRIK=0; OLIK=""
for f in $(ls "$TMP" 2>/dev/null | sort -n); do
  R=$(cat "$TMP/$f")
  if [ "${R%%|*}" = "1" ]; then
    echo "    cam $f: ${R#*|}  OK"; TIRIK=$((TIRIK+1))
  else
    echo "    cam $f: ${R#*|}"; OLIK="$OLIK $f"
  fi
done

echo "    natija: $TIRIK/$CNT tirik"
if [ "$TIRIK" = "0" ]; then
  echo "    XATO: bironta ham manba javob bermadi — ko'tarish ma'nosiz."
  [ "$MODE" = "rtsp" ] && echo "          Server kamera tarmog'idami? (ip a | grep 10.144)"
  exit 1
fi
[ -n "$OLIK" ] && echo "    DIQQAT: o'lik kameralar:$OLIK — ular kadr bermaydi"

# O'lik HLS (http) manbalar sources dan CHIQARIB TASHLANADI: 404/qotgan HTTP
# manba butun pipeline'ni to'xtatadi (2026-08-26 da o'lchandi: cam 2 404 ->
# frame#1 dan keyin 0 fps, hamma kamera qotdi). O'lik RTSP esa QOLADI —
# nvurisrcbin o'zi qayta ulanadi va boshqalarga xalal bermaydi (o'lchangan).
if [ -n "$OLIK" ]; then
  # DIQQAT: logs/ papka konteyner (root) egaligida — host python u yerga yoza
  # olmaydi. Shuning uchun filtr ham web konteyner ichida bajariladi.
  if ! $DC exec -T -e DEAD_IDS="$OLIK" web python3.14 - <<'PYF'
import json, os
dead = set(os.environ.get("DEAD_IDS", "").split())
p = "/app/logs/sources_new.json"
d = json.load(open(p))
drop = [k for k in d if k in dead and d[k].startswith("http")]
for k in drop:
    d.pop(k)
    print(f"    cam {k}: o'lik HLS -> chiqarildi (pipeline'ni to'xtatardi)")
if drop:
    json.dump(d, open(p, "w"), indent=2)
PYF
  then
    echo "    XATO: o'lik manba filtri ishlamadi (web exec yiqildi) — o'lik HLS"
    echo "          manba pipeline'ni to'xtatib qo'ymasligi uchun to'xtatildi."
    exit 1
  fi
  CNT=$(python3 -c "import json;print(len(json.load(open('logs/sources_new.json'))))")
  if [ "$CNT" = "0" ]; then
    echo "    XATO: tirik manba qolmadi."
    exit 1
  fi
fi

# ─── 3. Interval hisoblash ───────────────────────────────────────────────────
# Engine ~224 fps. Har kamera 25 fps kerak. interval=N -> har (N+1)-kadrda
# detection. Kerakli quvvat = kamera*25/(interval+1). 2x zaxira qoldiramiz.
if [ -z "$INTERVAL" ]; then
  if   [ "$CNT" -le 2 ]; then INTERVAL=0
  elif [ "$CNT" -le 4 ]; then INTERVAL=1
  elif [ "$CNT" -le 8 ]; then INTERVAL=2
  else                        INTERVAL=3
  fi
fi
KERAK=$(( CNT * 25 / (INTERVAL + 1) ))
echo
echo "[3/5] Yuk hisobi: $CNT kamera x 25 fps / (interval $INTERVAL + 1) = ~$KERAK fps kerak"
echo "      engine quvvati ~224 fps  ->  zaxira $(( 224 * 100 / (KERAK>0?KERAK:1) ))%"
if [ "$KERAK" -gt 180 ]; then
  echo "      DIQQAT: zaxira kam. --interval $((INTERVAL+1)) bilan qayta ishga tushiring."
fi

if [ "$DRY" = "1" ]; then
  echo
  echo "=== --dry-run: hech nima ko'tarilmadi ==="
  exit 0
fi

cp logs/sources_new.json "$SRC"

# ─── 4. Pipeline ─────────────────────────────────────────────────────────────
echo
echo "[4/5] AI pipeline ko'tarilmoqda..."
docker rm -f "$RUN" school_ai_ds3_run >/dev/null 2>&1
DS_INTERVAL="$INTERVAL" $DC --profile deepstream up -d ds3 >/dev/null 2>&1

# ─── 5. To'liq zanjir: kadr -> Kafka -> consumer -> baza ─────────────────────
# Har bo'g'in alohida tekshiriladi. "Konteyner ishlayapti" YETARLI EMAS —
# ds3 jim o'lganda ham status "running" bo'lib turaveradi.
echo
echo "[5/5] Davomat zanjiri tasdiqlanmoqda (90s)..."

OK=0
for i in $(seq 1 18); do
  sleep 5
  if ! docker ps --format '{{.Names}}' | grep -q "^${RUN}$"; then
    echo "    XATO: ds3 konteyneri o'chdi. Loglar:"
    docker logs "$RUN" 2>&1 | tail -20 | sed 's/^/      /'
    exit 1
  fi
  # log formati: "frame#24300 -> 2 track | kafka=274 | 293 fps"
  SATR=$(docker logs --tail 5 "$RUN" 2>&1 | grep -oE '[0-9.]+ fps' | tail -1)
  FPS="${SATR% fps}"
  if [ -n "$FPS" ] && [ "${FPS%.*}" -gt 0 ] 2>/dev/null; then
    echo "    1. kadr olinmoqda    : $FPS fps  OK"; OK=1; break
  fi
  printf "    kutilmoqda... %ds\n" $((i * 5))
done

if [ "$OK" = "0" ]; then
  echo "    1. kadr olinmoqda    : YO'Q — konteyner tirik, lekin kadr kelmayapti"
  echo "       Sabab odatda: manba jim o'lgan yoki engine yuklanmagan."
  docker logs "$RUN" 2>&1 | tail -12 | sed 's/^/       /'
fi

# 2. Kafka — ds3 o'zi nechta xabar yuborganini logga yozadi (kafka=N).
# kafka-run-class konteynerda yo'q, shuning uchun manba loglaridan olamiz.
KAFKA_N=$(docker logs --tail 5 "$RUN" 2>&1 | grep -oE 'kafka=[0-9]+' | tail -1 | cut -d= -f2)
LAG=$(docker exec school_ai_kafka kafka-consumer-groups --bootstrap-server localhost:9092 \
      --describe --group attendance-consumer 2>/dev/null \
      | awk 'NR>2 && $6 ~ /^[0-9]+$/ {s+=$6} END {print s+0}')
if [ "${KAFKA_N:-0}" -gt 0 ]; then
  echo "    2. Kafka ga yuborildi: $KAFKA_N ta yuz, consumer navbatida ${LAG:-0}  OK"
else
  echo "    2. Kafka ga yuborildi: 0 — hali yuz topilmagan (xona bo'sh bo'lsa normal)"
fi

# 3. Consumer tirikmi. DIQQAT: consumer statistikani "errors: 0" ko'rinishida
# yozadi — uni xato deb sanamaymiz. Faqat Traceback va nolga teng bo'lmagan
# xato hisoblagichlari muhim.
if docker ps --format '{{.Names}}' | grep -q '^school_ai_kafka_consumer$'; then
  TB=$(docker logs --since 5m school_ai_kafka_consumer 2>&1 | grep -c 'Traceback' || true)
  NOL_EMAS=$(docker logs --since 5m school_ai_kafka_consumer 2>&1 \
             | grep -iE 'errors:[[:space:]]+[1-9]' | tail -1)
  if [ "${TB:-0}" -gt 0 ] || [ -n "$NOL_EMAS" ]; then
    echo "    3. Consumer          : ishlayapti, lekin xato bor"
    [ "${TB:-0}" -gt 0 ] && echo "       Traceback: $TB ta (oxirgi 5 daq)"
    [ -n "$NOL_EMAS" ] && echo "       $NOL_EMAS"
  else
    echo "    3. Consumer          : ishlayapti, xato yo'q  OK"
  fi
else
  echo "    3. Consumer          : ISHLAMAYAPTI — davomat yozilmaydi!"
fi

# 4. Baza — bugungi davomat. --no-imports: Django 5+ "N objects imported"
# xabarini bosadi, aks holda u raqamga aralashib ketadi.
BUGUN=$($DC exec -T web python3.14 manage.py shell --no-imports -c "
from apps.attendance.models import LessonAttendance
from django.utils import timezone
print(LessonAttendance.objects.filter(created_at__date=timezone.localdate()).count())" 2>/dev/null | tr -dc '0-9')
echo "    4. Bugungi davomat   : ${BUGUN:-0} yozuv"

echo
echo "============================================================"
echo " ISHLAYAPTI — $MODE, $CNT kamera, interval=$INTERVAL"
echo "   chegara: accept=${CUR_ACC:-.env}  review=${CUR_REV:-.env}"
if [ "$CONS_URL" = "http://127.0.0.1:9" ]; then
  echo "   SKUD:    izolyatsiya (bazaga yoziladi, tashqariga ketmaydi)"
else
  echo "   SKUD:    HAQIQIY push -> ${CONS_URL:-.env}"
fi
echo
echo "   Jonli AI tasvir:   http://127.0.0.1:8554/mjpeg/0 ... /mjpeg/$((CNT-1))"
echo "   Monitoring:        http://127.0.0.1:8000/monitoring/"
echo "   Holat:             bash deploy/start.sh status"
echo "   To'xtatish:        bash deploy/start.sh stop"
echo "   Dars sinovi:       bash deploy/run_lesson_test.sh --camera-id N --class 10-V"
echo "============================================================"
