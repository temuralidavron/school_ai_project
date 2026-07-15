"""
Sighting-jurnal (F2): har qaror nuqtasi bir qator JSONL sifatida yoziladi.

Nega kerak: RecognitionEvent'da review yozuvlar ustma-ust yangilanadi —
ko'rinishlar KETMA-KETLIGI yo'qoladi. B5 "bosqichli tasdiqlash" (N marta izchil
top-1) va elimination'ni haqiqiy ketma-ketliklarda sinash uchun shu jurnal
yagona manba. Kuzgacha yig'ilgan fayllar = validatsiya dataseti.

Format: logs/sightings-YYYY-MM-DD.jsonl (kunlik fayl, append-only).
O'chirish: SIGHTING_LOG=0. DB'ga tegmaydi, xato bo'lsa jim o'tadi (hot-path).
"""
import datetime
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

ENABLED = os.getenv("SIGHTING_LOG", "1") == "1"
LOG_DIR = os.getenv("SIGHTING_LOG_DIR", "/app/logs")

_lock = threading.Lock()
_warned = False


def log_sighting(*, track_key: str, camera_id, schedule_id, result: dict,
                 extra: dict | None = None):
    """result — decide_match/decide_match_by_embedding qaytargan dict."""
    global _warned
    if not ENABLED:
        return
    try:
        top = [
            {"sid": c.get("student_id"), "s": round(c.get("best_score", 0), 4)}
            for c in (result.get("top_candidates") or [])[:5]
        ]
        row = {
            "ts": datetime.datetime.now().isoformat(timespec="milliseconds"),
            "cam": camera_id,
            "sched": schedule_id,
            "track": track_key,
            "decision": result.get("decision"),
            "rule": result.get("decision_rule"),
            "margin": result.get("margin"),
            "top": top,
        }
        if extra:
            row.update(extra)
        day = datetime.date.today().isoformat()
        path = os.path.join(LOG_DIR, f"sightings-{day}.jsonl")
        line = json.dumps(row, ensure_ascii=False, default=str)
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError as exc:
        if not _warned:
            _warned = True
            logger.warning("sighting log yozilmadi (%s) — jurnal o'chiq davom etadi", exc)
