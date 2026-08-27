#!/bin/bash
# =============================================================================
# RTSP TAYYORGARLIK — maktab serverida, kamera tarmog'ida ishga tushiriladi.
#
#   bash deploy/rtsp_tayyorla.sh                   zondlaydi va hisobot beradi
#   bash deploy/rtsp_tayyorla.sh --apply           topilganini bazaga yozadi
#   bash deploy/rtsp_tayyorla.sh --scan 10.144.4   IP lar noma'lum bo'lsa (/24)
#   bash deploy/rtsp_tayyorla.sh --user admin --pass PAROL
#
# NEGA KERAK: export_ds_sources.py:123 da Camera.ip_address CSV dan USTUVOR.
# Bazada eski IP tursa, deploy/camera_ips.csv jimgina e'tiborsiz qoladi va
# pipeline noto'g'ri manzilga ulanadi — xato hech qayerda ko'rinmaydi, shunchaki
# kadr kelmaydi. Bu skript haqiqatni tarmoqdan aniqlaydi va bazani moslaydi.
# Shundan keyin `bash deploy/start.sh rtsp` qo'shimcha argumentsiz ishlaydi.
#
# add_cameras --csv ISHLATMANG: u stream_url bo'yicha update_or_create qiladi,
# ya'ni RTSP url bilan YANGI kamera qatorlari yaratadi (id lar siljiydi,
# kamera<->xona bog'lanishi uziladi). Bu skript mavjud qatorlarni id bo'yicha
# joyida yangilaydi.
# =============================================================================
set -u
cd "$(dirname "$0")/.."

ORG_ID=16
RT_USER="admin"
RT_PASS="admin"
CSV=""
SCAN=""
APPLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --org-id) ORG_ID="$2"; shift 2 ;;
    --user)   RT_USER="$2"; shift 2 ;;
    --pass|--password) RT_PASS="$2"; shift 2 ;;
    --csv)    CSV="$2"; shift 2 ;;
    --scan)   SCAN="$2"; shift 2 ;;    # masalan: 10.144.4  (/24 bo'ylab 554-port)
    --apply)  APPLY=1; shift ;;
    *) sed -n '3,10p' "$0" | sed 's/^# \?//'; exit 1 ;;
  esac
done

echo "============================================================"
echo " RTSP TAYYORGARLIK — tashkilot $ORG_ID"
echo "============================================================"

# Tarmoq: server kamera tarmog'ida bo'lmasa zondlashning ma'nosi yo'q.
MYIP=$(ip -4 -o addr show 2>/dev/null | grep -oE '10\.144\.[0-9]+\.[0-9]+' | head -1)
if [ -n "$MYIP" ]; then
  echo "  server IP: $MYIP  (kamera tarmog'ida)"
else
  echo "  DIQQAT: bu mashina 10.144.x.x tarmog'ida EMAS."
  ip -4 -o addr show 2>/dev/null | grep -v ' lo ' | awk '{print "           "$2": "$4}'
  echo "           Kameralar ko'rinmasligi mumkin — baribir zondlaymiz."
fi

if ! docker ps --format '{{.Names}}' | grep -q '^school_ai_web$'; then
  echo "  XATO: school_ai_web ishlamayapti.  docker compose up -d web"
  exit 1
fi

# Default CSV 225-maktab (org 16) IP lari bilan to'ldirilgan — boshqa org
# uchun avtomatik olinmaydi (noto'g'ri kameralarga ulanish xavfi).
[ -z "$CSV" ] && [ "$ORG_ID" = "16" ] && CSV="deploy/camera_ips.csv"

# CSV ni "id;ip,id;ip" ko'rinishida beramiz — konteyner deploy/ ni ko'rmaydi.
CSV_PAIRS=""
if [ -n "$CSV" ] && [ -f "$CSV" ]; then
  CSV_PAIRS=$(grep -vE '^\s*#|^\s*$' "$CSV" \
    | tr ',' ';' \
    | awk -F';' 'NF>=2 {gsub(/ /,""); printf "%s;%s,", $1, $NF}')
  echo "  ip-map:    $CSV ($(echo "$CSV_PAIRS" | tr ',' '\n' | grep -c ';') qator)"
else
  echo "  ip-map:    yo'q ($CSV topilmadi)"
fi
[ -n "$SCAN" ] && echo "  skanerlash: ${SCAN}.1-254 (554-port)"
[ "$APPLY" = "1" ] && echo "  rejim:     --apply (baza YANGILANADI)" \
                   || echo "  rejim:     faqat hisobot (baza o'zgarmaydi)"
echo

docker compose exec -T \
  -e RT_ORG="$ORG_ID" -e RT_USER="$RT_USER" -e RT_PASS="$RT_PASS" \
  -e RT_CSV="$CSV_PAIRS" -e RT_SCAN="$SCAN" -e RT_APPLY="$APPLY" \
  web python3.14 manage.py shell --no-imports <<'PY'
import os
import socket
from concurrent.futures import ThreadPoolExecutor

from apps.cameras.models import Camera

ORG = int(os.environ["RT_ORG"])
USER = os.environ["RT_USER"]
PASS = os.environ["RT_PASS"]
APPLY = os.environ["RT_APPLY"] == "1"
SCAN = os.environ.get("RT_SCAN", "").strip()

# /stream1 birinchi — 225-maktabda tasdiqlangan (2026-08-26). 102 (Hikvision
# kichik oqim) ro'yxatda umuman yo'q: yuz 30-40 px bo'lib tanilmaydi.
PATHS = ["/stream1", "/Streaming/Channels/101",
         "/cam/realmonitor?channel=1&subtype=0", "/h264/ch1/main/av_stream",
         "/media/video1", "/live/ch0", "/onvif1", "/11"]

csv_map = {}
for juft in os.environ.get("RT_CSV", "").split(","):
    if ";" in juft:
        k, v = juft.split(";", 1)
        if k.strip() and v.strip():
            csv_map[k.strip()] = v.strip()

cams = list(Camera.objects.filter(organization_id=ORG).order_by("id"))
print(f"  bazada {len(cams)} kamera (org {ORG})")


def port_ochiq(ip, port=554, t=2.0):
    try:
        with socket.create_connection((ip, port), timeout=t):
            return True
    except OSError:
        return False


# 1-qadam: nomzod IP lar — bazadagi, CSV dagi va (so'ralsa) skanerdan.
nomzod = {}                       # ip -> sabab ro'yxati
for c in cams:
    ip = (c.ip_address or "").strip()
    if ip:
        nomzod.setdefault(ip, []).append(f"baza:{c.id}")
for cid, ip in csv_map.items():
    nomzod.setdefault(ip, []).append(f"csv:{cid}")

if SCAN:
    hammasi = [f"{SCAN}.{i}" for i in range(1, 255)]
    with ThreadPoolExecutor(max_workers=64) as ex:
        for ip, ochiq in zip(hammasi, ex.map(lambda x: port_ochiq(x, 554, 1.0), hammasi)):
            if ochiq:
                nomzod.setdefault(ip, []).append("skaner")
    print(f"  skaner: {SCAN}.0/24 da 554-port ochiq {sum(1 for v in nomzod.values() if 'skaner' in v)} ta host")

print(f"  zondlanadi: {len(nomzod)} ta IP\n")

# 2-qadam: 554-port. Yopiq bo'lsa kadr o'qishga urinish ham vaqt isrofi.
with ThreadPoolExecutor(max_workers=32) as ex:
    ochiqlar = dict(zip(nomzod, ex.map(port_ochiq, nomzod)))


def yol_top(ip):
    """Haqiqiy kadr o'qiydi — 'ochiq port' hali 'ishlaydigan oqim' emas."""
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;6000000"
    import cv2
    for yol in PATHS:
        cap = cv2.VideoCapture(f"rtsp://{USER}:{PASS}@{ip}:554{yol}", cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 6000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 6000)
        except Exception:
            pass
        try:
            if cap.isOpened():
                ok, kadr = cap.read()
                if ok and kadr is not None:
                    return yol, f"{kadr.shape[1]}x{kadr.shape[0]}"
        finally:
            cap.release()
    return None, None


def _ip_kalit(x):
    # Camera.ip_address validatsiyasiz TextField — iflos qiymat (hostname,
    # "ip:port", bo'sh) sortni yiqitmasin: IP bo'lmaganlar oxiriga tushadi.
    try:
        return (0, tuple(int(p) for p in x.split(".")))
    except ValueError:
        return (1, (x,))


tirik = {}                        # ip -> (yol, o'lcham)
for ip in sorted(nomzod, key=_ip_kalit):
    sabab = ",".join(nomzod[ip])
    if not ochiqlar.get(ip):
        print(f"  {ip:<15} 554 YOPIQ            ({sabab})")
        continue
    yol, olcham = yol_top(ip)
    if yol:
        tirik[ip] = (yol, olcham)
        print(f"  {ip:<15} KADR OK  {olcham:<10} {yol}   ({sabab})")
    else:
        print(f"  {ip:<15} 554 ochiq, kadr YO'Q ({sabab}) — login/parol yoki yo'l boshqa")

print()
print("  === Kamera bo'yicha xulosa ===")
yangilanadi, muammo, bog_lanmagan = [], [], set(tirik)

for c in cams:
    db_ip = (c.ip_address or "").strip()
    csv_ip = csv_map.get(str(c.id), "")
    db_ok, csv_ok = db_ip in tirik, csv_ip in tirik
    bog_lanmagan.discard(db_ip)
    bog_lanmagan.discard(csv_ip)

    if db_ok and csv_ok and db_ip != csv_ip:
        # Ikkalasi ham javob beryapti — qaysi biri shu xona ekanini tarmoq
        # aytib bera olmaydi. Taxmin qilish = davomatni boshqa sinfga yozish.
        muammo.append(f"cam {c.id} ({c.name}): baza {db_ip} ham, CSV {csv_ip} ham tirik "
                      f"— qaysi biri ekanini MJPEG da ko'rib qo'lda tanlang")
        continue
    tanlangan = db_ip if db_ok else (csv_ip if csv_ok else "")
    if not tanlangan:
        muammo.append(f"cam {c.id} ({c.name}): tirik IP yo'q "
                      f"(baza={db_ip or '-'}, csv={csv_ip or '-'})")
        continue
    yol, olcham = tirik[tanlangan]
    # Zond aynan USER:PASS@ip:554 bilan kadr oldi — bazada boshqa port/login
    # qolsa pipeline baribir ishlamaydi, shularni ham solishtiramiz.
    ozgardi = (tanlangan != db_ip) or ((c.path or "") != yol) \
        or (c.port or 0) != 554 \
        or (c.username or "") != USER or (c.password or "") != PASS \
        or not c.is_active_stream or not (c.stream_url or "").strip()
    belgi = "yangilanadi" if ozgardi else "o'zgarishsiz"
    print(f"  cam {c.id:<3} {c.name:<10} -> {tanlangan:<15} {yol:<28} {olcham:<10} {belgi}")
    if ozgardi:
        yangilanadi.append((c, tanlangan, yol))

for m in muammo:
    print(f"  MUAMMO: {m}")
for ip in sorted(bog_lanmagan):
    print(f"  BOG'LANMAGAN: {ip} ({tirik[ip][1]}) — bazada bunday kamera yo'q")

print()
if not APPLY:
    print(f"  Hisobot tugadi. Baza o'zgarmadi ({len(yangilanadi)} kamera yangilanishi kerak).")
    print("  Yozish uchun:  bash deploy/rtsp_tayyorla.sh --apply")
else:
    for c, ip, yol in yangilanadi:
        c.ip_address = ip
        c.path = yol
        c.port = 554
        c.username = USER
        c.password = PASS
        # export_ds_sources faqat is_active_stream=True va stream_url bo'sh
        # bo'lmagan kameralarni oladi — busiz tuzatilgan kamera baribir
        # sources'ga tushmay qolardi.
        c.is_active_stream = True
        if not (c.stream_url or "").strip():
            c.stream_url = f"rtsp://{USER}:{PASS}@{ip}:554{yol}"
        c.save(update_fields=["ip_address", "path", "port", "username",
                              "password", "is_active_stream", "stream_url"])
        print(f"  yozildi: cam {c.id} -> {ip}{yol}")
    print(f"\n  {len(yangilanadi)} kamera yangilandi.")
    print("  Endi:  bash deploy/start.sh rtsp --threshold 0.50")
PY

echo
echo "============================================================"
if [ "$APPLY" = "1" ]; then
  echo " Baza RTSP ga moslandi. Ishga tushirish:"
  echo "   bash deploy/start.sh rtsp --threshold 0.50"
else
  echo " Hisobot tugadi (baza o'zgarmadi). Yozish uchun:"
  echo "   bash deploy/rtsp_tayyorla.sh --apply"
fi
echo " Tirik ko'rish:  http://127.0.0.1:8554/mjpeg/0"
echo "============================================================"
