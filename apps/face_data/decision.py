"""
B5 margin qarori — top-1 va top-2 nomzod farqiga asoslangan qabul yo'llari.

B5_MARGIN=1 bo'lsa qattiq accept_threshold'dan tashqari ikkita margin yo'li
ochiladi. Asos: 320 haqiqiy event simulyatsiyasi (2026-07) — avtomatik qabul
45%->95%, sezgirlik panjarasida barqaror plato, "soxta bola" stress-testida
0/320 aldanish. Flag o'chiq bo'lsa xulq avvalgidek (evrika bilan mos).
"""
import os


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


B5_ENABLED = os.getenv("B5_MARGIN", "0") == "1"
FLOOR1 = _f("B5_FLOOR1", 0.48)
MARGIN1 = _f("B5_MARGIN1", 0.15)
FLOOR2 = _f("B5_FLOOR2", 0.45)
MARGIN2 = _f("B5_MARGIN2", 0.22)

# F2b: elimination — dars ichida qabul qilinganlar nomzodlardan chiqariladi
# (top-2 ni bo'shatib, margin'ni ochadi). Faqat top-1 LOCKED bo'lmaganda.
ELIM_ENABLED = os.getenv("B5_ELIM", "0") == "1"
# F2b: bosqichli tasdiqlash — past ball, lekin N marta izchil bir xil bola
STAGED_ENABLED = os.getenv("B5_STAGED", "0") == "1"
STAGED_FLOOR = _f("B5_STAGED_FLOOR", 0.48)
STAGED_MARGIN = _f("B5_STAGED_MARGIN", 0.08)
STAGED_N = int(_f("B5_STAGED_N", 5))


def decide(score: float, margin: float | None,
           accept_threshold: float, review_threshold: float) -> tuple[str, str]:
    """
    Qaytaradi: (decision, rule).
    rule — qaysi yo'l ishlagani ("score" | "margin1" | "margin2" | "review" | "reject")
    — meta_json/log orqali keyin tahlil qilish uchun.
    """
    if score >= accept_threshold:
        return "accepted", "score"
    if B5_ENABLED and margin is not None:
        if score >= FLOOR1 and margin >= MARGIN1:
            return "accepted", "margin1"
        if score >= FLOOR2 and margin >= MARGIN2:
            return "accepted", "margin2"
    if score >= review_threshold:
        return "review", "review"
    return "rejected", "reject"
