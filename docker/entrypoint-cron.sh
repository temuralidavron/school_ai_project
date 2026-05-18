#!/bin/bash
# Cron konteyner: rejalashtirilgan Django vazifalarni bajaradi
set -e

cd /app
mkdir -p /app/logs
touch /app/logs/cron.log

echo "[cron] crontab o'rnatilmoqda..."
crontab /app/docker/crontab
crontab -l

# cron.log ni stdout ga ham chiqaramiz (docker compose logs cron uchun)
tail -F /app/logs/cron.log &

echo "[cron] cron daemon ishga tushmoqda (Asia/Tashkent)..."
exec cron -f
