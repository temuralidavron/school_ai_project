# F3c — Galereya boyitish (dry-run) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Temir darvozadan o'tgan accepted sighting'larni embedding bilan JSONL jurnalga yozish va `gallery_enrich` buyrug'i orqali dry-run hisobot / `--apply` bilan `StudentEmbedding`ga `source="camera"` shablon qo'shish.

**Architecture:** Gibrid (spec C-variant): jonli oqim (`recognize_track_and_record_by_embedding` ichidagi hook) faqat nomzod yig'adi — `apps/face_data/gallery_candidates.py` moduli darvoza tekshiruvi + JSONL yozadi (sighting_log falsafasi: xato jim yutiladi). Qo'shish qarori oflayn: `gallery_enrich` management buyrug'i sof tanlash mantig'i (`gallery_select.py`) bilan har bola uchun eng yaxshi nomzodni tanlab, self-sim (ikkinchi himoya devori) tekshiradi.

**Tech Stack:** Django (python3.14, docker image `school_ai:latest`), PostgreSQL+pgvector, OpenCV (Laplacian), JSONL.

**Spec:** `docs/superpowers/specs/2026-07-20-f3c-galereya-dry-run-design.md`

## Global Constraints

- **Git: HECH QACHON commit/push qilinmaydi** — Aliyer o'zi qiladi. Har task oxiridagi "Commit nuqtasi" qadami = Aliyer'ga commit xabari TAKLIF qilish, kutmasdan davom etish.
- Yangi mantiq flag ostida, DEFAULT O'CHIQ: `GALLERY_CANDIDATES=1` yoqadi. Flag o'chiq bo'lsa xulq bayt-ma-bayt avvalgidek.
- Darvoza chegaralari (env, default): `GALLERY_MIN_SCORE=0.60`, `GALLERY_MIN_MARGIN=0.20`, `GALLERY_MIN_FACE=80` (bbox kichik tomoni, px), `GALLERY_MIN_BLUR=60` (Laplacian var), `GALLERY_MIN_SELF_SIM=0.35`.
- Til: o'zbek (Latin), straight apostrof `'`, kod ichida emoji yo'q, kommentariy minimal (faqat WHY), log xabarlari inglizcha.
- Kod image ichida (mount emas): **`docker cp` TAQIQLANGAN** — kod o'zgarsa `docker build -t school_ai:latest .` + container recreate. Tez test tsikli uchun quyidagi throwaway container ishlatiladi (rebuild kerak emas):

```bash
# TEST BUYRUG'I (har taskda shu ishlatiladi; talab: docker compose up -d db)
cd /home/user02/Desktop/school_full/school_ai_project
docker run --rm --network school_ai_project_default \
  --env-file .env -e DB_HOST=db -e MINIO_HOST=minio \
  -v "$(pwd)":/app school_ai:latest \
  python3.14 manage.py test apps.face_data.tests_gallery -v 2
```

- Mavjud kodga minimal tegish: `services.py`ga faqat bitta hook blok; qolgani yangi fayllar.
- pgvector extension migratsiyada bor (`face_data/0003`) — test DB avtomatik ishlaydi. DB user default `postgres` (superuser) — test DB yaratish mumkin.

---

### Task 1: `gallery_candidates.py` — darvoza + JSONL yozuvchi

**Files:**
- Create: `apps/face_data/gallery_candidates.py`
- Create: `apps/face_data/tests_gallery.py`

**Interfaces:**
- Consumes: hech narsa (yangi modul; `cv2` image ichida bor).
- Produces (Task 2 va 5 ishlatadi):
  - `ENABLED: bool`, `LOG_DIR: str`, `MIN_SCORE/MIN_MARGIN/MIN_FACE/MIN_BLUR` konstantalar, `_f(name, default) -> float`
  - `passes_gate(score: float, margin: float | None, face_px: int) -> bool`
  - `blur_score(image_path: str) -> float | None`
  - `log_candidate(*, student_id, camera_id, schedule_id, score, margin, bbox, image_path, embedding) -> None`
  - JSONL qator formati: `{ts, sid, cam, sched, score, margin, face_w, face_h, blur, emb: [512 float], crop_b64}`
  - Fayl: `{LOG_DIR}/gallery-candidates-YYYY-MM-DD.jsonl`

- [ ] **Step 1: Failing testlarni yozish**

`apps/face_data/tests_gallery.py` (yangi fayl — mavjud `tests.py` stub'iga tegilmaydi):

```python
import json
import os
import tempfile
from unittest.mock import patch

from django.test import SimpleTestCase

import apps.face_data.gallery_candidates as gc


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
```

- [ ] **Step 2: Testlar FAIL bo'lishini tekshirish**

Global Constraints'dagi TEST BUYRUG'I bilan ishga tushirish.
Expected: `ModuleNotFoundError: No module named 'apps.face_data.gallery_candidates'`

- [ ] **Step 3: Modulni yozish**

`apps/face_data/gallery_candidates.py`:

```python
"""
F3c: galereya-nomzod jurnali — temir darvozadan o'tgan accepted sighting'lar
embedding bilan JSONL'ga yoziladi. DB'ga tegilmaydi; qo'shish qarori oflayn
(gallery_enrich buyrug'i). Zahar-sinov isboti (2026-07-16): himoyasiz galereya
boyitish MUMKIN EMAS — shu uchun darvoza qattiq va flag default o'chiq.

Yoqish: GALLERY_CANDIDATES=1. Fayl: logs/gallery-candidates-YYYY-MM-DD.jsonl.
Xato jim yutiladi — hot-path (davomat oqimi) hech qachon buzilmaydi.
"""
import base64
import datetime
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


ENABLED = os.getenv("GALLERY_CANDIDATES", "0") == "1"
MIN_SCORE = _f("GALLERY_MIN_SCORE", 0.60)
MIN_MARGIN = _f("GALLERY_MIN_MARGIN", 0.20)
MIN_FACE = int(_f("GALLERY_MIN_FACE", 80))
MIN_BLUR = _f("GALLERY_MIN_BLUR", 60.0)
LOG_DIR = os.getenv("GALLERY_LOG_DIR", os.getenv("SIGHTING_LOG_DIR", "/app/logs"))

_lock = threading.Lock()
_warned = False


def passes_gate(score: float, margin: float | None, face_px: int) -> bool:
    # margin None = bitta nomzod — isbotsiz, o'tkazmaymiz
    if margin is None:
        return False
    return score >= MIN_SCORE and margin >= MIN_MARGIN and face_px >= MIN_FACE


def blur_score(image_path: str) -> float | None:
    try:
        import cv2
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return float(cv2.Laplacian(img, cv2.CV_64F).var())
    except Exception:
        return None


def log_candidate(*, student_id, camera_id, schedule_id, score, margin,
                  bbox, image_path, embedding) -> None:
    global _warned
    if not ENABLED or student_id is None or bbox is None:
        return
    try:
        face_w = int(bbox[2]) - int(bbox[0])
        face_h = int(bbox[3]) - int(bbox[1])
        if not passes_gate(float(score), margin, min(face_w, face_h)):
            return
        # blur qimmat — faqat qolgan shartlar o'tgach hisoblanadi
        blur = blur_score(image_path)
        if blur is None or blur < MIN_BLUR:
            return
        crop_b64 = ""
        try:
            with open(image_path, "rb") as fh:
                crop_b64 = base64.b64encode(fh.read()).decode("ascii")
        except OSError:
            pass
        row = {
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "sid": int(student_id),
            "cam": camera_id,
            "sched": schedule_id,
            "score": round(float(score), 4),
            "margin": round(float(margin), 4),
            "face_w": face_w,
            "face_h": face_h,
            "blur": round(blur, 1),
            "emb": [round(float(v), 6) for v in embedding],
            "crop_b64": crop_b64,
        }
        day = datetime.date.today().isoformat()
        path = os.path.join(LOG_DIR, f"gallery-candidates-{day}.jsonl")
        line = json.dumps(row, ensure_ascii=False)
        with _lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception as exc:
        if not _warned:
            _warned = True
            logger.warning("gallery candidate log failed (%s) - continuing", exc)
```

- [ ] **Step 4: Testlar PASS bo'lishini tekshirish**

TEST BUYRUG'I. Expected: `OK`, 11 test.

- [ ] **Step 5: Commit nuqtasi**

Aliyer'ga taklif: `F3c-1: gallery_candidates — temir darvoza + JSONL yozuvchi (flag-off)`

---

### Task 2: `services.py` hook — accepted sighting'da nomzod yozish

**Files:**
- Modify: `apps/attendance/services.py` (log_sighting chaqiruvidan keyin, ~588-qator)

**Interfaces:**
- Consumes: `gallery_candidates.log_candidate(...)` (Task 1); joriy scope o'zgaruvchilari: `decision`, `best`, `result`, `camera_id`, `_active_schedule`, `bbox`, `image_path`, `query_embedding`.
- Produces: flag yoniq bo'lsa JSONL qatorlar; flag o'chiq bo'lsa xulq o'zgarmasligi.

- [ ] **Step 1: Hook qo'shish**

`apps/attendance/services.py`da shu blokdan KEYIN (F2 log_sighting chaqiruvi):

```python
        # F2: har sighting jurnalga — YAKUNIY qaror bilan (elim/staged'dan keyin)
        from apps.attendance.sighting_log import log_sighting
        log_sighting(
            track_key=track_key, camera_id=camera_id,
            schedule_id=_active_schedule.id if _active_schedule else None,
            result=result,
        )
```

quyidagi yangi blok qo'shiladi:

```python
        # F3c: galereya-nomzod jurnali (GALLERY_CANDIDATES=1 bo'lmasa no-op)
        if decision == RecognitionEvent.DECISION_ACCEPTED and best is not None:
            from apps.face_data.gallery_candidates import log_candidate
            log_candidate(
                student_id=best.get("student_id"),
                camera_id=camera_id,
                schedule_id=_active_schedule.id if _active_schedule else None,
                score=best.get("best_score", 0.0),
                margin=result.get("margin"),
                bbox=bbox,
                image_path=image_path,
                embedding=query_embedding,
            )
```

Eslatma: `RecognitionEvent.DECISION_ACCEPTED = "accepted"` (`apps/attendance/models.py:5`) — tasdiqlangan; `services.py` fayl boshidagi importlar allaqachon `RecognitionEvent`ni oladi.

- [ ] **Step 2: Django check**

```bash
docker run --rm --network school_ai_project_default \
  --env-file .env -e DB_HOST=db -e MINIO_HOST=minio \
  -v "$(pwd)":/app school_ai:latest python3.14 manage.py check
```
Expected: `System check identified no issues`

- [ ] **Step 3: Flag-o'chiq regressiya (repo qoidasi: har kod o'zgarishidan keyin smoke)**

```bash
docker build -t school_ai:latest . && docker compose up -d web kafka_consumer
bash deepstream_v3/tests/smoke.sh
```
Expected: `PASS` (T1). `.env`da `GALLERY_CANDIDATES` YO'Q — flag o'chiq, `logs/gallery-candidates-*.jsonl` paydo BO'LMASLIGI kerak: `ls logs/gallery-candidates-* 2>/dev/null` bo'sh.

- [ ] **Step 4: Commit nuqtasi**

Aliyer'ga taklif: `F3c-2: accepted sighting -> gallery candidate hook (flag-off, T1 PASS)`

---

### Task 3: `StudentEmbedding` migratsiyasi — source/source_meta

**Files:**
- Modify: `apps/face_data/models.py:54-93` (StudentEmbedding)
- Create: `apps/face_data/migrations/0007_gallery_source.py` (makemigrations orqali)
- Test: `apps/face_data/tests_gallery.py` (qo'shimcha klass)

**Interfaces:**
- Produces (Task 5 ishlatadi): `StudentEmbedding.SOURCE_ENROLLMENT = "enrollment"`, `SOURCE_CAMERA = "camera"`, maydonlar `source` (default enrollment), `source_meta` (JSON, null), `enrollment_photo` endi `null=True`.

- [ ] **Step 1: Failing test yozish**

`apps/face_data/tests_gallery.py`ga qo'shish:

```python
from django.test import TestCase

from apps.face_data.models import StudentEmbedding
from apps.integrations.models import ExternalOrganization, ExternalStudent


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
```

- [ ] **Step 2: FAIL tekshirish**

TEST BUYRUG'I. Expected: `AttributeError: ... SOURCE_CAMERA` (yoki `TypeError` — maydonlar yo'q).

- [ ] **Step 3: Modelni o'zgartirish**

`apps/face_data/models.py` StudentEmbedding ichida:

```python
    SOURCE_ENROLLMENT = "enrollment"
    SOURCE_CAMERA = "camera"

    SOURCE_CHOICES = (
        (SOURCE_ENROLLMENT, "Enrollment"),
        (SOURCE_CAMERA, "Camera"),
    )
```

`enrollment_photo` maydoniga `null=True, blank=True` qo'shish (SKUD fotosiz kamera-shablon uchun); `is_active` maydonidan keyin:

```python
    source = models.CharField(
        max_length=16, choices=SOURCE_CHOICES, default=SOURCE_ENROLLMENT)
    source_meta = models.JSONField(null=True, blank=True)
```

- [ ] **Step 4: Migratsiya yaratish va qo'llash**

```bash
docker run --rm --network school_ai_project_default \
  --env-file .env -e DB_HOST=db -e MINIO_HOST=minio \
  -v "$(pwd)":/app school_ai:latest \
  python3.14 manage.py makemigrations face_data -n gallery_source
docker run --rm --network school_ai_project_default \
  --env-file .env -e DB_HOST=db -e MINIO_HOST=minio \
  -v "$(pwd)":/app school_ai:latest python3.14 manage.py migrate face_data
```
Expected: `0007_gallery_source` yaratiladi va qo'llanadi.

- [ ] **Step 5: PASS tekshirish**

TEST BUYRUG'I. Expected: `OK` (barcha testlar).

- [ ] **Step 6: Commit nuqtasi**

Aliyer'ga taklif: `F3c-3: StudentEmbedding.source/source_meta + enrollment_photo null (0007)`

---

### Task 4: `gallery_select.py` — sof tanlash mantig'i + self-sim devori

**Files:**
- Create: `apps/face_data/gallery_select.py`
- Test: `apps/face_data/tests_gallery.py` (qo'shimcha klass)

**Interfaces:**
- Produces (Task 5 ishlatadi):
  - `parse_candidates(lines: Iterable[str]) -> list[dict]` — buzuq/bo'sh qatorlarni tashlab JSON parse
  - `best_per_student(cands: list[dict]) -> dict[int, dict]` — kalit `(score, blur)` bo'yicha eng yaxshi
  - `cosine(a, b) -> float`
  - `evaluate(best_by_student, primary_by_student, camera_score_by_student, min_self_sim) -> list[dict]` — har element `{"sid", "cand", "self_sim", "verdict"}`
  - Verdictlar: `VERDICT_ADD="add"`, `VERDICT_REPLACE="replace"`, `VERDICT_KEEP="keep_existing"`, `VERDICT_SUSPICIOUS="suspicious"`, `VERDICT_NO_PRIMARY="no_primary"`

- [ ] **Step 1: Failing testlar**

`apps/face_data/tests_gallery.py`ga qo'shish:

```python
from apps.face_data import gallery_select as gs


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
```

- [ ] **Step 2: FAIL tekshirish**

TEST BUYRUG'I. Expected: `ModuleNotFoundError: ... gallery_select`

- [ ] **Step 3: Modulni yozish**

`apps/face_data/gallery_select.py`:

```python
"""
F3c: nomzod-jurnaldan tanlash — sof funksiyalar (DB/IO yo'q).
Ikkinchi himoya devori shu yerda: self-sim (nomzod vs primary etalon) —
zahar-sinovdagi "1 noto'g'ri shablon = 3 xato qabul" stsenariysiga qarshi.
"""
import json
import math

VERDICT_ADD = "add"
VERDICT_REPLACE = "replace"
VERDICT_KEEP = "keep_existing"
VERDICT_SUSPICIOUS = "suspicious"
VERDICT_NO_PRIMARY = "no_primary"


def parse_candidates(lines):
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if row.get("sid") is None or not row.get("emb"):
            continue
        out.append(row)
    return out


def best_per_student(cands):
    best = {}
    for c in cands:
        sid = int(c["sid"])
        cur = best.get(sid)
        key = (c.get("score", 0.0), c.get("blur", 0.0))
        if cur is None or key > (cur.get("score", 0.0), cur.get("blur", 0.0)):
            best[sid] = c
    return best


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def evaluate(best_by_student, primary_by_student, camera_score_by_student,
             min_self_sim):
    out = []
    for sid, cand in sorted(best_by_student.items()):
        primary = primary_by_student.get(sid)
        if primary is None:
            self_sim, verdict = None, VERDICT_NO_PRIMARY
        else:
            self_sim = cosine(cand["emb"], primary)
            if self_sim < min_self_sim:
                verdict = VERDICT_SUSPICIOUS
            else:
                old = camera_score_by_student.get(sid)
                if old is not None and old >= cand.get("score", 0.0):
                    verdict = VERDICT_KEEP
                elif old is not None:
                    verdict = VERDICT_REPLACE
                else:
                    verdict = VERDICT_ADD
        out.append({"sid": sid, "cand": cand,
                    "self_sim": self_sim, "verdict": verdict})
    return out
```

- [ ] **Step 4: PASS tekshirish**

TEST BUYRUG'I. Expected: `OK`.

- [ ] **Step 5: Commit nuqtasi**

Aliyer'ga taklif: `F3c-4: gallery_select — sof tanlash + self-sim devori`

---

### Task 5: `gallery_enrich` buyrug'i — dry-run / --apply / --rollback

**Files:**
- Create: `apps/face_data/management/commands/gallery_enrich.py`
- Test: `apps/face_data/tests_gallery.py` (qo'shimcha klass)

**Interfaces:**
- Consumes: Task 1 (`LOG_DIR`, `_f`), Task 3 (`SOURCE_CAMERA`, `source_meta`), Task 4 (`parse_candidates`, `best_per_student`, `evaluate`, verdictlar).
- Produces: CLI — `gallery_enrich [--date YYYY-MM-DD] [--file PATH] [--apply] [--rollback [--hard]]`. Apply'da yozuv: `model_version="camera-f3c"`, `is_primary=False`, `source="camera"`, `source_meta={score, margin, blur, camera_id, schedule_id, date, file}`.

- [ ] **Step 1: Failing testlar**

`apps/face_data/tests_gallery.py`ga qo'shish:

```python
import io

from django.core.management import call_command


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
```

- [ ] **Step 2: FAIL tekshirish**

TEST BUYRUG'I. Expected: `CommandError: Unknown command: 'gallery_enrich'`

- [ ] **Step 3: Buyruqni yozish**

`apps/face_data/management/commands/gallery_enrich.py`:

```python
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
```

Eslatma: `management/` va `management/commands/` papkalarida `__init__.py` bor-yo'qligini tekshirish (`ls apps/face_data/management/commands/`) — mavjud (test_thread_safety.py shu yerda turibdi).

- [ ] **Step 4: PASS tekshirish**

TEST BUYRUG'I. Expected: `OK` (barcha testlar, jami ~20).

- [ ] **Step 5: Commit nuqtasi**

Aliyer'ga taklif: `F3c-5: gallery_enrich — dry-run/apply/rollback + zahar-replay testlari`

---

### Task 6: Integratsiya replay + hujjat yangilash

**Files:**
- Modify: `.env` (vaqtincha flag, oxirida olib tashlanadi)
- Modify: `JAMI_2.md` (flag ro'yxati + "Keyingi ishlar")

**Interfaces:**
- Consumes: Task 1-5 barchasi, `deepstream_v3/run_demo.sh`, `deepstream_v3/tests/smoke.sh`.

- [ ] **Step 1: Image rebuild + flag yoniq replay**

```bash
docker build -t school_ai:latest .
echo "GALLERY_CANDIDATES=1" >> .env
docker compose up -d --force-recreate web kafka_consumer
bash deepstream_v3/run_demo.sh
sleep 120
```

- [ ] **Step 2: Jurnal paydo bo'lgani va darvozaga mosligini tekshirish**

```bash
J="logs/gallery-candidates-$(date +%F).jsonl"
wc -l "$J"
# har qator darvozaga mos bo'lishi shart — buzilish soni 0:
jq -c 'select(.score < 0.60 or .margin < 0.20 or ([.face_w,.face_h]|min) < 80 or .blur < 60)' "$J" | wc -l
jq -c 'select((.emb|length) != 512)' "$J" | wc -l
```
Expected: qatorlar > 0 (sinf.mp4'da 0.60+ ballar bor — evrika'da max 0.723 ko'rilgan); ikkala tekshiruv `0`.
Agar 0 qator bo'lsa: bu FAIL emas — chegara juda qattiq degani; `docker logs school_ai_kafka_consumer | grep -i gallery` tekshirilib, natija hisobotga yoziladi (chegara kalibrlash avgust dry-run vazifasi).

- [ ] **Step 3: Dry-run hisobot jonli jurnal ustida**

```bash
docker exec school_ai_web python3.14 manage.py gallery_enrich
```
Expected: hisobot chiqadi (nomzodlar bo'lsa — verdictlar; DRY-RUN yozuvi bilan), DB'ga yozilmaydi:
```bash
docker exec school_ai_web python3.14 manage.py shell -c "
from apps.face_data.models import StudentEmbedding
print(StudentEmbedding.objects.filter(source='camera').count())"
```
Expected: `0`

- [ ] **Step 4: Flag o'chirish + yakuniy regressiya**

```bash
sed -i '/^GALLERY_CANDIDATES=/d' .env
docker compose up -d --force-recreate web kafka_consumer
bash deepstream_v3/tests/smoke.sh
```
Expected: `PASS` (T1), yangi `gallery-candidates` qatorlar QO'SHILMAYDI (flag o'chiq).

- [ ] **Step 5: JAMI_2.md yangilash**

"Ishlaydigan flaglar" ro'yxatiga qo'shish:
```
- `GALLERY_CANDIDATES=1` — F3c galereya-nomzod jurnali (temir darvoza: 0.60/0.20/80px/blur60); qo'shish faqat `gallery_enrich --apply` bilan, rollback `--rollback`
```
"Keyingi ishlar" qatoridan F3 olib tashlanadi (BEKOR — admin panel yetarli deb qaror qilindi, 2026-07-20), F3c holati "kod tayyor, avgust dry-run" ga o'zgartiriladi.

- [ ] **Step 6: Commit nuqtasi**

Aliyer'ga taklif: `F3c-6: integratsiya replay tekshirildi + JAMI_2 yangilandi`

---

## Yakuniy holat (definition of done)

- Flag o'chiq: xulq o'zgarmagan (T1 smoke PASS, jurnal yozilmaydi).
- Flag yoniq: accepted+darvoza sighting'lar JSONL'ga tushadi.
- `gallery_enrich`: dry-run hisobot, `--apply` idempotent, zahar-nomzod `suspicious` bilan rad, `--rollback` bir buyruq.
- Avgust rejasi (bu plandan TASHQARIDA): flag yoniq dry-run yig'ish, chegaralarni (ayniqsa `GALLERY_MIN_BLUR`, `GALLERY_MIN_SELF_SIM`) hisobotlar bilan kalibrlash; sentabr: jonli dry-run 1-2 hafta → `--apply`.
