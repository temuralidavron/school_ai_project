"""
Camera jadvalidan DeepStream sources.json yaratadi (F1 jonli manba).

Yagona haqiqat manbasi — Django Camera.stream_url; pipeline shu fayldan o'qiydi.

Ikki rejim:
  hls  (default) — Camera.stream_url o'zi (edu-api proxy). Internet orqali,
                   tarmoq uzilsa oqim yo'qoladi, kechikish 6-20s.
  rtsp           — kamera IP ga TO'G'RIDAN. Kechikish <1s, internetga bog'liq
                   emas, lekin server kamera tarmog'ida bo'lishi SHART.

Ishlatish:
  python manage.py export_ds_sources --out deepstream_v3/configs/sources.json
  python manage.py export_ds_sources --org-id 16 --camera-id 5
  python manage.py export_ds_sources --mode rtsp --org-id 16 \
         --rtsp-user admin --rtsp-pass admin --ip-map deploy/camera_ips.csv

ip-map CSV formati (nuqtali vergul, izohlar '#' bilan):
  camera_id;IP            yoki      kamera_nomi;IP
  5;10.144.4.4
  9-xona;10.144.4.7
"""
import json
import os

from django.core.management.base import BaseCommand

from apps.cameras.models import Camera


def _normalize(url: str) -> str:
    # pipeline'dagi _normalize_uri bilan bir xil qoida
    if url.startswith(("rtsp://", "rtsps://", "file://")):
        return url
    if url.startswith(("http://", "https://")):
        base = url.split("?", 1)[0]
        if not base.endswith(".m3u8"):
            return url.rstrip("/") + "/index.m3u8"
    return url


def _load_ip_map(path):
    """CSV -> {kalit: ip}. Kalit camera_id yoki kamera nomi bo'lishi mumkin."""
    out = {}
    if not path or not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.replace(",", ";").split(";")]
            if len(parts) >= 2 and parts[-1]:
                out[parts[0].lower()] = parts[-1]
    return out


class Command(BaseCommand):
    help = "Camera.stream_url -> DeepStream sources.json ({camera_id: uri})"

    def add_arguments(self, parser):
        parser.add_argument("--out", default="deepstream_v3/configs/sources.json")
        parser.add_argument("--org-id", type=int, default=None,
                            help="Faqat shu tashkilot kameralari")
        parser.add_argument("--camera-id", type=int, action="append", default=None,
                            help="Faqat shu kamera(lar) — sinov uchun")
        parser.add_argument("--mode", choices=["hls", "rtsp"], default="hls",
                            help="hls: stream_url (proxy) | rtsp: IP ga to'g'ridan")
        parser.add_argument("--rtsp-user", default="admin")
        parser.add_argument("--rtsp-pass", default="admin")
        parser.add_argument("--rtsp-port", type=int, default=554)
        parser.add_argument("--rtsp-path", default="/stream1",
                            help="Kamera brendiga qarab: /stream1, /cam/realmonitor?channel=1&subtype=0, "
                                 "/Streaming/Channels/101")
        parser.add_argument("--ip-map", default=None,
                            help="CSV: camera_id;IP — Camera.ip_address bo'sh bo'lganda")

    def handle(self, *args, **opts):
        qs = Camera.objects.filter(is_active_stream=True).exclude(
            stream_url__isnull=True).exclude(stream_url="")
        if opts["org_id"] is not None:
            qs = qs.filter(organization_id=opts["org_id"])
        if opts["camera_id"]:
            qs = Camera.objects.filter(id__in=opts["camera_id"])

        cams = list(qs.order_by("id"))
        if not cams:
            self.stderr.write("Mos kamera topilmadi (is_active_stream/stream_url tekshiring)")
            return

        if opts["mode"] == "rtsp":
            data, yoq = self._rtsp_map(cams, opts)
            if yoq:
                self.stderr.write(self.style.WARNING(
                    f"  IP topilmadi ({len(yoq)} kamera), o'tkazib yuborildi: "
                    + ", ".join(yoq)))
                self.stderr.write(
                    "  Yechim: Camera.ip_address to'ldiring yoki --ip-map CSV bering")
        else:
            data = {str(c.id): _normalize(c.stream_url) for c in cams}

        if not data:
            self.stderr.write(self.style.ERROR("Bironta ham manba yig'ilmadi"))
            return

        with open(opts["out"], "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.stdout.write(self.style.SUCCESS(
            f"{len(data)} manba ({opts['mode']}) -> {opts['out']}"))
        for cid, uri in data.items():
            # parolni logda ko'rsatmaymiz
            self.stdout.write(f"  {cid}: {self._mask(uri)}")

    def _rtsp_map(self, cams, opts):
        """
        Camera jadvalidagi maydonlar USTUVOR (SKUD dan kelgan haqiqiy qiymatlar),
        CLI argumentlari faqat bo'sh maydon uchun zaxira.
        """
        ip_map = _load_ip_map(opts["ip_map"])
        data, yoq = {}, []
        for c in cams:
            ip = (c.ip_address or "").strip()
            if not ip:
                ip = (ip_map.get(str(c.id))
                      or ip_map.get((c.name or "").strip().lower())
                      or "")
            if not ip:
                yoq.append(f"{c.id}({c.name or '-'})")
                continue

            user = (c.username or "").strip() or opts["rtsp_user"]
            pwd = (c.password or "").strip() or opts["rtsp_pass"]
            port = c.port or opts["rtsp_port"]
            path = (c.path or "").strip() or opts["rtsp_path"]
            if not path.startswith("/"):
                path = "/" + path
            # {channel} shabloni bo'lsa to'ldiramiz (dahua/hikvision yo'llarida uchraydi)
            if "{channel}" in path:
                path = path.replace("{channel}", str(c.channel or 1))

            data[str(c.id)] = f"rtsp://{user}:{pwd}@{ip}:{port}{path}"
        return data, yoq

    @staticmethod
    def _mask(uri):
        if "://" in uri and "@" in uri:
            sxema, qolgan = uri.split("://", 1)
            kirish, host = qolgan.split("@", 1)
            foydalanuvchi = kirish.split(":", 1)[0]
            return f"{sxema}://{foydalanuvchi}:***@{host}"
        return uri
