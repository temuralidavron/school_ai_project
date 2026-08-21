#!/bin/bash
# =============================================================================
# PROD MUAMMOLARINI TUZATISH — 2026-08-20 auditi natijasi
#
#   bash deploy/fix_prod_issues.sh --check    # faqat ko'rsatadi, TEGMAYDI
#   bash deploy/fix_prod_issues.sh --apply    # tuzatadi
#
# Bu skript FAQAT sozlama va tozalash qiladi — KODGA TEGMAYDI.
# Kod tuzatishlari (SKUD 400 tasnifi, retry chegarasi, ogohlantirish)
# alohida va flag ostida qilinadi.
#
# Har qadam orqaga qaytariladi:
#   1. .env  -> .env.bak_<sana> nusxasi olinadi
#   2. cameras -> qayta yoqish: docker compose up -d cameras
#   3. loglar -> o'chiriladi (qayta yaratiladi)
#   4. VACUUM -> faqat bo'sh joyni qaytaradi, ma'lumot yo'qolmaydi
#   5. lock   -> faqat 30 kundan eski va schedule_id NULL bo'lganlar
# =============================================================================
set -u
cd "$(dirname "$0")/.."

MODE="${1:---check}"
[ "$MODE" = "--check" ] || [ "$MODE" = "--apply" ] || {
  echo "Ishlatish: bash deploy/fix_prod_issues.sh {--check|--apply}"; exit 1; }

RUN() { if [ "$MODE" = "--apply" ]; then eval "$1"; else echo "      [check] $1"; fi; }
DJ() { docker exec school_ai_web python3.14 manage.py shell -c "$1" 2>&1 | grep -v "objects imported"; }

echo "============================================================"
echo " PROD MUAMMOLARINI TUZATISH — rejim: $MODE"
echo "============================================================"
echo

# ─── 1. Rasm ikki joyda saqlanmasin ──────────────────────────────────────────
echo "[1/6] Rasm bazada takrorlanishi (AI_SAVE_EVENT_BASE64)"
CUR=$(grep -E "^AI_SAVE_EVENT_BASE64=" .env 2>/dev/null | cut -d= -f2)
echo "      hozir: ${CUR:-YOQ}"
if [ "${CUR:-}" = "True" ]; then
  echo "      -> False qilinadi (rasm MinIO da qoladi, bazada takrorlanmaydi)"
  RUN "cp .env .env.bak_\$(date +%Y%m%d_%H%M%S)"
  RUN "sed -i 's/^AI_SAVE_EVENT_BASE64=True/AI_SAVE_EVENT_BASE64=False/' .env"
  echo "      DIQQAT: kuchga kirishi uchun konteynerlar qayta ishga tushadi (6-qadam)"
else
  echo "      o'zgarish kerak emas"
fi
echo

# ─── 2. Eski avlod servisini o'chirish ───────────────────────────────────────
echo "[2/6] Eski 'cameras' servisi (ds3 bilan bir xil ishni qiladi)"
if docker ps --format '{{.Names}}' | grep -q '^school_ai_cameras$'; then
  echo "      ISHLAYAPTI — to'xtatiladi"
  echo "      sabab: kameraga ikki ulanish, GPU da ikki model, dublikat davomat"
  RUN "docker compose stop cameras"
else
  echo "      allaqachon to'xtatilgan"
fi
echo "      qayta yoqish kerak bo'lsa: docker compose up -d cameras"
echo

# ─── 3. Log tozalash ─────────────────────────────────────────────────────────
echo "[3/6] Loglar"
SZ=$(du -sm logs/ 2>/dev/null | cut -f1)
echo "      hozir: ${SZ:-0} MB"
BIG=$(find logs -type f -size +50M 2>/dev/null | head -5)
if [ -n "$BIG" ]; then
  echo "      50 MB dan katta fayllar (loglar emas, tasodifan tashlangan):"
  find logs -type f -size +50M -printf '        %s %p\n' 2>/dev/null | awk '{printf "        %.0f MB  %s\n", $1/1048576, $2}'
fi
echo "      -> 14 kundan eski log va JSONL o'chiriladi"
RUN "find logs -type f \\( -name '*.log.*' -o -name 'sightings-*.jsonl' \\) -mtime +14 -delete"
echo "      -> logs/ ichidagi .onnx (u yerda turmasligi kerak):"
find logs -name "*.onnx" -printf '        %p\n' 2>/dev/null
RUN "find logs -name '*.onnx' -delete"
echo

# ─── 4. Baza bo'sh joyi (bloat) ──────────────────────────────────────────────
echo "[4/6] Baza bo'sh joyi"
docker exec school_ai_db psql -U postgres -d school_ai -t -c \
  "SELECT '      ' || relname || ': ' || pg_size_pretty(pg_total_relation_size(relid)) || ' (' || n_live_tup || ' qator)'
   FROM pg_stat_user_tables WHERE relname IN ('external_student_photos','recognition_events')
   ORDER BY pg_total_relation_size(relid) DESC;" 2>/dev/null
echo "      -> VACUUM FULL (bo'sh joy qaytariladi, MA'LUMOT YO'QOLMAYDI)"
echo "         DIQQAT: bu vaqtda jadval qulflanadi — dars vaqtida BAJARMANG"
RUN "docker exec school_ai_db psql -U postgres -d school_ai -c 'VACUUM FULL external_student_photos;'"
echo

# ─── 5. Egasiz lock'lar ──────────────────────────────────────────────────────
echo "[5/6] AttendanceLock (tozalanmaydi, cheksiz o'sadi)"
DJ "
from apps.attendance.models import AttendanceLock
from django.utils import timezone
import datetime
q = AttendanceLock.objects.filter(schedule__isnull=True, created_at__lt=timezone.now()-datetime.timedelta(days=30))
print('      jami lock:', AttendanceLock.objects.count())
print('      schedule siz va 30 kundan eski:', q.count(), '<- o\'chiriladi')
"
RUN "docker exec school_ai_web python3.14 manage.py shell -c \"
from apps.attendance.models import AttendanceLock
from django.utils import timezone
import datetime
n,_ = AttendanceLock.objects.filter(schedule__isnull=True, created_at__lt=timezone.now()-datetime.timedelta(days=30)).delete()
print('      o\\'chirildi:', n)
\" 2>&1 | grep -v 'objects imported'"
echo

# ─── 6. Konteynerlarni yangi sozlama bilan ko'tarish ─────────────────────────
echo "[6/6] Sozlama kuchga kirishi"
if [ "$MODE" = "--apply" ] && [ "${CUR:-}" = "True" ]; then
  echo "      web va kafka_consumer qayta yaratilmoqda..."
  RUN "docker compose up -d --force-recreate web"
  RUN "docker compose --profile deepstream up -d --force-recreate kafka_consumer"
  sleep 8
  docker exec school_ai_web printenv AI_SAVE_EVENT_BASE64 2>/dev/null | sed 's/^/      web: AI_SAVE_EVENT_BASE64=/'
else
  echo "      (--apply da bajariladi)"
fi
echo

echo "============================================================"
if [ "$MODE" = "--check" ]; then
  echo " Bu faqat KO'RSATISH edi. Bajarish uchun:"
  echo "   bash deploy/fix_prod_issues.sh --apply"
else
  echo " TUZATILDI. Tekshirish:"
  echo "   du -sh logs/"
  echo "   docker compose ps"
  echo "   docker exec school_ai_web printenv AI_SAVE_EVENT_BASE64"
fi
echo "============================================================"
