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
