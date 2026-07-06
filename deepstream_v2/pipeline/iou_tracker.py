"""
Oddiy IOU-based yuz tracker.
nvtracker o'rniga — CUDA context muammosisiz.
"""
import numpy as np

from pipeline.config import TRACKER_IOU_THR, TRACKER_MAX_LOST


def _iou(box_a, box_b):
    xa = max(box_a[0], box_b[0])
    ya = max(box_a[1], box_b[1])
    xb = min(box_a[2], box_b[2])
    yb = min(box_a[3], box_b[3])
    inter = max(0, xb - xa) * max(0, yb - ya)
    if inter == 0:
        return 0.0
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    return inter / (area_a + area_b - inter + 1e-7)


class IouTracker:
    def __init__(self, iou_thr=None, max_lost=None):
        self._iou_thr  = TRACKER_IOU_THR if iou_thr is None else iou_thr
        self._max_lost = TRACKER_MAX_LOST if max_lost is None else max_lost
        self._tracks: dict[int, dict] = {}  # track_id → {bbox, lost, kps}
        self._next_id = 1

    def update(self, dets: list[dict]) -> list[dict]:
        """
        dets: [{"bbox":[x1,y1,x2,y2], "score":float, "kps":...}, ...]
        Returns: [{"track_id":int, "bbox":..., "score":..., "kps":...}, ...]
        """
        if not dets and not self._tracks:
            return []

        # Lost counter oshirish
        for t in self._tracks.values():
            t["lost"] += 1

        # Greedy IOU matching
        matched_tids = set()
        result = []

        for det in dets:
            best_tid, best_iou = None, self._iou_thr
            for tid, track in self._tracks.items():
                if tid in matched_tids:
                    continue
                iou = _iou(det["bbox"], track["bbox"])
                if iou > best_iou:
                    best_iou = iou
                    best_tid = tid

            if best_tid is not None:
                self._tracks[best_tid].update(bbox=det["bbox"], lost=0, kps=det.get("kps"))
                matched_tids.add(best_tid)
                result.append({**det, "track_id": best_tid})
            else:
                tid = self._next_id
                self._next_id += 1
                self._tracks[tid] = {"bbox": det["bbox"], "lost": 0, "kps": det.get("kps")}
                result.append({**det, "track_id": tid})

        # Eskirgan track'larni o'chirish
        self._tracks = {tid: t for tid, t in self._tracks.items()
                        if t["lost"] <= self._max_lost}
        return result
