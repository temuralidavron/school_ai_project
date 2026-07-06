"""
Hamma konfiguratsiya env o'zgaruvchilardan.
Bitta joyda — boshqa fayllarda import qilish uchun.
"""
import os

# ── Kafka ────────────────────────────────────────────────────────────────────
KAFKA_BOOTSTRAP      = os.getenv("KAFKA_BOOTSTRAP",  "kafka:9092")
KAFKA_TOPIC          = os.getenv("KAFKA_TOPIC",       "deepstream-faces")

# ── Manba (RTSP yoki video fayl) ─────────────────────────────────────────────
# Vergul bilan ajratilgan URL ro'yxati:  rtsp://cam1,rtsp://cam2,...
# Yoki bitta video fayl: /data/sinf.mp4
RTSP_URLS            = [u.strip() for u in os.getenv("RTSP_URLS", "").split(",") if u.strip()]
VIDEO_FILE           = os.getenv("VIDEO_FILE", "")

# camera_id ↔ source_id moslashtirish (vergul bilan: "1,2,3,...")
# Agar ko'rsatilmasa — source index + 1
_cam_ids_str         = os.getenv("CAMERA_IDS", "")
CAMERA_IDS: list[int] = [int(x) for x in _cam_ids_str.split(",") if x.strip()] if _cam_ids_str else []

# ── GPU ───────────────────────────────────────────────────────────────────────
GPU_ID               = int(os.getenv("GPU_ID", "0"))

# ── DeepStream stream parametrlari ───────────────────────────────────────────
MUX_WIDTH            = int(os.getenv("MUX_WIDTH",  "1280"))
MUX_HEIGHT           = int(os.getenv("MUX_HEIGHT", "720"))
MUX_TIMEOUT_US       = int(os.getenv("MUX_TIMEOUT_US", "4000000"))  # 4ms

# ── Yuz topish (det_10g.onnx — SCRFD) ───────────────────────────────────────
# Model 640×640 fixed; letterbox frame'ni nisbat saqlab resize qiladi
DET_THRESHOLD        = float(os.getenv("DET_THRESHOLD", "0.50"))
NMS_THRESHOLD        = float(os.getenv("NMS_THRESHOLD", "0.40"))
MIN_FACE_PX          = int(os.getenv("MIN_FACE_PX",     "20"))

# ── Tracking ─────────────────────────────────────────────────────────────────
TRACKER_WIDTH        = int(os.getenv("TRACKER_WIDTH",  "640"))
TRACKER_HEIGHT       = int(os.getenv("TRACKER_HEIGHT", "384"))
# IouTracker parametrlari — env orqali sozlanadi (kod o'zgarmaydi).
# max_lost: track o'chirilishidan oldin necha kadr ko'rinmay tursa toqat qilinadi.
TRACKER_IOU_THR      = float(os.getenv("TRACKER_IOU_THR",  "0.3"))
TRACKER_MAX_LOST     = int(os.getenv("TRACKER_MAX_LOST",   "150"))

# ── Tanish (ArcFace — w600k_r50) ─────────────────────────────────────────────
TRACK_SEND_COOLDOWN  = int(os.getenv("TRACK_SEND_COOLDOWN", "10"))  # soniya
ARCFACE_BATCH_SIZE   = int(os.getenv("ARCFACE_BATCH_SIZE",  "16"))

# ── Model yo'llari ───────────────────────────────────────────────────────────
MODELS_DIR           = os.getenv("MODELS_DIR", "/root/.insightface/models")
ENGINES_DIR          = os.getenv("ENGINES_DIR", "/engines")
PGIE_CONFIG          = os.getenv("PGIE_CONFIG", "/configs/pgie_det10g.txt")
TRACKER_CONFIG       = os.getenv("TRACKER_CONFIG", "/configs/tracker_nvdcf.txt")
