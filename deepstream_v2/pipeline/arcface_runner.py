"""
ArcFace (w600k_r50.onnx) ONNX Runtime GPU inference — batched.

10 kamera × 25 fps × O'rtacha 5 yuz = 1250 inference/s.
Batchlash bilan GPU GPU samaraliroq ishlatiladi.
"""
import logging
import numpy as np
import onnxruntime as ort

log = logging.getLogger(__name__)


class ArcFaceRunner:
    INPUT_SIZE = 112

    def __init__(self, model_path: str, gpu_id: int = 0):
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3  # 3=ERROR, batch shape mismatch warning ni o'chirish

        self._sess = ort.InferenceSession(
            model_path,
            sess_options=opts,
            providers=[
                ("CUDAExecutionProvider", {"device_id": gpu_id}),
                "CPUExecutionProvider",
            ],
        )
        self._in  = self._sess.get_inputs()[0].name   # "input.1"
        self._out = self._sess.get_outputs()[0].name  # "683"

        # Isiqish uchun bir marta bo'sh inference
        dummy = np.zeros((1, 3, self.INPUT_SIZE, self.INPUT_SIZE), dtype=np.float32)
        self._sess.run([self._out], {self._in: dummy})
        log.info("ArcFaceRunner tayyor: %s (GPU %d)", model_path, gpu_id)

    def get_embeddings(self, faces_bgr: list[np.ndarray]) -> np.ndarray:
        """
        faces_bgr: list of (112, 112, 3) BGR uint8
        Qaytaradi: (N, 512) L2-normallashtirilgan float32
        """
        if not faces_bgr:
            return np.zeros((0, 512), np.float32)

        batch = np.stack([_preprocess(f) for f in faces_bgr], axis=0)  # (N, 3, 112, 112)
        embs  = self._sess.run([self._out], {self._in: batch})[0]       # (N, 512)

        norms = np.linalg.norm(embs, axis=1, keepdims=True)
        return embs / np.maximum(norms, 1e-7)


def _preprocess(face_bgr: np.ndarray) -> np.ndarray:
    """(112,112,3) BGR uint8 → (3,112,112) float32 [-1, 1]"""
    rgb = face_bgr[:, :, ::-1].astype(np.float32)
    rgb = (rgb - 127.5) / 128.0
    return rgb.transpose(2, 0, 1)  # HWC → CHW
