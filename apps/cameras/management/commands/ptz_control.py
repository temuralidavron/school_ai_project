"""
PTZ boshqaruv — kamerani burish/zoom (CGI va ONVIF).

Kamera IP ga TO'G'RIDAN ulanadi. Ya'ni server kamera tarmog'ida bo'lishi
shart (VPN yoki lokal). Proxy (edu-api) orqali PTZ O'TMAYDI — 2026-08-25 da
isbotlangan: proxy CGI so'rovga o'z HTML sahifasini qaytaradi.

Ishlatish:
    # 1) Formatni topish (kamera burilishini kuzatib turing)
    python manage.py ptz_control --ip 10.144.0.42 --detect

    # 2) Topilgan format bilan burish
    python manage.py ptz_control --ip 10.144.0.42 --format hi3510 --move left --duration 1.5
    python manage.py ptz_control --camera-id 5 --format dahua --move right

    # 3) Barcha kameralarni bir yo'la tekshirish (CSV dan)
    python manage.py ptz_control --csv deploy/cameras_yangi_obyekt.csv --detect
"""
import time

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from django.core.management.base import BaseCommand

# Har format: harakat nomlarini CGI yo'liga aylantiradi.
# {act} — yo'nalish, {ss} — start/stop (dahua uchun).
FORMATS = {
    "hi3510": {
        "url": "/web/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act={act}&-speed={speed}",
        "moves": {"left": "left", "right": "right", "up": "up", "down": "down",
                  "stop": "stop", "zoom_in": "zoomin", "zoom_out": "zoomout"},
    },
    "hi3510_alt": {
        "url": "/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act={act}&-speed={speed}",
        "moves": {"left": "left", "right": "right", "up": "up", "down": "down",
                  "stop": "stop", "zoom_in": "zoomin", "zoom_out": "zoomout"},
    },
    "dahua": {
        "url": "/cgi-bin/ptz.cgi?action={ss}&channel=0&code={act}&arg1=0&arg2={speed}&arg3=0",
        "moves": {"left": "Left", "right": "Right", "up": "Up", "down": "Down",
                  "stop": "Left", "zoom_in": "ZoomTele", "zoom_out": "ZoomWide"},
        "digest": True,
    },
    "hikvision": {  # ISAPI — XML PUT
        "url": "/ISAPI/PTZCtrl/channels/1/continuous",
        "moves": {"left": -60, "right": 60, "up": 0, "down": 0, "stop": 0,
                  "zoom_in": 0, "zoom_out": 0},
        "digest": True,
        "isapi": True,
    },
    "axis": {
        "url": "/axis-cgi/com/ptz.cgi?move={act}",
        "moves": {"left": "left", "right": "right", "up": "up", "down": "down",
                  "stop": "stop", "zoom_in": "zoom+", "zoom_out": "zoom-"},
        "digest": True,
    },
    "foscam": {
        "url": "/cgi-bin/CGIProxy.fcgi?cmd={act}&usr={user}&pwd={pwd}",
        "moves": {"left": "ptzMoveLeft", "right": "ptzMoveRight", "up": "ptzMoveUp",
                  "down": "ptzMoveDown", "stop": "ptzStopRun",
                  "zoom_in": "zoomIn", "zoom_out": "zoomOut"},
    },
    "cgi_move": {
        "url": "/cgi-bin/ptz.cgi?move={act}",
        "moves": {"left": "left", "right": "right", "up": "up", "down": "down",
                  "stop": "stop", "zoom_in": "zoomin", "zoom_out": "zoomout"},
    },
}


def _send(ip, fmt_name, move, user, pwd, speed=10, timeout=6):
    """Bitta PTZ buyrug'ini yuboradi. (ok, status, xato) qaytaradi."""
    f = FORMATS[fmt_name]
    act = f["moves"].get(move)
    if act is None:
        return False, 0, f"'{move}' bu formatda yo'q"

    auth = (HTTPDigestAuth(user, pwd) if f.get("digest")
            else HTTPBasicAuth(user, pwd))
    try:
        if f.get("isapi"):
            pan = act if move in ("left", "right") else 0
            tilt = f["moves"]["up"] if move == "up" else (-60 if move == "down" else 0)
            if move == "stop":
                pan = tilt = 0
            xml = f"<PTZData><pan>{pan}</pan><tilt>{tilt}</tilt></PTZData>"
            r = requests.put(f"http://{ip}{f['url']}", data=xml, auth=auth,
                             headers={"Content-Type": "application/xml"}, timeout=timeout)
        else:
            ss = "stop" if move == "stop" else "start"
            url = f["url"].format(act=act, speed=speed, ss=ss, user=user, pwd=pwd)
            r = requests.get(f"http://{ip}{url}", auth=auth, timeout=timeout)
        return r.status_code in (200, 204), r.status_code, ""
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)[:60]


class Command(BaseCommand):
    help = "PTZ: kamerani burish yoki mos CGI formatini aniqlash"

    def add_arguments(self, p):
        p.add_argument("--ip", type=str, default=None)
        p.add_argument("--camera-id", type=int, default=None, help="Camera.ip_address dan oladi")
        p.add_argument("--csv", type=str, default=None, help="name;...;IP — hammasini sinaydi")
        p.add_argument("--user", type=str, default="admin")
        p.add_argument("--password", type=str, default="admin")
        p.add_argument("--detect", action="store_true", help="Mos formatni topish")
        p.add_argument("--format", type=str, default=None, choices=list(FORMATS))
        p.add_argument("--move", type=str, default="left",
                       choices=["left", "right", "up", "down", "stop", "zoom_in", "zoom_out"])
        p.add_argument("--duration", type=float, default=1.0, help="Necha soniya (keyin stop)")
        p.add_argument("--speed", type=int, default=10)

    def handle(self, *a, **o):
        ips = self._collect_ips(o)
        if not ips:
            self.stderr.write(self.style.ERROR(
                "--ip, --camera-id yoki --csv bering"))
            return

        for name, ip in ips:
            self.stdout.write(self.style.SUCCESS(f"\n=== {name} ({ip}) ==="))
            if not self._reachable(ip):
                self.stdout.write(self.style.ERROR(
                    "  yetib bo'lmadi (80-port yopiq) — VPN ulanmagan yoki kamera o'chiq"))
                continue
            if o["detect"] or not o["format"]:
                self._detect(ip, o)
            else:
                self._move(ip, o["format"], o)

    # ── yordamchilar ─────────────────────────────────────────────────────────
    def _collect_ips(self, o):
        if o["ip"]:
            return [("kamera", o["ip"])]
        if o["camera_id"]:
            from apps.cameras.models import Camera
            c = Camera.objects.filter(id=o["camera_id"]).first()
            if c and c.ip_address:
                return [(c.name or f"cam{c.id}", c.ip_address)]
            self.stderr.write(self.style.ERROR("camera_id topilmadi yoki ip_address bo'sh"))
            return []
        if o["csv"]:
            out = []
            with open(o["csv"]) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(";")
                    if len(parts) >= 2:
                        out.append((parts[0], parts[-1]))
            return out
        return []

    def _reachable(self, ip, port=80, timeout=3):
        import socket
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _detect(self, ip, o):
        """Har formatni sinaydi: chapga -> stop. Kamera burilsa — o'sha format."""
        self.stdout.write("  Formatlar sinalmoqda (video ekranini kuzating):")
        ishladi = []
        for fmt in FORMATS:
            ok, code, err = _send(ip, fmt, "left", o["user"], o["password"], o["speed"])
            time.sleep(o["duration"])
            _send(ip, fmt, "stop", o["user"], o["password"], o["speed"])
            belgi = "<- BURILDIMI?" if ok else ""
            self.stdout.write(f"    {fmt:12s} HTTP {code or '---'} {err} {belgi}")
            if ok:
                ishladi.append(fmt)
            time.sleep(0.5)

        self.stdout.write("")
        if ishladi:
            self.stdout.write(self.style.SUCCESS(
                f"  Javob bergan: {', '.join(ishladi)}"))
            self.stdout.write(
                f"  Qaysi biri kamerani HAQIQATAN burgan bo'lsa, o'shani ishlating:\n"
                f"    manage.py ptz_control --ip {ip} --format {ishladi[0]} --move left")
        else:
            self.stdout.write(self.style.WARNING(
                "  Hech biri javob bermadi — login/parol yoki brend boshqa.\n"
                f"  Kamera web UI ni oching: http://{ip}"))

    def _move(self, ip, fmt, o):
        move, dur = o["move"], o["duration"]
        ok, code, err = _send(ip, fmt, move, o["user"], o["password"], o["speed"])
        self.stdout.write(f"  {fmt} / {move}: HTTP {code or '---'} {err}")
        if move != "stop" and ok:
            time.sleep(dur)
            _send(ip, fmt, "stop", o["user"], o["password"], o["speed"])
            self.stdout.write(f"  to'xtatildi ({dur}s)")
