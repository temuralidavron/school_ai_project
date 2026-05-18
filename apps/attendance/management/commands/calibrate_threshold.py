"""
Threshold kalibrlash — REAL RecognitionEvent ma'lumotidan optimal chegarani topadi.

Faqat O'QIYDI — hech narsani o'zgartirmaydi/buzmaydi.

Strategiya:
  1-kun: .env da past threshold + AI_REVIEW_RECORDS_ATTENDANCE=True → ma'lumot yig'iladi
  Keyin: shu komanda similarity taqsimotini ko'rsatadi → aniq threshold tanlanadi
  .env da threshold oshiriladi (kod tegmaydi) → docker compose restart cameras

Ishlatish:
    python manage.py calibrate_threshold --org-id 16
    python manage.py calibrate_threshold --org-id 16 --date 2026-05-19
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.attendance.models import RecognitionEvent


class Command(BaseCommand):
    help = "RecognitionEvent similarity taqsimotidan threshold tavsiya qiladi"

    def add_arguments(self, parser):
        parser.add_argument("--org-id", type=int, default=None)
        parser.add_argument("--date", type=str, default=None,
                            help="YYYY-MM-DD (default: bugun)")
        parser.add_argument("--days", type=int, default=1,
                            help="Necha kunlik ma'lumot (default 1)")

    def _pct(self, sorted_vals, p):
        if not sorted_vals:
            return 0.0
        idx = int(len(sorted_vals) * p / 100)
        idx = min(idx, len(sorted_vals) - 1)
        return sorted_vals[idx]

    def handle(self, *args, **options):
        from datetime import timedelta
        qs = RecognitionEvent.objects.all()
        if options["org_id"]:
            qs = qs.filter(organization_id=options["org_id"])

        tz = timezone.get_current_timezone()
        if options["date"]:
            from datetime import datetime
            d0 = datetime.strptime(options["date"], "%Y-%m-%d").date()
        else:
            d0 = timezone.now().astimezone(tz).date()
        d_start = d0 - timedelta(days=options["days"] - 1)
        qs = qs.filter(recognized_at__date__gte=d_start,
                       recognized_at__date__lte=d0)

        rows = list(qs.values_list("decision", "similarity"))
        if not rows:
            self.stderr.write("Ma'lumot yo'q. Avval tizim ishlab ma'lumot yig'sin.")
            return

        by_dec: dict[str, list] = {}
        for dec, sim in rows:
            if sim is None:
                continue
            by_dec.setdefault(dec or "?", []).append(float(sim))

        self.stdout.write(f"\n=== Threshold kalibrlash | {d_start} → {d0} | {len(rows)} event ===\n")
        dist = Counter(d for d, _ in rows)
        for dec, cnt in dist.most_common():
            self.stdout.write(f"  {dec:12s}: {cnt}")

        self.stdout.write("\n--- Similarity taqsimoti (decision bo'yicha) ---")
        self.stdout.write("  decision   |  min  |  p10  |  p25  | medMQ |  p75  |  p90  |  max")
        self.stdout.write("  -----------|-------|-------|-------|-------|-------|-------|------")
        for dec, vals in sorted(by_dec.items()):
            v = sorted(vals)
            self.stdout.write(
                f"  {dec:10s} | {v[0]:.3f} | {self._pct(v,10):.3f} | "
                f"{self._pct(v,25):.3f} | {self._pct(v,50):.3f} | "
                f"{self._pct(v,75):.3f} | {self._pct(v,90):.3f} | {v[-1]:.3f}"
            )

        acc = sorted(by_dec.get("accepted", []))
        rev = sorted(by_dec.get("review", []))
        rej = sorted(by_dec.get("rejected", []))

        self.stdout.write("\n--- TAVSIYA ---")
        if acc:
            safe_accept = round(self._pct(acc, 10), 2)
            self.stdout.write(
                f"  accepted p10 = {self._pct(acc,10):.3f} → "
                f"AI_ACCEPT_THRESHOLD ≈ {safe_accept} (haqiqiy tanishlar shu atrofda)"
            )
        if rej:
            self.stdout.write(
                f"  rejected p90 = {self._pct(rej,90):.3f} → "
                f"AI_REVIEW_THRESHOLD bundan YUQORI bo'lsin (impostor zonasi)"
            )
        if acc and rej:
            gap_lo = self._pct(rej, 90)
            gap_hi = self._pct(acc, 10)
            mid = round((gap_lo + gap_hi) / 2, 2)
            self.stdout.write(
                f"  Genuine/impostor oraliq: {gap_lo:.3f} .. {gap_hi:.3f}\n"
                f"  → Boshlang'ich xavfsiz AI_ACCEPT_THRESHOLD ≈ {mid} "
                f"(keyin ma'lumot ko'paygach aniqlashtiriladi)"
            )
        self.stdout.write(
            "\n  Eslatma: bu avtomatik emas — qaror SIZniki. Ko'proq kun "
            "ma'lumot = aniqroq. .env da o'zgartirib `docker compose restart cameras`.\n"
        )
