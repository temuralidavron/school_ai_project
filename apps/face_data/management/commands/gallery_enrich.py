"""
F3c: galereya boyitish buyrug'i (spec: 2026-07-20-f3c-galereya-dry-run-design.md).

  gallery_enrich                     # dry-run: bugungi jurnal hisoboti
  gallery_enrich --date 2026-07-21   # boshqa kun jurnali
  gallery_enrich --file PATH         # aniq fayl (test/tahlil)
  gallery_enrich --apply             # add/replace verdictlarni DB'ga yozish
  gallery_enrich --rollback          # barcha kamera-shablon is_active=False
  gallery_enrich --rollback --hard   # butunlay o'chirish
"""
import datetime
import os

from django.core.management.base import BaseCommand, CommandError

from apps.face_data.gallery_candidates import LOG_DIR, _f
from apps.face_data.gallery_select import (
    VERDICT_ADD, VERDICT_REPLACE,
    best_per_student, evaluate, parse_candidates,
)
from apps.face_data.models import StudentEmbedding
from apps.integrations.models import ExternalStudent

MIN_SELF_SIM = _f("GALLERY_MIN_SELF_SIM", 0.35)


class Command(BaseCommand):
    help = "F3c: gallery-candidates jurnalidan galereya boyitish (dry-run default)"

    def add_arguments(self, parser):
        parser.add_argument("--date", default=None)
        parser.add_argument("--file", default=None)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--rollback", action="store_true")
        parser.add_argument("--hard", action="store_true")

    def handle(self, *args, **opts):
        if opts["rollback"]:
            self._rollback(hard=opts["hard"])
            return

        day = opts["date"] or datetime.date.today().isoformat()
        path = opts["file"] or os.path.join(
            LOG_DIR, f"gallery-candidates-{day}.jsonl")
        if not os.path.exists(path):
            raise CommandError(f"jurnal topilmadi: {path}")

        with open(path, encoding="utf-8") as fh:
            cands = parse_candidates(fh)
        best = best_per_student(cands)
        sids = list(best.keys())

        primary = {
            e.student_id: [float(v) for v in e.embedding]
            for e in StudentEmbedding.objects.filter(
                student_id__in=sids, is_primary=True, is_active=True)
        }
        camera_score = {
            e.student_id: float((e.source_meta or {}).get("score", 0.0))
            for e in StudentEmbedding.objects.filter(
                student_id__in=sids,
                source=StudentEmbedding.SOURCE_CAMERA, is_active=True)
        }
        names = dict(ExternalStudent.objects.filter(
            id__in=sids).values_list("id", "full_name"))

        rows = evaluate(best, primary, camera_score, MIN_SELF_SIM)

        self.stdout.write(
            f"Jurnal: {path} — {len(cands)} nomzod, {len(best)} bola")
        counts: dict = {}
        for r in rows:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
            c = r["cand"]
            ss = f"{r['self_sim']:.3f}" if r["self_sim"] is not None else "-"
            nm = names.get(r["sid"], f"id={r['sid']}")
            self.stdout.write(
                f"  {nm}: score={c['score']:.3f} margin={c['margin']:.3f} "
                f"blur={c.get('blur', 0):.0f} self_sim={ss} -> {r['verdict']}")
        self.stdout.write("Xulosa: " + ", ".join(
            f"{k}={v}" for k, v in sorted(counts.items())))

        if not opts["apply"]:
            self.stdout.write("DRY-RUN — DB'ga yozilmadi (--apply bilan yoziladi)")
            return

        applied = 0
        for r in rows:
            if r["verdict"] not in (VERDICT_ADD, VERDICT_REPLACE):
                continue
            c = r["cand"]
            StudentEmbedding.objects.filter(
                student_id=r["sid"],
                source=StudentEmbedding.SOURCE_CAMERA,
                is_active=True).update(is_active=False)
            StudentEmbedding.objects.create(
                student_id=r["sid"],
                enrollment_photo=None,
                model_name=StudentEmbedding.MODEL_ARCFACE,
                model_version="camera-f3c",
                embedding=c["emb"],
                embedding_dim=len(c["emb"]),
                is_primary=False,
                quality_score=c["score"],
                is_active=True,
                source=StudentEmbedding.SOURCE_CAMERA,
                source_meta={
                    "score": c["score"], "margin": c["margin"],
                    "blur": c.get("blur"), "camera_id": c.get("cam"),
                    "schedule_id": c.get("sched"), "date": day,
                    "file": os.path.basename(path),
                },
            )
            applied += 1
        self.stdout.write(f"APPLY: {applied} ta kamera-shablon yozildi")

    def _rollback(self, *, hard: bool):
        qs = StudentEmbedding.objects.filter(
            source=StudentEmbedding.SOURCE_CAMERA)
        n = qs.count()
        if hard:
            qs.delete()
            self.stdout.write(f"ROLLBACK HARD: {n} ta kamera-shablon o'chirildi")
        else:
            qs.update(is_active=False)
            self.stdout.write(
                f"ROLLBACK: {n} ta kamera-shablon is_active=False qilindi")
