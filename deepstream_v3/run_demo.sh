#!/bin/bash
# DEMO: 2 sinf (9-G + 11-G) — 1280 detection rejimida (isbotlangan: +53% natija).
# run_2cam.sh dan farqi: PGIE_CONFIG + DET_INPUT_SZ = 1280.
# Ishlatish:  bash deepstream_v3/run_demo.sh
set -e
cd "$(dirname "$0")/.."

echo "[1/4] Dars jadvali sanasini bugunga tenglash..."
docker exec school_ai_web python3.14 manage.py shell -c "
from django.utils import timezone
from apps.integrations.models import ExternalSchedule
t=timezone.now().date()
ExternalSchedule.objects.filter(id__in=[5,6]).update(date=t)
print('  schedule 5(9-G), 6(11-G) sanasi =', t)
" 2>&1 | grep -v "objects imported"

echo "[2/4] Eski test davomatini tozalash..."
docker exec school_ai_web python3.14 manage.py shell -c "
from django.utils import timezone
from apps.attendance.models import LessonAttendance, AttendanceLock, RecognitionEvent, TrackSession
t=timezone.now().date()
for cam,sid in [(1,5),(2,6)]:
    LessonAttendance.objects.filter(schedule_id=sid).delete()
    AttendanceLock.objects.filter(schedule_id=sid).delete()
    RecognitionEvent.objects.filter(camera_id=cam, recognized_at__date=t).delete()
    TrackSession.objects.filter(camera_id=cam).delete()
print('  tozalandi')
" 2>&1 | grep -v "objects imported"
rm -f deepstream/data/track_names.json

echo "[3/4] Pipeline (1280 rejim) ishga tushmoqda..."
docker rm -f school_ai_ds3_run 2>/dev/null || true
docker run -d --name school_ai_ds3_run --gpus all \
  --network school_ai_project_default -p 8554:8554 \
  -e KAFKA_BOOTSTRAP=kafka:9092 -e CAMERA_IDS=1,2 \
  -e TRACK_SEND_COOLDOWN=3 -e VIS_EVERY=2 \
  -e PGIE_CONFIG=/ds3/configs/pgie_det10g_1280.txt -e DET_INPUT_SZ=1280 \
  -v school_ai_project_insightface_models:/root/.insightface:ro \
  -v "$(pwd)/deepstream_v3/engines:/engines:ro" \
  -v "$(pwd)/deepstream/data:/data:ro" \
  school_ai_ds3:latest --video /data/sinf.mp4 /data/11g.mp4 >/dev/null

echo "[4/4] Tayyor! ~30 soniyada bolalar tanila boshlaydi."
echo ""
echo "  KO'RISH:"
echo "   9-xona:   http://localhost:8000/monitoring/live/1/"
echo "   11-xona:  http://localhost:8000/monitoring/live/2/"
echo ""
echo "  To'xtatish: docker stop school_ai_ds3_run"
