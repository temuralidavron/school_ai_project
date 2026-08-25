#!/bin/bash
# =============================================================================
# PTZ SINOV — kamera to'g'ridan (RTSP tarmog'ida, VPN yoki lokal).
#
#   bash deploy/ptz_test.sh 10.144.0.42                    # admin/admin
#   bash deploy/ptz_test.sh 10.144.0.42 admin PAROL
#
# Kamera web UI da jonli video ochiq tursin — qaysi format kamerani
# BURSA, o'sha to'g'ri. Skript har formatni: chapga 1s -> stop qiladi.
#
# DIQQAT: kamera IP ga TO'G'RIDAN ulanadi (proxy emas). Ya'ni bu mashina
# kamera tarmog'ida (10.144.0.x) bo'lishi SHART — VPN yoki lokal.
# Proxy (edu-api) orqali PTZ O'TMAYDI (2026-08-25 da isbotlandi: proxy
# CGI so'rovga o'z HTML sahifasini qaytaradi, buyruq kameraga yetmaydi).
# =============================================================================
IP="${1:?Ishlatish: bash deploy/ptz_test.sh <IP> [user] [parol]}"
USER_="${2:-admin}"
PASS_="${3:-admin}"

echo "=== PTZ sinov: $IP (user=$USER_) ==="
echo

# 0. Kamera umuman ko'rinadimi
echo "[0] Yetib boradimi..."
if ! timeout 3 bash -c "echo > /dev/tcp/$IP/80" 2>/dev/null; then
  echo "  XATO: $IP:80 yopiq — kamera ko'rinmayapti."
  echo "  Bu mashina 10.144.0.x tarmog'idami? (VPN ulanganmi?)  ip a | grep 10.144"
  exit 1
fi
echo "  OK: kamera javob beryapti"
echo

# Formatlar: nom | chapga URL | stop URL
FORMATS=(
  "hi3510|/web/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act=left&-speed=10|/web/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act=stop&-speed=10"
  "hi3510_alt|/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act=left&-speed=10|/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act=stop&-speed=10"
  "dahua|/cgi-bin/ptz.cgi?action=start&channel=0&code=Left&arg1=0&arg2=1&arg3=0|/cgi-bin/ptz.cgi?action=stop&channel=0&code=Left&arg1=0&arg2=1&arg3=0"
  "hikvision|/ISAPI/PTZCtrl/channels/1/continuous|/ISAPI/PTZCtrl/channels/1/continuous"
  "axis|/axis-cgi/com/ptz.cgi?move=left|/axis-cgi/com/ptz.cgi?move=stop"
  "foscam|/cgi-bin/CGIProxy.fcgi?cmd=ptzMoveLeft&usr=$USER_&pwd=$PASS_|/cgi-bin/CGIProxy.fcgi?cmd=ptzStopRun&usr=$USER_&pwd=$PASS_"
  "cgi_move|/cgi-bin/ptz.cgi?move=left|/cgi-bin/ptz.cgi?move=stop"
)

echo "[1] Har formatni sinash (chapga 1s -> stop). Video ekranini kuzating:"
echo
for f in "${FORMATS[@]}"; do
  NAME="${f%%|*}"; REST="${f#*|}"; GO="${REST%%|*}"; STOP="${REST#*|}"
  printf "  %-12s: " "$NAME"

  if [ "$NAME" = "hikvision" ]; then
    # Hikvision ISAPI — XML PUT, digest auth
    C1=$(timeout 8 curl -s -o /dev/null -w "%{http_code}" --digest -u "$USER_:$PASS_" \
      -X PUT -H "Content-Type: application/xml" \
      -d '<PTZData><pan>-30</pan><tilt>0</tilt></PTZData>' "http://$IP$GO" 2>/dev/null)
    sleep 1
    timeout 8 curl -s -o /dev/null --digest -u "$USER_:$PASS_" \
      -X PUT -H "Content-Type: application/xml" \
      -d '<PTZData><pan>0</pan><tilt>0</tilt></PTZData>' "http://$IP$STOP" 2>/dev/null
  else
    # CGI — oddiy va digest ikkalasini sinab (kamera qaysisini tan olsa)
    C1=$(timeout 8 curl -s -o /dev/null -w "%{http_code}" -u "$USER_:$PASS_" "http://$IP$GO" 2>/dev/null)
    sleep 1
    timeout 8 curl -s -o /dev/null -u "$USER_:$PASS_" "http://$IP$STOP" 2>/dev/null
  fi
  echo "HTTP $C1  $([ "$C1" = "200" ] && echo '<- kamera burildimi? kuzating' || echo '')"
  sleep 1
done

echo
echo "=== Qaysi format kamerani BURDI — o'shani eslab qoling ==="
echo "RTSP URL topish uchun:"
echo "  bash deploy/probe_cameras.sh --csv deploy/cameras_yangi_obyekt.csv --user $USER_ --password $PASS_"
