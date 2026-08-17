#!/bin/bash
# DEMO — SKUD IZOLYATSIYASI BILAN. run_demo.sh ning xavfsiz o'ramchisi.
#
# NEGA KERAK (2026-07-21 incident): oddiy run_demo.sh 2 bolani (KIRAKOSYAN,
# UMIDJONOV, 11-G) real edu.devel.uz ga push qilgan. Uch sizish yo'li bor:
#   1) kafka_consumer inline push  — services.py _push_to_skud, shartsiz
#   2) cron retry_skud_push        — docker/crontab:15, har 5 daqiqada, --limit 200:
#      o'lik URL bilan muvaffaqiyatsiz bo'lgan eventlarni PROD URL bilan qayta yuboradi
#   3) Kafka backlog                — temp consumer to'xtagach, prod consumer tiklanganda
#      consume qilinmagan xabarlarni drenaj qilib push qiladi
#
# Ishlatish:
#   bash deepstream_v3/run_demo_isolated.sh start   # izolyatsiya + demo
#   bash deepstream_v3/run_demo_isolated.sh stop    # tozalash + prod tiklash
#   bash deepstream_v3/run_demo_isolated.sh status  # hozir izolyatsiyadami?
set -e
cd "$(dirname "$0")/.."

OVERRIDE="docker-compose.demo-isolated.yml"
COMPOSE_ISO="docker compose -f docker-compose.yml -f $OVERRIDE --profile deepstream"
COMPOSE_PROD="docker compose --profile deepstream"
KAFKA_BIN="/opt/kafka/bin"
GROUP="attendance-consumer"
TOPIC="deepstream-faces"

skud_url_of() {
  docker inspect "$1" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | grep '^SKUD_API_BASE_URL=' | tail -1 | cut -d= -f2-
}

clean_demo_data() {
  echo "  demo eventlarini tozalash (cam 1,2 bugungi + schedule 5,6)..."
  docker exec school_ai_web python3.14 manage.py shell -c "
from django.utils import timezone
from apps.attendance.models import LessonAttendance, AttendanceLock, RecognitionEvent, TrackSession
t = timezone.now().date()
n = RecognitionEvent.objects.filter(camera_id__in=[1,2], recognized_at__date=t).count()
for cam, sid in [(1,5),(2,6)]:
    LessonAttendance.objects.filter(schedule_id=sid).delete()
    AttendanceLock.objects.filter(schedule_id=sid).delete()
    RecognitionEvent.objects.filter(camera_id=cam, recognized_at__date=t).delete()
    TrackSession.objects.filter(camera_id=cam).delete()
print('    ochirildi:', n, 'ta RecognitionEvent')
" 2>&1 | grep -v "objects imported"
}

reset_offset() {
  echo "  Kafka offset ni topic oxiriga surish (backlog minasini zararsizlantirish)..."
  docker exec school_ai_kafka bash -lc \
    "$KAFKA_BIN/kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
     --group $GROUP --topic $TOPIC --reset-offsets --to-latest --execute" 2>&1 | tail -2
}

case "${1:-}" in

start)
  echo "=== IZOLYATSIYALANGAN DEMO ==="
  echo
  echo "[1/4] Prod SKUD yo'llarini uzish..."
  echo "  cron to'xtatilmoqda (retry_skud_push har 5 daqiqada prod ga yuboradi)..."
  docker stop school_ai_cron >/dev/null && echo "    school_ai_cron STOP"

  echo "  consumer o'lik SKUD URL bilan qayta yaratilmoqda..."
  $COMPOSE_ISO up -d --force-recreate kafka_consumer >/dev/null 2>&1
  sleep 3
  URL=$(skud_url_of school_ai_kafka_consumer)
  if [ "$URL" != "http://127.0.0.1:9" ]; then
    echo "    XATO: consumer hali ham '$URL' ishlatyapti. To'xtatildi."
    docker start school_ai_cron >/dev/null
    exit 1
  fi
  echo "    school_ai_kafka_consumer SKUD_API_BASE_URL=$URL  ✓ izolyatsiya tasdiqlandi"

  echo
  echo "[2/4] Kafka boshlang'ich holati:"
  docker exec school_ai_kafka bash -lc \
    "$KAFKA_BIN/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group $GROUP" 2>&1 \
    | awk 'NR==1 || /deepstream-faces/ {print "    " $0}'

  echo
  echo "[3/4] Demo pipeline ishga tushmoqda (run_demo.sh)..."
  bash deepstream_v3/run_demo.sh

  echo
  echo "[4/4] IZOLYATSIYA FAOL. Tugagach ALBATTA quyidagini bajaring:"
  echo "    bash deepstream_v3/run_demo_isolated.sh stop"
  ;;

stop)
  echo "=== DEMONI YOPISH VA PRODNI TIKLASH ==="
  echo
  echo "[1/5] Pipeline to'xtatilmoqda..."
  docker rm -f school_ai_ds3_run >/dev/null 2>&1 && echo "  school_ai_ds3_run o'chirildi" || echo "  (ishlamayotgan edi)"

  echo "[2/5] Izolyatsiyalangan consumer to'xtatilmoqda..."
  docker stop school_ai_kafka_consumer >/dev/null 2>&1 || true

  echo "[3/5] Demo ma'lumotlarini tozalash..."
  clean_demo_data

  echo "[4/5] Kafka backlog..."
  reset_offset

  echo "[5/5] Prod konfiguratsiyani tiklash..."
  $COMPOSE_PROD up -d --force-recreate kafka_consumer >/dev/null 2>&1
  sleep 3
  URL=$(skud_url_of school_ai_kafka_consumer)
  echo "  consumer SKUD_API_BASE_URL=$URL"
  docker start school_ai_cron >/dev/null && echo "  school_ai_cron START"

  echo
  echo "  Yakuniy tekshiruv — SKUD ga yuborilmagan qolgan event bormi:"
  docker exec school_ai_web python3.14 manage.py retry_skud_push --dry-run --limit 5 2>&1 \
    | grep -v "objects imported" | sed 's/^/    /'
  ;;

status)
  echo "=== HOLAT ==="
  URL=$(skud_url_of school_ai_kafka_consumer)
  echo "  consumer SKUD_API_BASE_URL : ${URL:-(konteyner topilmadi)}"
  if [ "$URL" = "http://127.0.0.1:9" ]; then
    echo "  -> IZOLYATSIYADA (demo rejimi)"
  else
    echo "  -> PROD REJIMI — demo qilmang, avval 'start' bajaring"
  fi
  echo -n "  cron                       : "
  docker inspect school_ai_cron --format '{{.State.Status}}' 2>/dev/null || echo "yo'q"
  echo -n "  pipeline (ds3_run)         : "
  docker inspect school_ai_ds3_run --format '{{.State.Status}}' 2>/dev/null || echo "ishlamayapti"
  ;;

*)
  echo "Ishlatish: bash deepstream_v3/run_demo_isolated.sh {start|stop|status}"
  exit 1
  ;;
esac
