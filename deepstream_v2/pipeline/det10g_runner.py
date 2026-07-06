"""
det_10g.onnx (SCRFD) inference — onnxruntime-gpu.

Asosiy muammolar va yechimlar:
  1. Squish (aspect ratio buzilishi) → letterbox bilan hal qilinadi
  2. Kichik yuzlar → MIN_FACE_PX=20, score_thr=0.45
  3. SCRFD output layout: [score_s8, score_s16, score_s32, bbox_s8, ..., kps_s8, ...]

Model 640×640 fixed input. Letterbox: 1920×1080 → 640×360 padded → 640×640.
"""
import logging
import numpy as np
import onnxruntime as ort
import cv2

log = logging.getLogger(__name__)

_STRIDES     = [8, 16, 32]
_NUM_ANCHORS = 2
_INPUT_SZ    = 640  # ONNX model fixed input size (letterbox mana shu o'lchamga qisqartiradi)


def _build_anchors(input_sz: int) -> dict[int, np.ndarray]:
    """640×640 uchun anchor markazlari — InsightFace tartibida (interleaved)."""
    anchors = {}
    for s in _STRIDES:
        n = input_sz // s
        cy = (np.arange(n) * s).repeat(n)
        cx = np.tile(np.arange(n) * s, n)
        grid = np.stack([cx, cy], axis=1).astype(np.float32)
        # np.repeat: [loc0,loc0, loc1,loc1, ...] — InsightFace bilan mos
        anchors[s] = np.repeat(grid, _NUM_ANCHORS, axis=0)
    return anchors


_ANCHORS = _build_anchors(_INPUT_SZ)


def _letterbox(img: np.ndarray, size: int = 640):
    """
    Aspect ratio saqlab size×size ga resize + padding.
    InsightFace kabi yuqori-chapga joylashtirish (dw=dh=0).
    Qaytaradi: (padded_img, scale, dw, dh)
    """
    h, w = img.shape[:2]
    scale = size / max(h, w)
    nw, nh = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    padded = np.zeros((size, size, 3), dtype=np.uint8)
    dw, dh = 0, 0  # InsightFace: yuqori-chapga (markazga emas)
    padded[dh:dh + nh, dw:dw + nw] = resized
    return padded, scale, dw, dh


class Det10gRunner:
    INPUT_SIZE = _INPUT_SZ

    def __init__(self, model_path: str, gpu_id: int = 0):
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 1

        self._sess = ort.InferenceSession(
            model_path,
            sess_options=opts,
            providers=[
                ("CUDAExecutionProvider", {"device_id": gpu_id}),
                "CPUExecutionProvider",
            ],
        )
        self._in_name   = self._sess.get_inputs()[0].name
        self._out_names = [o.name for o in self._sess.get_outputs()]

        dummy = np.zeros((1, 3, _INPUT_SZ, _INPUT_SZ), dtype=np.float32)
        self._sess.run(self._out_names, {self._in_name: dummy})
        log.info("Det10gRunner tayyor: letterbox %dx%d (GPU %d)", _INPUT_SZ, _INPUT_SZ, gpu_id)

    def detect(self, frame_bgr: np.ndarray,
               score_thr: float = 0.45,
               nms_thr:   float = 0.40,
               min_px:    int   = 20) -> list[dict]:
        """
        Qaytaradi: [{"bbox":[x1,y1,x2,y2], "score":float, "kps":[[x,y]*5]}, ...]
        Koordinatalar asl frame o'lchamida.
        """
        padded, scale, dw, dh = _letterbox(frame_bgr, _INPUT_SZ)

        inp = padded[:, :, ::-1].astype(np.float32)
        inp = (inp - 127.5) / 128.0
        inp = inp.transpose(2, 0, 1)[np.newaxis]  # (1,3,640,640)

        outputs = self._sess.run(self._out_names, {self._in_name: inp})

        # SCRFD output layout: score[s8,s16,s32], bbox[s8,s16,s32], kps[s8,s16,s32]
        # indices:              0   1   2          3   4   5          6   7   8
        dets: list[dict] = []
        for i, stride in enumerate(_STRIDES):
            scores = outputs[i    ].reshape(-1)
            bboxes = outputs[i + 3].reshape(-1, 4)
            kps    = outputs[i + 6].reshape(-1, 10)

            keep = scores >= score_thr
            if not keep.any():
                continue

            ac = _ANCHORS[stride][keep]
            bd = bboxes[keep]
            kd = kps[keep]
            sc = scores[keep]

            # Letterbox koordinatalari → asl frame koordinatalari
            x1 = (ac[:, 0] - bd[:, 0] * stride - dw) / scale
            y1 = (ac[:, 1] - bd[:, 1] * stride - dh) / scale
            x2 = (ac[:, 0] + bd[:, 2] * stride - dw) / scale
            y2 = (ac[:, 1] + bd[:, 3] * stride - dh) / scale

            kps_arr = np.zeros((len(ac), 5, 2), np.float32)
            for k in range(5):
                kps_arr[:, k, 0] = (ac[:, 0] + kd[:, 2*k    ] * stride - dw) / scale
                kps_arr[:, k, 1] = (ac[:, 1] + kd[:, 2*k + 1] * stride - dh) / scale

            for j in range(len(sc)):
                if (x2[j] - x1[j]) < min_px or (y2[j] - y1[j]) < min_px:
                    continue
                dets.append({
                    "bbox":  [float(x1[j]), float(y1[j]), float(x2[j]), float(y2[j])],
                    "score": float(sc[j]),
                    "kps":   kps_arr[j].tolist(),
                })

        return _nms(dets, nms_thr) if dets else []


def _nms(dets: list[dict], thr: float) -> list[dict]:
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
