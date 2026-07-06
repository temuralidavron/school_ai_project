"""
1k3d68.onnx (InsightFace buffalo_l) — 3D 68-nuqta landmark aniqlash.

Yuz det_10g orqali topilgandan keyin bu model aniq landmark beradi.
Keyin bu aniq 5 nuqta face_align.align() ga uzatiladi.
Bu InsightFace buffalo_l get() bilan bir xil embedding ishlab chiqaradi.
"""
import logging
import numpy as np
import onnxruntime as ort
import cv2

log = logging.getLogger(__name__)

# 68-nuqtadan 5 kanoniq nuqta indekslari
_LEFT_EYE_IDX  = [36, 37, 38, 39, 40, 41]
_RIGHT_EYE_IDX = [42, 43, 44, 45, 46, 47]
_NOSE_IDX      = 30
_L_MOUTH_IDX   = 48
_R_MOUTH_IDX   = 54

# 1k3d68 output: (1, 3309) — oxirgi 204 qiymat = 68*3 landmark (tasnifi tasdiqlangan)
_LMK_OUTPUT_OFFSET = 204  # out[-204:].reshape(68,3)


class Landmark3d68Runner:
    INPUT_SIZE = 192

    def __init__(self, model_path: str, gpu_id: int = 0):
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3

        self._sess = ort.InferenceSession(
            model_path,
            sess_options=opts,
            providers=[
                ("CUDAExecutionProvider", {"device_id": gpu_id}),
                "CPUExecutionProvider",
            ],
        )
        self._in_name = self._sess.get_inputs()[0].name

        dummy = np.zeros((1, 3, self.INPUT_SIZE, self.INPUT_SIZE), dtype=np.float32)
        self._sess.run(None, {self._in_name: dummy})
        log.info("Landmark3d68Runner tayyor (GPU %d)", gpu_id)

    def get_5pts(self, frame_bgr: np.ndarray, bbox: list[float]) -> np.ndarray | None:
        """
        bbox [x1,y1,x2,y2] asosida 192×192 crop qilib 68 landmark topadi,
        keyin 5 kanoniq nuqtani original frame koordinatalarida qaytaradi.

        Qaytaradi: (5,2) float32 yoki None (yuz topilmasa)
        """
        x1, y1, x2, y2 = bbox
        w = x2 - x1
        h = y2 - y1
        if w < 4 or h < 4:
            return None

        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        scale = self.INPUT_SIZE / (max(w, h) * 1.5)

        # InsightFace affine matrix: output = scale*(input-center) + INPUT_SIZE/2
        half = self.INPUT_SIZE / 2
        M = np.array([
            [scale, 0,     -cx * scale + half],
            [0,     scale, -cy * scale + half],
        ], dtype=np.float32)

        crop = cv2.warpAffine(frame_bgr, M, (self.INPUT_SIZE, self.INPUT_SIZE),
                              flags=cv2.INTER_LINEAR)

        # Preprocessing: BGR→RGB, float32, 0-255
        rgb = crop[:, :, ::-1].astype(np.float32)
        inp = rgb.transpose(2, 0, 1)[np.newaxis]  # (1,3,192,192)

        out = self._sess.run(None, {self._in_name: inp})[0][0]  # (3309,)

        # Oxirgi 204 qiymat = 68*3 landmark
        pred = out[-_LMK_OUTPUT_OFFSET:].reshape(68, 3)

        # Normalizatsiya: [-1,1] → [0,192]
        pred_xy = pred[:, :2].copy()
        pred_xy = (pred_xy + 1) / 2 * self.INPUT_SIZE

        # 5 nuqta: ko'z markazlari, burun, og'iz burchaklari
        left_eye  = pred_xy[_LEFT_EYE_IDX].mean(axis=0)
        right_eye = pred_xy[_RIGHT_EYE_IDX].mean(axis=0)
        nose      = pred_xy[_NOSE_IDX]
        l_mouth   = pred_xy[_L_MOUTH_IDX]
        r_mouth   = pred_xy[_R_MOUTH_IDX]

        crop_pts = np.stack([left_eye, right_eye, nose, l_mouth, r_mouth], axis=0)  # (5,2)

        # Crop koordinatadan asl frame koordinataga
        # input = (output - half) / scale + center
        orig_pts = np.empty_like(crop_pts)
        orig_pts[:, 0] = (crop_pts[:, 0] - half) / scale + cx
        orig_pts[:, 1] = (crop_pts[:, 1] - half) / scale + cy

        return orig_pts.astype(np.float32)
