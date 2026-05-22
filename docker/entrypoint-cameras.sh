#!/bin/bash
# Kamera konteyner: barcha aktiv kamera streamlarini ishga tushiradi
set -e

cd /app

echo "[cameras] DB tayyorligini kutmoqda..."
python3.14 - <<'PY'
import os, time, sys
import psycopg2
host = os.environ.get("DB_HOST", "db")
port = os.environ.get("DB_PORT", "5432")
name = os.environ.get("DB_NAME", "school_ai")
user = os.environ.get("DB_USER", "postgres")
pw   = os.environ.get("DB_PASSWORD", "")
for i in range(120):
    try:
        psycopg2.connect(host=host, port=port, dbname=name, user=user, password=pw).close()
        print(f"[cameras] DB ulandi ({i}s)")
        sys.exit(0)
    except Exception:
        time.sleep(1)
print("[cameras] DB ga ulanib bo'lmadi — 120s timeout")
sys.exit(1)
PY

# RTSP TCP transport — Python/cv2 ishga tushishidan OLDIN (shell darajasi).
# UDP paket yo'qolishi h264 "decoding MB" artefaktlariga sabab → TCP yo'qotadi.
# Yagona ishonchli usul: modul-level setdefault cv2 boshqa moduldan oldin
# yuklansa kech qoladi, shell export esa kafolatli.
export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp|timeout;8000000"

ACCEPT="${AI_ACCEPT_THRESHOLD:-0.55}"
REVIEW="${AI_REVIEW_THRESHOLD:-0.42}"
INTERVAL="${AI_FRAME_INTERVAL:-1.0}"

echo "[cameras] Stream boshlanmoqda  accept=$ACCEPT review=$REVIEW interval=$INTERVAL"
exec python3.14 manage.py run_camera_stream \
    --all \
    --accept-threshold "$ACCEPT" \
    --review-threshold "$REVIEW" \
    --frame-interval "$INTERVAL"
