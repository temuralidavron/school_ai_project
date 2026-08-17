import io
import json
import os
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

import apps.face_data.gallery_candidates as gc
from apps.face_data import gallery_select as gs
from apps.face_data.models import StudentEmbedding
from apps.integrations.models import ExternalOrganization, ExternalStudent


class GateTests(SimpleTestCase):
    def test_margin_none_otkazilmaydi(self):
        self.assertFalse(gc.passes_gate(0.90, None, 200))

    def test_past_score(self):
        self.assertFalse(gc.passes_gate(0.59, 0.30, 200))

    def test_past_margin(self):
        self.assertFalse(gc.passes_gate(0.70, 0.19, 200))

    def test_kichik_yuz(self):
        self.assertFalse(gc.passes_gate(0.70, 0.30, 79))

    def test_hammasi_otadi(self):
        self.assertTrue(gc.passes_gate(0.60, 0.20, 80))


class BlurTests(SimpleTestCase):
    def test_otkir_va_tekis(self):
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            sharp_p = os.path.join(d, "sharp.jpg")
            flat_p = os.path.join(d, "flat.jpg")
            rng = np.random.default_rng(42)
            cv2.imwrite(sharp_p, (rng.random((200, 200)) * 255).astype("uint8"))
            cv2.imwrite(flat_p, np.full((200, 200), 128, dtype="uint8"))
            self.assertGreater(gc.blur_score(sharp_p), 60.0)
            self.assertLess(gc.blur_score(flat_p), 60.0)

    def test_fayl_yoq(self):
        self.assertIsNone(gc.blur_score("/yoq/fayl.jpg"))


class LogCandidateTests(SimpleTestCase):
    def _sharp_jpg(self, dirpath):
        import cv2
        import numpy as np
        p = os.path.join(dirpath, "crop.jpg")
        rng = np.random.default_rng(1)
        cv2.imwrite(p, (rng.random((160, 160)) * 255).astype("uint8"))
        return p

    def test_yozadi_va_format_togri(self):
        with tempfile.TemporaryDirectory() as d:
            crop = self._sharp_jpg(d)
            with patch.object(gc, "ENABLED", True), patch.object(gc, "LOG_DIR", d):
                gc.log_candidate(
                    student_id=7, camera_id=1, schedule_id=5,
                    score=0.65, margin=0.25, bbox=(10, 10, 130, 140),
                    image_path=crop, embedding=[0.1] * 512,
                )
                files = [f for f in os.listdir(d) if f.startswith("gallery-candidates-")]
                self.assertEqual(len(files), 1)
                row = json.loads(open(os.path.join(d, files[0])).read().strip())
                self.assertEqual(row["sid"], 7)
                self.assertEqual(row["face_w"], 120)
                self.assertEqual(row["face_h"], 130)
                self.assertEqual(len(row["emb"]), 512)
                self.assertGreater(row["blur"], 60.0)
                self.assertTrue(row["crop_b64"])

    def test_flag_ochiq_yozmaydi(self):
        with tempfile.TemporaryDirectory() as d:
            crop = self._sharp_jpg(d)
            with patch.object(gc, "ENABLED", False), patch.object(gc, "LOG_DIR", d):
                gc.log_candidate(
                    student_id=7, camera_id=1, schedule_id=5,
                    score=0.65, margin=0.25, bbox=(10, 10, 130, 140),
                    image_path=crop, embedding=[0.1] * 512,
                )
                self.assertEqual(
                    [f for f in os.listdir(d) if f.endswith(".jsonl")], [])

    def test_darvozadan_otmagan_yozilmaydi(self):
        with tempfile.TemporaryDirectory() as d:
            crop = self._sharp_jpg(d)
            with patch.object(gc, "ENABLED", True), patch.object(gc, "LOG_DIR", d):
                gc.log_candidate(
                    student_id=7, camera_id=1, schedule_id=5,
                    score=0.55, margin=0.25, bbox=(10, 10, 130, 140),
                    image_path=crop, embedding=[0.1] * 512,
                )
                self.assertEqual(
                    [f for f in os.listdir(d) if f.endswith(".jsonl")], [])

    def test_xato_jim_yutiladi(self):
        # image_path yo'q bo'lsa blur None -> yozilmaydi, exception chiqmaydi
        with tempfile.TemporaryDirectory() as d:
            with patch.object(gc, "ENABLED", True), patch.object(gc, "LOG_DIR", d):
                gc.log_candidate(
                    student_id=7, camera_id=1, schedule_id=5,
                    score=0.65, margin=0.25, bbox=(10, 10, 130, 140),
                    image_path="/yoq/fayl.jpg", embedding=[0.1] * 512,
                )
                self.assertEqual(
                    [f for f in os.listdir(d) if f.endswith(".jsonl")], [])


class SourceFieldTests(TestCase):
    def setUp(self):
        self.org = ExternalOrganization.objects.create(
            organization_id=999001, organization_name="Test maktab")
        self.student = ExternalStudent.objects.create(
            pinfl="TEST0001", full_name="Test Bola", organization=self.org)

    def test_camera_shablon_fotosiz_yaratiladi(self):
        e = StudentEmbedding.objects.create(
            student=self.student, enrollment_photo=None,
            embedding=[0.1] * 512, is_primary=False,
            source=StudentEmbedding.SOURCE_CAMERA,
            source_meta={"score": 0.65},
        )
        e.refresh_from_db()
        self.assertEqual(e.source, "camera")
        self.assertEqual(e.source_meta["score"], 0.65)

    def test_default_source_enrollment(self):
        e = StudentEmbedding.objects.create(
            student=self.student, enrollment_photo=None,
            embedding=[0.1] * 512)
        self.assertEqual(e.source, StudentEmbedding.SOURCE_ENROLLMENT)


class GallerySelectTests(SimpleTestCase):
    def _cand(self, sid, score, blur=100.0, emb=None):
        return {"sid": sid, "score": score, "blur": blur,
                "margin": 0.25, "emb": emb or [1.0] + [0.0] * 511}

    def test_parse_buzuq_qatorlar_tashlanadi(self):
        lines = ['{"sid": 1, "emb": [0.1]}', "buzuq{", "", '{"emb": [0.1]}']
        self.assertEqual(len(gs.parse_candidates(lines)), 1)

    def test_best_per_student_score_ustun(self):
        best = gs.best_per_student(
            [self._cand(1, 0.61, blur=500), self._cand(1, 0.70, blur=80)])
        self.assertEqual(best[1]["score"], 0.70)

    def test_best_teng_scoreda_blur_hal_qiladi(self):
        best = gs.best_per_student(
            [self._cand(1, 0.65, blur=80), self._cand(1, 0.65, blur=200)])
        self.assertEqual(best[1]["blur"], 200)

    def test_cosine(self):
        a = [1.0] + [0.0] * 511
        b = [0.0, 1.0] + [0.0] * 510
        self.assertAlmostEqual(gs.cosine(a, a), 1.0, places=6)
        self.assertAlmostEqual(gs.cosine(a, b), 0.0, places=6)

    def test_evaluate_verdictlar(self):
        ref = [1.0] + [0.0] * 511
        poison = [0.0, 1.0] + [0.0] * 510
        best = {
            1: self._cand(1, 0.65),                # primary bor, mavjud shablon yo'q -> add
            2: self._cand(2, 0.65, emb=poison),    # self-sim 0.0 -> suspicious
            3: self._cand(3, 0.65),                # primary yo'q -> no_primary
            4: self._cand(4, 0.65),                # mavjud 0.70 >= 0.65 -> keep
            5: self._cand(5, 0.70),                # mavjud 0.65 < 0.70 -> replace
        }
        primary = {1: ref, 2: ref, 4: ref, 5: ref}
        camera = {4: 0.70, 5: 0.65}
        rows = {r["sid"]: r["verdict"]
                for r in gs.evaluate(best, primary, camera, 0.35)}
        self.assertEqual(rows[1], gs.VERDICT_ADD)
        self.assertEqual(rows[2], gs.VERDICT_SUSPICIOUS)
        self.assertEqual(rows[3], gs.VERDICT_NO_PRIMARY)
        self.assertEqual(rows[4], gs.VERDICT_KEEP)
        self.assertEqual(rows[5], gs.VERDICT_REPLACE)


class GalleryEnrichCommandTests(TestCase):
    def setUp(self):
        self.org = ExternalOrganization.objects.create(
            organization_id=999002, organization_name="Test maktab 2")
        self.student = ExternalStudent.objects.create(
            pinfl="TEST0002", full_name="Enrich Bola", organization=self.org)
        self.ref = [1.0] + [0.0] * 511
        StudentEmbedding.objects.create(
            student=self.student, enrollment_photo=None,
            embedding=self.ref, is_primary=True, is_active=True)
        self.tmpdir = tempfile.mkdtemp()
        self.jsonl = os.path.join(self.tmpdir, "gallery-candidates-test.jsonl")
        good = {"ts": "t", "sid": self.student.id, "cam": 1, "sched": 5,
                "score": 0.66, "margin": 0.24, "face_w": 120, "face_h": 130,
                "blur": 150.0, "emb": self.ref, "crop_b64": ""}
        with open(self.jsonl, "w") as f:
            f.write(json.dumps(good) + "\n")

    def _run(self, **opts):
        out = io.StringIO()
        call_command("gallery_enrich", stdout=out, **opts)
        return out.getvalue()

    def test_dry_run_hisobot_db_yozmaydi(self):
        out = self._run(file=self.jsonl)
        self.assertIn("DRY-RUN", out)
        self.assertIn("Enrich Bola", out)
        self.assertIn("add", out)
        self.assertEqual(StudentEmbedding.objects.filter(
            source=StudentEmbedding.SOURCE_CAMERA).count(), 0)

    def test_apply_yozadi_va_idempotent(self):
        self._run(file=self.jsonl, apply=True)
        qs = StudentEmbedding.objects.filter(
            source=StudentEmbedding.SOURCE_CAMERA, is_active=True)
        self.assertEqual(qs.count(), 1)
        e = qs.get()
        self.assertFalse(e.is_primary)
        self.assertIsNone(e.enrollment_photo)
        self.assertEqual(e.source_meta["score"], 0.66)
        # qayta apply — dublikat yo'q (keep_existing)
        self._run(file=self.jsonl, apply=True)
        self.assertEqual(StudentEmbedding.objects.filter(
            source=StudentEmbedding.SOURCE_CAMERA, is_active=True).count(), 1)

    def test_zahar_replay_suspicious(self):
        poison = {"ts": "t", "sid": self.student.id, "cam": 1, "sched": 5,
                  "score": 0.70, "margin": 0.30, "face_w": 120, "face_h": 130,
                  "blur": 200.0, "emb": [0.0, 1.0] + [0.0] * 510, "crop_b64": ""}
        p = os.path.join(self.tmpdir, "poison.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps(poison) + "\n")
        out = self._run(file=p, apply=True)
        self.assertIn("suspicious", out)
        self.assertEqual(StudentEmbedding.objects.filter(
            source=StudentEmbedding.SOURCE_CAMERA).count(), 0)

    def test_rollback(self):
        self._run(file=self.jsonl, apply=True)
        self._run(rollback=True)
        self.assertEqual(StudentEmbedding.objects.filter(
            source=StudentEmbedding.SOURCE_CAMERA, is_active=True).count(), 0)
        self.assertEqual(StudentEmbedding.objects.filter(
            source=StudentEmbedding.SOURCE_CAMERA).count(), 1)
        self._run(rollback=True, hard=True)
        self.assertEqual(StudentEmbedding.objects.filter(
            source=StudentEmbedding.SOURCE_CAMERA).count(), 0)
