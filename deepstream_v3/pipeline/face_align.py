"""
5 ta yuz nuqtasi yordamida ArcFace uchun 112×112 aligned yuz kesib olish.

Standart nuqtalar (InsightFace buffalo_l bilan bir xil):
  0: chap ko'z, 1: o'ng ko'z, 2: burun, 3: chap og'iz, 4: o'ng og'iz
"""
import cv2
import numpy as np

_DST = np.array([
    [38.2946, 51.6963],   # chap ko'z
    [73.5318, 51.5014],   # o'ng ko'z
    [56.0252, 71.7366],   # burun
    [41.5493, 92.3655],   # chap og'iz
    [70.7299, 92.2041],   # o'ng og'iz
], dtype=np.float32)


def align(image: np.ndarray, kps: list | np.ndarray, size: int = 112) -> np.ndarray:
    """
    image: (H, W, 3) BGR uint8
    kps:   (5, 2) float — [chap_ko'z, o'ng_ko'z, burun, chap_og'iz, o'ng_og'iz]
    Qaytaradi: (size, size, 3) aligned yuz
    """
    src = np.array(kps, dtype=np.float32).reshape(5, 2)
    dst = _DST if size == 112 else _DST * (size / 112.0)

    M, _ = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=5.0)
    if M is None:
        # Fallback: bbox asosida oddiy resize
        x1 = max(0, int(src[:, 0].min()))
        y1 = max(0, int(src[:, 1].min()))
        x2 = min(image.shape[1], int(src[:, 0].max()))
        y2 = min(image.shape[0], int(src[:, 1].max()))
        crop = image[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else image[:1, :1]
        return cv2.resize(crop, (size, size))

    return cv2.warpAffine(image, M, (size, size), borderValue=0)


def align_from_bbox(image: np.ndarray, bbox: list[float], padding: float = 0.4) -> np.ndarray:
    """Landmarks yo'q bo'lsa bbox dan to'g'ridan-to'g'ri kesib resize qilish."""
    x1, y1, x2, y2 = bbox
    pw = (x2 - x1) * padding
    ph = (y2 - y1) * padding
    h, w = image.shape[:2]
    cx1 = max(0, int(x1 - pw))
    cy1 = max(0, int(y1 - ph))
    cx2 = min(w, int(x2 + pw))
    cy2 = min(h, int(y2 + ph))
    crop = image[cy1:cy2, cx1:cx2]
    return cv2.resize(crop, (112, 112)) if crop.size > 0 else np.zeros((112, 112, 3), np.uint8)
