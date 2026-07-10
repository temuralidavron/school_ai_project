"""
SCRFD xom tensor chiqishini decode qilish (nvinfer output-tensor-meta'dan).

deepstream_v2/det10g_runner.py bilan bir xil mantiq (anchors, NMS),
farqi: ORT sessiya emas, tayyor numpy massivlar qabul qiladi.
Layer'lar nomga emas, SHAKLga qarab tasniflanadi (engine binding tartibi
ONNX'dan farq qilishi mumkin — shakl ishonchli).
"""
import os

import numpy as np

_STRIDES     = [8, 16, 32]
_NUM_ANCHORS = 2
# Engine kirish o'lchami — pgie config'dagi infer-dims bilan mos bo'lishi SHART
# (640: s8=12800 s16=3200 s32=800; 1280: s8=51200 s16=12800 s32=3200)
INPUT_SZ     = int(os.getenv("DET_INPUT_SZ", "640"))

# stride -> anchor soni
_COUNT_TO_STRIDE = {
    (INPUT_SZ // s) ** 2 * _NUM_ANCHORS: s for s in _STRIDES
}


def _build_anchors(input_sz: int) -> dict:
    anchors = {}
    for s in _STRIDES:
        n = input_sz // s
        cy = (np.arange(n) * s).repeat(n)
        cx = np.tile(np.arange(n) * s, n)
        grid = np.stack([cx, cy], axis=1).astype(np.float32)
        anchors[s] = np.repeat(grid, _NUM_ANCHORS, axis=0)
    return anchors


_ANCHORS = _build_anchors(INPUT_SZ)


def classify_layers(layers: list) -> dict:
    """layers: [(name, np.ndarray), ...] -> {(stride, kind): arr (N,w)}
    Batch o'lchami ([1,N,w]) va 1D holatlarga chidamli: oxirgi o'lcham
    1/4/10 bo'lsa shundan, bo'lmasa umumiy hajmdan aniqlanadi."""
    out = {}
    for name, arr in layers:
        shape = list(arr.shape)
        total = arr.size
        w = shape[-1] if shape and shape[-1] in (1, 4, 10) else None
        if w is None:
            for cand in (10, 4, 1):
                if total % cand == 0 and (total // cand) in _COUNT_TO_STRIDE:
                    w = cand
                    break
        if w is None:
            continue
        n = total // w
        stride = _COUNT_TO_STRIDE.get(n)
        if stride is None:
            continue
        kind = {1: "score", 4: "bbox", 10: "kps"}[w]
        out[(stride, kind)] = arr.reshape(n, w)
    return out


def decode(layers: list, scale: float,
           score_thr: float = 0.35, nms_thr: float = 0.4,
           min_px: int = 20) -> list:
    """
    layers: [(name, np.ndarray), ...] — nvinfer tensor meta'dan
    scale:  INPUT_SZ / max(frame_w, frame_h) — letterbox koeffitsienti
    Qaytaradi: [{"bbox":[x1,y1,x2,y2], "score":f, "kps":[[x,y]*5]}] frame koordinatalarida.
    """
    by_key = classify_layers(layers)
    dets = []
    for stride in _STRIDES:
        sc = by_key.get((stride, "score"))
        bd = by_key.get((stride, "bbox"))
        kd = by_key.get((stride, "kps"))
        if sc is None or bd is None:
            continue
        scores = sc.reshape(-1)
        keep = scores >= score_thr
        if not keep.any():
            continue
        ac = _ANCHORS[stride][keep]
        b  = bd[keep]
        s  = scores[keep]
        x1 = (ac[:, 0] - b[:, 0] * stride) / scale
        y1 = (ac[:, 1] - b[:, 1] * stride) / scale
        x2 = (ac[:, 0] + b[:, 2] * stride) / scale
        y2 = (ac[:, 1] + b[:, 3] * stride) / scale
        if kd is not None:
            k = kd[keep]
            kps = np.zeros((len(ac), 5, 2), np.float32)
            for j in range(5):
                kps[:, j, 0] = (ac[:, 0] + k[:, 2*j    ] * stride) / scale
                kps[:, j, 1] = (ac[:, 1] + k[:, 2*j + 1] * stride) / scale
        else:
            kps = np.zeros((len(ac), 5, 2), np.float32)
        for j in range(len(s)):
            if (x2[j] - x1[j]) < min_px or (y2[j] - y1[j]) < min_px:
                continue
            dets.append({
                "bbox":  [float(x1[j]), float(y1[j]), float(x2[j]), float(y2[j])],
                "score": float(s[j]),
                "kps":   kps[j].tolist(),
            })
    return _nms(dets, nms_thr) if dets else []


def _nms(dets: list, thr: float) -> list:
    boxes  = np.array([d["bbox"]  for d in dets], np.float32)
    scores = np.array([d["score"] for d in dets], np.float32)
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas  = (x2 - x1) * (y2 - y1)
    order  = scores.argsort()[::-1]
    keep   = []
    while order.size:
        i = order[0]
        keep.append(i)
        ix1 = np.maximum(x1[i], x1[order[1:]])
        iy1 = np.maximum(y1[i], y1[order[1:]])
        ix2 = np.minimum(x2[i], x2[order[1:]])
        iy2 = np.minimum(y2[i], y2[order[1:]])
        inter = np.maximum(0.0, ix2 - ix1) * np.maximum(0.0, iy2 - iy1)
        iou   = inter / (areas[i] + areas[order[1:]] - inter + 1e-7)
        order = order[1:][iou < thr]
    return [dets[i] for i in keep]
