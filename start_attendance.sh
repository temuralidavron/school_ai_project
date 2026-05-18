#!/bin/bash
# 71-maktab davomat tizimini ishga tushirish
# Ishlatish: bash start_attendance.sh

ORG_ID=32  # 71-maktab

cd "$(dirname "$0")"
source .venv/bin/activate

echo "======================================"
echo " DAVOMAT TIZIMI ISHGA TUSHMOQDA"
echo " Maktab: 71-maktab (org_id=$ORG_ID)"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "======================================"

# 1. TrackSession tozalash
echo ""
echo "[1] Eski tracklar tozalanmoqda..."
python manage.py shell -c "
from apps.attendance.models import TrackSession
d = TrackSession.objects.all().delete()
print(f'  {d[0]} ta track ochirildi')
" 2>/dev/null | grep -v "objects imported"

# 2. Faqat 71-maktab uchun jadval sync
echo ""
echo "[2] 71-maktab jadvali sync qilinmoqda..."
python manage.py shell -c "
from apps.integrations.services import SkudSyncService
import datetime
svc = SkudSyncService()
today = datetime.date.today().isoformat()
try:
    r = svc.sync_schedule($ORG_ID, target_date=today)
    print(f'  {r.get(\"synced_schedule_items\", 0)} ta dars yozuvi yangilandi')
except Exception as e:
    print(f'  XATO: {e}')
" 2>/dev/null | grep -v "objects imported"

# 3. Faqat 71-maktab uchun embedding
echo ""
echo "[3] 71-maktab embeddinglari yangilanmoqda..."
python manage.py build_all_embeddings --org-id $ORG_ID --batch-size 300 2>/dev/null | grep -v "objects imported"

# 4. Embedding statistika
echo ""
echo "[4] Embedding holati (71-maktab):"
python manage.py shell -c "
from apps.face_data.models import StudentEmbedding
from apps.integrations.models import ExternalStudent
total_s = ExternalStudent.objects.filter(organization__organization_id=$ORG_ID).count()
total_e = StudentEmbedding.objects.filter(is_active=True, student__organization__organization_id=$ORG_ID).values('student').distinct().count()
pct = total_e * 100 // total_s if total_s else 0
print(f'  {total_e}/{total_s} talabada embedding bor ({pct}%)')
" 2>/dev/null | grep -v "objects imported"

# 5. Bugungi jadval tekshiruvi
echo ""
echo "[5] Bugungi darslar:"
python manage.py shell -c "
from apps.integrations.models import ExternalSchedule
from django.utils import timezone
from zoneinfo import ZoneInfo
import datetime
tz = ZoneInfo('Asia/Tashkent')
today = timezone.now().astimezone(tz).date()
count = ExternalSchedule.objects.filter(organization__organization_id=$ORG_ID, date=today).count()
print(f'  {today} — {count} ta dars topildi')
" 2>/dev/null | grep -v "objects imported"

# 6. Kamera stream ishga tushirish
echo ""
echo "[6] Kameralar ishga tushmoqda (71-maktab, 18 ta)..."
echo "  accept_threshold=0.55  review_threshold=0.42  frame_interval=1.0"
python manage.py run_camera_stream --all --accept-threshold 0.55 --review-threshold 0.42 --frame-interval 1.0

echo ""
echo "======================================"
echo " TIZIM TOXTATILDI: $(date '+%H:%M:%S')"
echo "======================================"
