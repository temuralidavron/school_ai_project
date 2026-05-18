#!/bin/bash
# Web konteyner: migratsiya + static + gunicorn (API/admin)
set -e

cd /app

echo "[web] DB tayyorligini kutmoqda..."
python3.14 - <<'PY'
import os, time, sys
import psycopg2
host = os.environ.get("DB_HOST", "db")
port = os.environ.get("DB_PORT", "5432")
name = os.environ.get("DB_NAME", "school_ai")
user = os.environ.get("DB_USER", "postgres")
pw   = os.environ.get("DB_PASSWORD", "")
for i in range(60):
    try:
        psycopg2.connect(host=host, port=port, dbname=name, user=user, password=pw).close()
        print(f"[web] DB ulandi ({i}s)")
        sys.exit(0)
    except Exception:
        time.sleep(1)
print("[web] DB ga ulanib bo'lmadi — 60s timeout")
sys.exit(1)
PY

echo "[web] Migratsiyalar..."
python3.14 manage.py migrate --noinput

echo "[web] collectstatic..."
python3.14 manage.py collectstatic --noinput

echo "[web] Gunicorn ishga tushmoqda..."
exec python3.14 -m gunicorn -c deploy/gunicorn.conf.py config.wsgi:application \
    --bind 0.0.0.0:8000
