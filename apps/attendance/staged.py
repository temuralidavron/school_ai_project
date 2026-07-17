"""
F2b: elimination va bosqichli tasdiqlash yordamchilari.

Ikkalasi ham flag bilan (B5_ELIM / B5_STAGED, default o'chiq) va faqat
recognize_track_and_record_by_embedding ichidan chaqiriladi.

ELIMINATION mantiqi (xavfsiz variant):
  - top-1 LOCKED bola bo'lsa — TEGILMAYDI (mavjud skipped_locked yo'li ishlaydi:
    bola sinfda o'tiribdi, uning yuzi unga tegishli).
  - top-1 locked EMAS, lekin top-2..5 orasida locked'lar bo'lsa — ular ro'yxatdan
    chiqariladi va margin qayta hisoblanadi: topilganlar top-2 ni band qilib,
    noma'lum bolaning marginini bosib turgan bo'ladi.
  - Open-set poydevor saqlanadi: ball chegaralari o'zgarmaydi, faqat margin ochiladi.

BOSQICHLI TASDIQLASH:
  - review bo'lgan sighting sifatli bo'lsa (ball >= STAGED_FLOOR, margin >=
    STAGED_MARGIN) — (dars, bola) hisoblagichi +1.
  - Hisoblagich STAGED_N ga yetsa — qabul ("staged" qoidasi bilan).
  - Sifatsiz yoki boshqa-bola sighting hisoblagichni oshirmaydi (reset yo'q —
    schedule tugashi bilan qator ahamiyatsiz bo'lib qoladi).
"""
import logging
import time

from django.db.models import F

from apps.face_data.decision import (
    decide as decide_margin,
    ELIM_ENABLED, STAGED_ENABLED, STAGED_FLOOR, STAGED_MARGIN, STAGED_N,
)

logger = logging.getLogger(__name__)

# schedule_id -> (ts, set(student_id)) — lock so'rovini har sighting'da qilmaslik uchun
_locked_cache: dict = {}
_LOCKED_TTL = 5.0


def get_locked_ids(schedule) -> set:
    if schedule is None:
        return set()
    now = time.monotonic()
    hit = _locked_cache.get(schedule.id)
    if hit and now - hit[0] < _LOCKED_TTL:
        return hit[1]
    from apps.attendance.models import AttendanceLock
    ids = set(
        AttendanceLock.objects.filter(
            schedule=schedule, is_active=True
        ).values_list("student_id", flat=True)
    )
    _locked_cache[schedule.id] = (now, ids)
    return ids


def apply_elimination(result: dict, locked_ids: set,
                      accept_threshold: float, review_threshold: float) -> dict:
    """result'ni (decide_match chiqishi) locked'larni chiqarib qayta baholaydi.
    Faqat: flag yoniq, qaror accepted emas, top-1 locked emas bo'lganda chaqiriladi.
    top-5 ro'yxati ustida ishlaydi — kesh/DBga tegmaydi."""
    top = result.get("top_candidates") or []
    if not top or top[0].get("student_id") in locked_ids:
        return result
    filtered = [c for c in top if c.get("student_id") not in locked_ids]
    if not filtered or len(filtered) == len(top):
        return result   # chiqaradigan hech kim yo'q

    score = filtered[0]["best_score"]
    margin = score - filtered[1]["best_score"] if len(filtered) > 1 else score
    decision, rule = decide_margin(score, margin, accept_threshold, review_threshold)
    if decision != "accepted":
        return result   # elimination yordam bermadi — asl natija qoladi

    new = dict(result)
    new["decision"] = decision
    new["decision_rule"] = "elim_" + rule
    new["margin"] = round(margin, 6)
    new["best_match"] = {**filtered[0], "effective_score": score}
    new["top_candidates"] = filtered
    return new


def staged_bump_and_check(schedule, result: dict) -> dict:
    """Review sighting sifatli bo'lsa hisoblagich +1; N ga yetsa accepted qiladi."""
    best = result.get("best_match")
    if best is None or schedule is None:
        return result
    score = best.get("best_score", 0.0)
    margin = result.get("margin")
    if score < STAGED_FLOOR or margin is None or margin < STAGED_MARGIN:
        return result

    from apps.attendance.models import StagedCount
    obj, created = StagedCount.objects.get_or_create(
        schedule=schedule, student_id=best["student_id"],
    )
    StagedCount.objects.filter(pk=obj.pk).update(
        count=F("count") + 1,
        best_score=max(obj.best_score, score),
        best_margin=max(obj.best_margin, margin or 0.0),
    )
    obj.refresh_from_db()
    if obj.count < STAGED_N:
        return result

    logger.info("STAGED qabul: student=%s count=%d score=%.3f",
                best["student_id"], obj.count, score)
    new = dict(result)
    new["decision"] = "accepted"
    new["decision_rule"] = f"staged_{obj.count}"
    return new


def staged_clear(schedule, student_id):
    """Bola qabul qilinganda hisoblagich qatori tozalanadi."""
    if schedule is None:
        return
    from apps.attendance.models import StagedCount
    StagedCount.objects.filter(schedule=schedule, student_id=student_id).delete()
