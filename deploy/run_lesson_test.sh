#!/bin/bash
# =============================================================================
# JONLI DARS SINOVI — bolalar bir xonaga yig'ilganda ishlatiladi.
#
#   bash deploy/run_lesson_test.sh --camera-id 3 --class 10-A --subject Tarix --duration 45
#
# Nima qiladi (ketma-ket):
#   1. Vaqtinchalik dars yozuvi yaratadi (ExternalSchedule)
#   2. ds3 pipeline'ni JONLI kamera bilan ishga tushiradi
#   3. IKKI video yozadi:  xom (kameradan)  +  AI (bbox/ism belgilari bilan)
#   4. Dars tugagach (yoki Ctrl+C da) hammasini to'xtatadi
#   5. CSV hisobot chiqaradi — kim keldi, qachon, qanday ball, SKUD ga ketdimi
#
# MAVJUD KODGA TEGMAYDI — pipeline, davomat, SKUD push hammasi o'z holicha
# ishlaydi. Bu skript faqat ularni ishga tushiradi va natijani yig'adi.
#
# DIQQAT: SKUD ga HAQIQIY push ketadi (edu.devel.uz). Izolyatsiya YO'Q —
# bu ataylab, sinov isboti haqiqiy bo'lishi uchun.
#
# Ctrl+C — istalgan payt xavfsiz to'xtatadi, videolar to'g'ri yopiladi va
# hisobot baribir chiqadi.
# =============================================================================
set -u
cd "$(dirname "$0")/.."

CAMERA_ID=""; CLASS_NAME=""; SUBJECT="Tarix"; DURATION=45; ORG_ID=16
while [ $# -gt 0 ]; do
  case "$1" in
    --camera-id) CAMERA_ID="$2"; shift 2 ;;
    --class)     CLASS_NAME="$2"; shift 2 ;;
    --subject)   SUBJECT="$2"; shift 2 ;;
    --duration)  DURATION="$2"; shift 2 ;;
    --org-id)    ORG_ID="$2"; shift 2 ;;
    *) echo "Noma'lum argument: $1"; exit 1 ;;
  esac
done
[ -z "$CAMERA_ID" ] || [ -z "$CLASS_NAME" ] && {
  echo "Ishlatish: bash deploy/run_lesson_test.sh --camera-id N --class 10-A [--subject Tarix] [--duration 45]"
  exit 1; }

TS=$(date +%Y%m%d_%H%M%S)
OUT="logs/lesson_test/$TS"
mkdir -p "$OUT"
SEC=$((DURATION * 60))
DC="docker compose"
RUN="school_ai_ds3_run"

echo "============================================================"
echo " JONLI DARS SINOVI"
echo "   sinf=$CLASS_NAME  fan=$SUBJECT  kamera=$CAMERA_ID  davomiylik=${DURATION}daq"
echo "   natijalar: $OUT/"
echo "============================================================"
echo

# ─── 1. Dars yozuvi ──────────────────────────────────────────────────────────
echo "[1/5] Vaqtinchalik dars yaratilmoqda..."
SETUP=$($DC exec -T web python3.14 manage.py setup_test_lesson \
          --org-id "$ORG_ID" --class-name "$CLASS_NAME" \
          --camera-id "$CAMERA_ID" --duration "$DURATION" --subject "$SUBJECT" 2>&1)
echo "$SETUP" | sed 's/^/    /'
SCHED_ID=$(echo "$SETUP" | grep -oE "schedule_id : [0-9]+" | grep -oE "[0-9]+$")
[ -z "$SCHED_ID" ] && { echo "  XATO: dars yaratilmadi, to'xtatildi."; exit 1; }
echo

# ─── 2. Kamera manbasi ───────────────────────────────────────────────────────
echo "[2/5] Kamera manbasi tayyorlanmoqda..."
$DC exec -T web python3.14 manage.py export_ds_sources \
    --camera-id "$CAMERA_ID" --out /app/logs/sources_test.json >/dev/null 2>&1
cp logs/sources_test.json deepstream_v3/configs/sources.json 2>/dev/null
SRC_URL=$(grep -oE 'https?://[^"]+|rtsp://[^"]+' deepstream_v3/configs/sources.json | head -1)
echo "    manba: $SRC_URL"
[ -z "$SRC_URL" ] && { echo "  XATO: kamera stream_url bo'sh. Camera jadvalini tekshiring."; exit 1; }
echo

# ─── 3. Pipeline ─────────────────────────────────────────────────────────────
echo "[3/5] AI pipeline ishga tushmoqda..."
docker rm -f "$RUN" >/dev/null 2>&1
docker run -d --name "$RUN" --gpus all \
  --network school_ai_project_default -p 8554:8554 \
  -e KAFKA_BOOTSTRAP=kafka:9092 -e CAMERA_IDS="$CAMERA_ID" \
  -e PGIE_CONFIG=/ds3/configs/pgie_det10g_1280.txt -e DET_INPUT_SZ=1280 \
  -e REALTIME=1 -e VIS_EVERY=2 -e TRACK_SEND_COOLDOWN=3 \
  -v school_ai_project_insightface_models:/root/.insightface:ro \
  -v "$(pwd)/deepstream_v3/engines:/engines:ro" \
  -v "$(pwd)/deepstream_v3/configs:/ds3/configs:ro" \
  school_ai_ds3:latest >/dev/null 2>&1
sleep 25
if ! docker ps --format '{{.Names}}' | grep -q "^${RUN}$"; then
  echo "  XATO: pipeline ko'tarilmadi. Loglar:"
  docker logs "$RUN" 2>&1 | tail -15 | sed 's/^/    /'
  exit 1
fi
docker logs "$RUN" 2>&1 | grep -iE "manba|source|engine|fps" | tail -3 | sed 's/^/    /'
echo

# ─── 4. Video yozish (xom + AI) ──────────────────────────────────────────────
echo "[4/5] Video yozish boshlandi (xom + AI)..."
docker run -d --name lesson_rec_raw --network school_ai_project_default \
  -v "$(pwd)/$OUT":/out -v "$(pwd)/deploy":/scripts:ro \
  --entrypoint python3.14 school_ai:latest \
  /scripts/record_lesson.py --mode raw --url "$SRC_URL" \
  --out /out/xom_video.mp4 --duration "$SEC" >/dev/null 2>&1

docker run -d --name lesson_rec_ai --network school_ai_project_default \
  -v "$(pwd)/$OUT":/out -v "$(pwd)/deploy":/scripts:ro \
  --entrypoint python3.14 school_ai:latest \
  /scripts/record_lesson.py --mode ai --url "http://${RUN}:8554/mjpeg/0" \
  --out /out/ai_video.mp4 --duration "$SEC" >/dev/null 2>&1
sleep 8
for c in lesson_rec_raw lesson_rec_ai; do
  if docker ps --format '{{.Names}}' | grep -q "^${c}$"; then
    echo "    $c: yozyapti"
  else
    echo "    $c: TO'XTAGAN — loglar:"; docker logs "$c" 2>&1 | tail -4 | sed 's/^/      /'
  fi
done
echo

# ─── Tozalash (Ctrl+C da ham) ────────────────────────────────────────────────
finish() {
  echo
  echo "[5/5] To'xtatilmoqda va hisobot tayyorlanmoqda..."
  docker stop lesson_rec_raw lesson_rec_ai >/dev/null 2>&1
  sleep 3
  docker logs lesson_rec_raw 2>&1 | tail -2 | sed 's/^/    /'
  docker logs lesson_rec_ai  2>&1 | tail -2 | sed 's/^/    /'
  docker rm -f lesson_rec_raw lesson_rec_ai >/dev/null 2>&1
  docker rm -f "$RUN" >/dev/null 2>&1

  echo "    SKUD navbatidagilar yuborilmoqda..."
  $DC exec -T web python3.14 manage.py retry_skud_push --org-id "$ORG_ID" --limit 500 2>&1 \
    | tail -3 | sed 's/^/      /'

  $DC exec -T web python3.14 manage.py lesson_report \
      --schedule-id "$SCHED_ID" --subject "$SUBJECT" \
      --out "/app/$OUT/hisobot.csv" 2>&1 | sed 's/^/    /'

  echo
  echo "============================================================"
  echo " TAYYOR — natijalar: $OUT/"
  ls -la "$OUT" 2>/dev/null | grep -vE "^total|^d" | awk '{printf "   %-20s %8.1f MB\n", $NF, $5/1048576}'
  echo "============================================================"
  exit 0
}
trap finish INT TERM

# ─── Kutish ──────────────────────────────────────────────────────────────────
echo "    Dars ketmoqda. Jonli ko'rish:"
echo "      http://127.0.0.1:8000/monitoring/live/$CAMERA_ID/"
echo "      http://127.0.0.1:8554/mjpeg/0"
echo
echo "    Erta tugatish uchun: Ctrl+C"
echo
for ((i = 0; i < SEC; i += 30)); do
  sleep 30
  N=$($DC exec -T web python3.14 manage.py shell -c "
from apps.attendance.models import LessonAttendance
print(LessonAttendance.objects.filter(schedule_id=$SCHED_ID).count())" 2>/dev/null | tr -d ' \r\n')
  printf "    [%3d/%d daq]  davomat: %s\n" $(((i + 30) / 60)) "$DURATION" "${N:-?}"
done
finish
