"""
Camera jadvalidan DeepStream sources.json yaratadi (F1 jonli manba).

Yagona haqiqat manbasi — Django Camera.stream_url; pipeline shu fayldan o'qiydi.
Ishlatish:
  python manage.py export_ds_sources --out deepstream_v3/configs/sources.json
  python manage.py export_ds_sources --org-id 16 --camera-id 5
"""
import json

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


class Command(BaseCommand):
    help = "Camera.stream_url -> DeepStream sources.json ({camera_id: uri})"

    def add_arguments(self, parser):
        parser.add_argument("--out", default="deepstream_v3/configs/sources.json")
        parser.add_argument("--org-id", type=int, default=None,
                            help="Faqat shu tashkilot kameralari")
        parser.add_argument("--camera-id", type=int, action="append", default=None,
                            help="Faqat shu kamera(lar) — sinov uchun")

    def handle(self, *args, **opts):
        qs = Camera.objects.filter(is_active_stream=True).exclude(
            stream_url__isnull=True).exclude(stream_url="")
        if opts["org_id"] is not None:
            qs = qs.filter(organization_id=opts["org_id"])
        if opts["camera_id"]:
            qs = Camera.objects.filter(id__in=opts["camera_id"])

        data = {str(c.id): _normalize(c.stream_url) for c in qs.order_by("id")}
        if not data:
            self.stderr.write("Mos kamera topilmadi (is_active_stream/stream_url tekshiring)")
            return

        with open(opts["out"], "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.stdout.write(self.style.SUCCESS(f"{len(data)} manba -> {opts['out']}"))
        for cid, uri in data.items():
            self.stdout.write(f"  {cid}: {uri}")
