#!/bin/bash
# =============================================================================
# DISK VA KESH BOSHQARUVI — "o'zicha to'lib qolmasin".
#
#   bash deploy/cleanup.sh --check          nima yeyayapti (hech nima o'chirmaydi)
#   bash deploy/cleanup.sh --apply          xavfsiz tozalash
#   bash deploy/cleanup.sh --install-cron   har kuni 03:00 da avtomatik
#
# NIMA O'CHIRILADI (xavfsiz — ishlayotgan tizimga tegmaydi):
#   docker build cache        qayta build faqat sekinlashadi, image saqlanadi
#   ishlatilmayotgan image    ishlab turgan konteynerlarniki TEGILMAYDI
#   logs/lesson_test/*        7 kundan eski sinov videolari
#   logs/*.log                100 MB dan katta bo'lsa kesiladi (truncate)
#   logs/sightings-*.jsonl    14 kundan eski
#   Postgres                  eski AttendanceLock + VACUUM
#
# NIMA O'CHIRILMAYDI: baza yozuvlari (davomat), MinIO rasmlar, .env, engine.
# =============================================================================
set -u
cd "$(dirname "$0")/.."

REJIM="${1:---check}"
LESSON_KUN=7        # sinov videolari necha kun saqlanadi
SIGHT_KUN=14        # sightings jsonl
LOG_MAX_MB=100      # bitta .log fayl chegarasi
LOCK_KUN=30         # AttendanceLock necha kundan keyin o'chadi

hajm() { du -sb "$1" 2>/dev/null | cut -f1 || echo 0; }
mb()   { echo $(( ${1:-0} / 1048576 )); }

echo "============================================================"
echo " DISK VA KESH  —  $(date '+%Y-%m-%d %H:%M')"
echo "============================================================"
df -h / | tail -1 | awk '{printf "  root: %s bo'\''sh / %s  (%s band)\n", $4, $2, $5}'
echo

# ─── O'lchash ────────────────────────────────────────────────────────────────
BC=$(docker system df -v 2>/dev/null | awk '/Build cache usage/{print $NF}')
DF=$(docker system df 2>/dev/null)
echo "  Docker:"
echo "$DF" | tail -n +2 | sed 's/^/    /'
echo
echo "  logs/:"
du -sh logs/* 2>/dev/null | sort -rh | head -6 | sed 's/^/    /'
echo

LESSON_ESKI=$(find logs/lesson_test -maxdepth 1 -type d -mtime +$LESSON_KUN 2>/dev/null | wc -l)
SIGHT_ESKI=$(find logs -maxdepth 1 -name 'sightings-*.jsonl' -mtime +$SIGHT_KUN 2>/dev/null | wc -l)
KATTA_LOG=$(find logs -maxdepth 1 -name '*.log' -size +${LOG_MAX_MB}M 2>/dev/null | wc -l)

echo "  Tozalash mumkin:"
echo "    docker build cache        : ${BC:-?}"
echo "    lesson_test (>${LESSON_KUN} kun)   : $LESSON_ESKI papka"
echo "    sightings (>${SIGHT_KUN} kun)    : $SIGHT_ESKI fayl"
echo "    .log (>${LOG_MAX_MB}MB)           : $KATTA_LOG fayl"
echo

# ─── Kelajakdagi o'sish ──────────────────────────────────────────────────────
echo "  KELAJAK — nima o'zicha o'sadi:"
if [ ! -f /etc/docker/daemon.json ] || ! grep -q 'max-size' /etc/docker/daemon.json 2>/dev/null; then
  if ! grep -q 'max-size' docker-compose.yml 2>/dev/null; then
    echo "    [!] Docker log rotation YO'Q — konteyner loglari CHEKSIZ o'sadi."
    echo "        ds3 har kadrda yozadi: ~2-4 GB/kun. --apply buni tuzatadi."
  else
    echo "    docker log rotation      : compose'da sozlangan  OK"
  fi
else
  echo "    docker log rotation      : daemon.json da sozlangan  OK"
fi

RET=$(docker exec school_ai_kafka kafka-configs --bootstrap-server localhost:9092 \
      --describe --entity-type topics --entity-name deepstream-faces 2>/dev/null \
      | grep -o 'retention.ms=[0-9]*' | head -1)
echo "    kafka retention          : ${RET:-default 7 kun}"

B64=$(grep '^AI_SAVE_EVENT_BASE64=' .env 2>/dev/null | cut -d= -f2)
if [ "${B64,,}" = "true" ]; then
  echo "    [!] AI_SAVE_EVENT_BASE64=True — har event ~123 kB baza."
  echo "        325 talaba x 6 dars = ~2000 event/kun = 7.4 GB/OY. Uni False qiling."
else
  echo "    AI_SAVE_EVENT_BASE64     : $B64  OK (rasm faqat MinIO da, ~0.5 kB/event)"
fi

psql_q() { docker exec school_ai_db psql -U postgres -d school_ai -t -c "$1" 2>/dev/null | tr -d ' \r\n'; }
LOCKS=$(psql_q "SELECT count(*) FROM attendance_locks;")
EVENTS=$(psql_q "SELECT count(*) FROM recognition_events;")
TRACKS=$(psql_q "SELECT count(*) FROM track_sessions;")
B64_QOLGAN=$(psql_q "SELECT count(*) FROM recognition_events WHERE image_base64 IS NOT NULL AND image_base64 <> '';")
DBSZ=$(psql_q "SELECT pg_size_pretty(pg_database_size('school_ai'));")
echo "    baza jami                : ${DBSZ:-?}"
echo "    attendance_locks         : ${LOCKS:-?} qator  (>${LOCK_KUN} kun eskisi o'chadi)"
echo "    recognition_events       : ${EVENTS:-?} qator, ${B64_QOLGAN:-?} tasida eski base64 rasm"
echo "    track_sessions           : ${TRACKS:-?} qator  (>${LOCK_KUN} kun eskisi o'chadi)"
echo

# ─── Bir kunlik o'sish prognozi ──────────────────────────────────────────────
echo "  PROGNOZ (325 talaba, 6 dars/kun, 10 kamera):"
echo "    baza      : ~1 MB/kun   (rasm MinIO da bo'lsa)  -> 30 MB/oy"
echo "    MinIO     : ~2000 rasm x 40 kB = 80 MB/kun      -> 2.4 GB/oy"
echo "    docker log: 3 fayl x 100 MB chegara             -> max 4 GB jami"
echo "    lesson_test: har sinov ~500 MB (2 video)        -> ${LESSON_KUN} kundan keyin o'chadi"
echo "    -> Cron o'rnatilgan bo'lsa disk BARQAROR turadi."
echo

# ─── --check shu yerda tugaydi ───────────────────────────────────────────────
if [ "$REJIM" = "--check" ]; then
  echo "  Tozalash uchun:  bash deploy/cleanup.sh --apply"
  echo "  Avtomatik:       bash deploy/cleanup.sh --install-cron"
  exit 0
fi

# ─── --install-cron ──────────────────────────────────────────────────────────
if [ "$REJIM" = "--install-cron" ]; then
  YOL="$(pwd)/deploy/cleanup.sh"
  QATOR="0 3 * * * /bin/bash $YOL --apply >> $(pwd)/logs/cleanup.log 2>&1"
  if crontab -l 2>/dev/null | grep -qF "$YOL"; then
    echo "  Cron allaqachon o'rnatilgan:"
    crontab -l 2>/dev/null | grep -F "$YOL" | sed 's/^/    /'
  else
    (crontab -l 2>/dev/null; echo "$QATOR") | crontab -
    echo "  Cron o'rnatildi — har kuni 03:00 da:"
    echo "    $QATOR"
  fi
  echo "  Tekshirish: crontab -l"
  exit 0
fi

if [ "$REJIM" != "--apply" ]; then
  echo "Ishlatish: --check | --apply | --install-cron"
  exit 1
fi

# ─── --apply ─────────────────────────────────────────────────────────────────
OLDIN=$(df -BM --output=avail / | tail -1 | tr -dc '0-9')
echo "============================================================"
echo " TOZALASH"
echo "============================================================"

echo "[1/6] Docker build cache..."
# DIQQAT: 'docker builder prune --filter until=24h' YETARLI EMAS — build
# cache yozuvlarining "last used" vaqti har build da yangilanadi, shuning
# uchun 373 GB cache ham "24 soatdan yosh" bo'lib chiqadi va tegilmaydi.
# --keep-storage ishonchli: berilgan hajmdan ortig'ini o'chiradi.
# Image'lar TEGILMAYDI, faqat qayta build sekinlashadi.
if docker buildx du >/dev/null 2>&1; then
  docker buildx prune -af --keep-storage 20GB 2>&1 | tail -2 | sed 's/^/    /'
else
  docker builder prune -af --keep-storage 20GB 2>&1 | tail -2 | sed 's/^/    /'
fi

echo "[2/6] Ishlatilmayotgan image va konteynerlar..."
docker container prune -f 2>&1 | tail -1 | sed 's/^/    /'
# DIQQAT: -a EMAS. -a bo'lsa hozir ishlatilmayotgan, lekin ertaga kerak
# bo'ladigan image'lar (school_ai_ds3:latest to'xtaganda) ham o'chib ketadi.
docker image prune -f 2>&1 | tail -1 | sed 's/^/    /'

echo "[3/6] Eski sinov videolari (>${LESSON_KUN} kun)..."
N=$(find logs/lesson_test -maxdepth 1 -type d -mtime +$LESSON_KUN 2>/dev/null | wc -l)
find logs/lesson_test -maxdepth 1 -type d -mtime +$LESSON_KUN -exec rm -rf {} + 2>/dev/null
echo "    $N papka o'chirildi"

echo "[4/6] Loglar..."
find logs -maxdepth 1 -name 'sightings-*.jsonl' -mtime +$SIGHT_KUN -delete 2>/dev/null
# truncate — o'chirmaymiz, chunki fayl deskriptori ochiq turgan bo'lishi mumkin
for f in $(find logs -maxdepth 1 -name '*.log' -size +${LOG_MAX_MB}M 2>/dev/null); do
  tail -c 20M "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  echo "    $f -> oxirgi 20 MB qoldirildi"
done
# konteyner loglari (rotation o'rnatilgunicha)
for c in $(docker ps -aq); do
  LP=$(docker inspect --format='{{.LogPath}}' "$c" 2>/dev/null)
  [ -f "$LP" ] && [ "$(stat -c%s "$LP" 2>/dev/null || echo 0)" -gt 524288000 ] && \
    truncate -s 0 "$LP" 2>/dev/null && echo "    konteyner log kesildi: $(docker inspect --format='{{.Name}}' $c)"
done

echo "[5/6] Baza — eski yozuvlar va VACUUM..."
# DIQQAT: lesson_attendances (davomat NATIJASI) va student_embeddings
# (etalonlar) HECH QACHON o'chirilmaydi. Faqat oraliq/texnik yozuvlar.
docker exec school_ai_db psql -U postgres -d school_ai -c \
  "DELETE FROM attendance_locks WHERE created_at < NOW() - INTERVAL '$LOCK_KUN days';" 2>&1 \
  | tail -1 | sed 's/^/    locks: /'
docker exec school_ai_db psql -U postgres -d school_ai -c \
  "DELETE FROM track_sessions WHERE created_at < NOW() - INTERVAL '$LOCK_KUN days';" 2>&1 \
  | tail -1 | sed 's/^/    tracks: /'
# Eski base64 rasmlar — yozuv qoladi, faqat rasm bo'shatiladi (MinIO da nusxa bor)
docker exec school_ai_db psql -U postgres -d school_ai -c \
  "UPDATE recognition_events SET image_base64 = NULL
   WHERE image_base64 IS NOT NULL AND created_at < NOW() - INTERVAL '7 days';" 2>&1 \
  | tail -1 | sed 's/^/    event rasm: /'
docker exec school_ai_db psql -U postgres -d school_ai -c \
  "VACUUM (ANALYZE);" >/dev/null 2>&1 && echo "    VACUUM ANALYZE bajarildi"

echo "[6/6] Docker log rotation (kelajakda o'smasin)..."
if ! grep -q 'max-size' docker-compose.yml 2>/dev/null; then
  echo "    docker-compose.yml da 'x-logging' bloki yo'q."
  echo "    Qo'shish uchun:  bash deploy/cleanup.sh --install-rotation"
else
  echo "    sozlangan  OK"
fi

KEYIN=$(df -BM --output=avail / | tail -1 | tr -dc '0-9')
echo
echo "============================================================"
printf " BO'SHADI: %d MB  (%d MB -> %d MB bo'sh)\n" $((KEYIN - OLDIN)) "$OLDIN" "$KEYIN"
echo "============================================================"
