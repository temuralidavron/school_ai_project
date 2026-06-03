"""
PTZ CGI formatini avtomatik aniqlash (ONVIF ishlamaganда).

browse/index.asp web UI'li generic/Hi3510 kameralar HTTP CGI orqali
boshqariladi. Bu komanda keng tarqalgan CGI formatlarni navbatma-navbat
sinab, kamerani CHAPGA buradi. Web UI'da jonli video ochiq tursin —
qaysi format kamerani harakatlantirsa, o'sha format to'g'ri.

Ishlatish:
    python manage.py test_ptz_cgi --ip 10.144.4.2 --user admin --password admin
    python manage.py test_ptz_cgi --camera-id 10
"""
import time

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
from django.core.management.base import BaseCommand

from apps.cameras.models import Camera


# Keng tarqalgan CGI formatlar. {act} = harakat yo'nalishi.
# Har element: (nom, chap_act, stop_act, URL shabloni)
CGI_FORMATS = [
    ("hi3510",
     "left", "stop",
     "/web/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act={act}&-speed=10"),
    ("hi3510_alt",
     "left", "stop",
     "/cgi-bin/hi3510/ptzctrl.cgi?-step=0&-act={act}&-speed=10"),
    ("dahua",
     "Left", "Left",
     "/cgi-bin/ptz.cgi?action={start_stop}&channel=0&code={act}&arg1=0&arg2=1&arg3=0"),
    ("axis",
     "left", "stop",
     "/axis-cgi/com/ptz.cgi?move={act}"),
    ("foscam",
     "ptzMoveLeft", "ptzStopRun",
     "/cgi-bin/CGIProxy.fcgi?cmd={act}&usr={user}&pwd={password}"),
    ("generic_decoder",
     "leftright?command=left", "leftright?command=stop",
     "/decoder_control.cgi?{act}"),
    ("cgi_ptz_move",
     "left", "stop",
     "/cgi-bin/ptz.cgi?move={act}"),
]


class Command(BaseCommand):
    help = "PTZ CGI formatini sinab topadi (ONVIF ishlamaganда)"

    def add_arguments(self, parser):
        parser.add_argument("--camera-id", type=int, default=None)
        parser.add_argument("--ip", type=str, default=None)
        parser.add_argument("--user", type=str, default="admin")
        parser.add_argument("--password", type=str, default="admin")
        parser.add_argument("--port", type=int, default=80)
        parser.add_argument("--pause", type=float, default=4.0,
                            help="Har format orasida pauza (kamerani kuzating)")

    def handle(self, *args, **options):
        ip = options["ip"]
        user = options["user"]
        password = options["password"]
        port = options["port"]

        if options["camera_id"]:
            cam = Camera.objects.filter(id=options["camera_id"]).first()
            if cam:
                ip = ip or cam.skud_device_id or cam.ip_address
                if cam.username:
                    user = cam.username
                if cam.password:
                    password = cam.password

        if not ip:
            self.stderr.write("--ip yoki --camera-id kerak")
            return

        base = f"http://{ip}:{port}"
        self.stdout.write(self.style.WARNING(
            f"\n{base} — web UI'da jonli video ochiq tursin.\n"
            f"Har format kamerani CHAPGA buradi. Qaysi biri ishlasa — o'sha to'g'ri.\n"
        ))

        auths = [
            ("basic", HTTPBasicAuth(user, password)),
            ("digest", HTTPDigestAuth(user, password)),
            ("none", None),
        ]

        for name, left_act, stop_act, tmpl in CGI_FORMATS:
            for auth_name, auth in auths:
                left_url = base + tmpl.format(
                    act=left_act, start_stop="start",
                    user=user, password=password,
                )
                try:
                    r = requests.get(left_url, auth=auth, timeout=4)
                    code = r.status_code
                    marker = "✅ 200" if code == 200 else f"  {code}"
                    self.stdout.write(
                        f"{marker} | {name:16s} | auth={auth_name:6s} | {left_url}"
                    )
                    if code == 200:
                        self.stdout.write(self.style.SUCCESS(
                            f"     ↑ KAMERA HARAKATLANDIMI? Agar HA — shu format: {name}/{auth_name}"
                        ))
                        # Stop yuborish
                        stop_url = base + tmpl.format(
                            act=stop_act, start_stop="stop",
                            user=user, password=password,
                        )
                        time.sleep(options["pause"])
                        try:
                            requests.get(stop_url, auth=auth, timeout=4)
                        except Exception:
                            pass
                        time.sleep(1.0)
                except requests.exceptions.RequestException as e:
                    self.stdout.write(f"  xato | {name:16s} | auth={auth_name:6s} | {type(e).__name__}")

        self.stdout.write(self.style.WARNING(
            "\nTugadi. Qaysi format kamerani harakatlantirgan bo'lsa — menga ayting.\n"
            "Keyin o'sha format bilan CGI patrul service yoziladi."
        ))
