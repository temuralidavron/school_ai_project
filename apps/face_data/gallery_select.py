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
