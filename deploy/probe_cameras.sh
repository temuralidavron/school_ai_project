#!/bin/bash
# 14-maktab kameralarini ZONDLASH — maktab tarmog'ida ishga tushiriladi.
#
# Nima qiladi: har IP uchun ping -> 554-port -> bir necha RTSP path variantini
# HAQIQIY kadr o'qib sinaydi -> ishlaganini topib CSV yozadi.
#
# Sinov OpenCV (FFMPEG/TCP) bilan qilinadi — `cameras` servisi ham aynan shuni
# ishlatadi, ya'ni "zondlash ishladi" = "tizim ham ishlaydi".
#
# Ishlatish (maktab serverida, 10.144.10.x tarmog'ida):
#   bash deploy/probe_cameras.sh
#   bash deploy/probe_cameras.sh --user admin --password SIZNING_PAROL
#
# Natija: deploy/cameras_14.csv  (name;stream_url;skud_device_id)
set -u

USER_="admin"
PASS_="${CAMERA_PASSWORD:-admin}"
while [ $# -gt 0 ]; do
  case "$1" in
    --user) USER_="$2"; shift 2 ;;
    --password) PASS_="$2"; shift 2 ;;
    *) echo "Noma'lum argument: $1"; exit 1 ;;
  esac
done

# SKUD org 59 dan olingan: classRoomName;deviceId
CAMS="A5-xona;10.144.10.10
B5-xona;10.144.10.11
A4-xona;10.144.10.12
A6-xona;10.144.10.13
A7-xona;10.144.10.14
B11-xona;10.144.10.15
A8-xona;10.144.10.16"

OUT="deploy/cameras_14.csv"
TMP=$(mktemp)

echo "=== 14-maktab kameralarini zondlash ==="
echo "  user=$USER_"
MYIP=$(ip -4 addr show 2>/dev/null | grep -oE 'inet 10\.144\.[0-9.]+' | head -1 | awk '{print $2}')
if [ -n "$MYIP" ]; then
  echo "  bizning IP: $MYIP  (10.144.x.x — to'g'ri tarmoq)"
else
  echo "  DIQQAT: bu mashina 10.144.x.x tarmog'ida EMAS —"
  echo "          $(ip -4 addr show 2>/dev/null | grep -oE 'inet [0-9.]+' | grep -v '127.0.0.1' | head -3 | awk '{print $2}' | tr '\n' ' ')"
  echo "          kameralar ko'rinmasligi mumkin. Baribir davom etamiz."
fi
echo

if ! docker ps --format '{{.Names}}' | grep -q '^school_ai_web$'; then
  echo "  XATO: school_ai_web ishlamayapti. Avval: docker compose up -d web"
  exit 1
fi

printf "name;stream_url;skud_device_id\n" > "$TMP"
TOPILDI=0; JAMI=0

while IFS=';' read -r NAME IP; do
  [ -z "$IP" ] && continue
  JAMI=$((JAMI+1))
  printf "  %-10s %-14s " "$NAME" "$IP"

  if ! timeout 3 ping -c1 -W2 "$IP" >/dev/null 2>&1; then
    echo "ping YO'Q -> o'tkazildi"; continue
  fi
  if ! timeout 3 bash -c "echo > /dev/tcp/$IP/554" 2>/dev/null; then
    echo "ping OK, 554-port YOPIQ -> o'tkazildi"; continue
  fi
  printf "ping OK, 554 ochiq | "

  # OpenCV bilan haqiqiy kadr o'qish. Ishlagan birinchi path qaytariladi.
  FOUND=$(docker exec -e PROBE_IP="$IP" -e PROBE_USER="$USER_" -e PROBE_PASS="$PASS_" \
    school_ai_web python3.14 -c "
import os, sys
os.environ.setdefault('OPENCV_FFMPEG_CAPTURE_OPTIONS', 'rtsp_transport;tcp|stimeout;6000000')
import cv2
ip, u, p = os.environ['PROBE_IP'], os.environ['PROBE_USER'], os.environ['PROBE_PASS']
paths = ['/stream1', '/Streaming/Channels/101', '/cam/realmonitor?channel=1&subtype=0',
         '/h264/ch1/main/av_stream', '/media/video1', '/live/ch0', '/onvif1', '/11']
for path in paths:
    uri = f'rtsp://{u}:{p}@{ip}:554{path}'
    cap = cv2.VideoCapture(uri, cv2.CAP_FFMPEG)
    try:
        cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 6000)
        cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 6000)
    except Exception:
        pass
    ok = False
    if cap.isOpened():
        ok, frame = cap.read()
        if ok and frame is not None:
            print(f'{path}|{frame.shape[1]}x{frame.shape[0]}')
            cap.release(); sys.exit(0)
    cap.release()
sys.exit(1)
" 2>/dev/null)

  if [ -n "$FOUND" ]; then
    PATH_="${FOUND%%|*}"; RES="${FOUND##*|}"
    echo "ISHLADI -> $PATH_ ($RES)"
    printf "%s;rtsp://%s:%s@%s:554%s;%s\n" "$NAME" "$USER_" "$PASS_" "$IP" "$PATH_" "$IP" >> "$TMP"
    TOPILDI=$((TOPILDI+1))
  else
    echo "RTSP path TOPILMADI (8 variant sinaldi)"
  fi
done <<< "$CAMS"

echo
echo "=== NATIJA: $TOPILDI / $JAMI kamera ishladi ==="
if [ "$TOPILDI" -gt 0 ]; then
  mv "$TMP" "$OUT"; chmod 600 "$OUT"
  echo "  CSV yozildi: $OUT  (chmod 600 — ichida parol bor)"
  echo
  echo "  Keyingi qadamlar:"
  echo "    docker compose exec web python3.14 manage.py add_cameras --org-id 59 --csv $OUT --activate"
  echo "    docker compose exec web python3.14 manage.py export_ds_sources --org-id 59 --out deepstream_v3/configs/sources.json"
  echo "    docker compose --profile deepstream up -d ds3"
  echo "    docker logs -f school_ai_ds3        # 'source N ulandi' + fps oqimi"
else
  rm -f "$TMP"
  echo "  Hech qaysi kamera javob bermadi. Tartib bilan tekshiring:"
  echo "   1) server 10.144.10.x tarmog'idami        -> ip a"
  echo "   2) kamera yoqilganmi, IP to'g'rimi        -> ping 10.144.10.10"
  echo "   3) login/parol                            -> --user / --password bilan qayta"
  echo "   4) kamera veb-interfeysi                  -> brauzerda http://10.144.10.10"
  echo "      (u yerda RTSP manzili ko'rsatilgan bo'ladi — topilsa menga ayting,"
  echo "       skriptdagi paths ro'yxatiga qo'shamiz)"
fi
