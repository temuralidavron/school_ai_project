"""
Kamera annotatsiya menejeri.

Har kamera uchun bitta background thread:
  1. HLS stream dan frame oladi
  2. InsightFace bilan yuzlar aniqlanadi
  3. Yuz markaziga qarab track_key hisoblanadi
  4. Recognition natijasi 3 soniya kesh landi — har kadrda DB urmasin
  5. Frame annotatsiyalanadi va JPEG sifatida xotirada saqlanadi

MJPEG view shu xotiradan o'qib brauzerga uzatadi (~15 fps).
Davomat yozish ham shu threadda, lock mexanizmi takrorlanishni to'xtatadi.
"""

import hashlib
import logging
import os
import tempfile
import threading
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_COLOR_ACCEPTED = (34, 197,  94)   # yashil
_COLOR_REVIEW   = (234, 179,   8)   # sariq
_COLOR_UNKNOWN  = (239,  68,  68)   # qizil
_FONT           = cv2.FONT_HERSHEY_SIMPLEX

_PROCESS_INTERVAL = 0.4    # AI ishlash oraligi (sekundda)
_RECONNECT_DELAY  = 5.0
_RECOG_CACHE_TTL  = 3.0    # shu vaqt ichida bir xil yuz uchun DB urilmaydi


def _draw_label(img, text: str, x1: int, y1: int, color):
    (tw, th), _ = cv2.getTextSize(text, _FONT, 0.55, 1)
    bg_y1 = max(0, y1 - th - 10)
    cv2.rectangle(img, (x1, bg_y1), (x1 + tw + 8, y1), color, -1)
    cv2.putText(img, text, (x1 + 4, y1 - 4), _FONT, 0.55, (255, 255, 255), 1, cv2.LINE_AA)


def _track_key(camera_id, x1, y1, x2, y2, grid=80):
    cx = ((x1 + x2) // 2 // grid) * grid
    cy = ((y1 + y2) // 2 // grid) * grid
    digest = hashlib.md5(f"{camera_id}:{cx}:{cy}".encode()).hexdigest()[:12]
    return f"cam{camera_id}_track_{digest}"


class CameraFrameManager:
    """Thread-safe singleton. Har kamera uchun annotatsiyalangan JPEG saqlaydi."""

    _instance  = None
    _cls_lock  = threading.Lock()

    def __new__(cls):
        with cls._cls_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._threads:      dict[int, threading.Thread] = {}
                inst._stop_events:  dict[int, threading.Event]  = {}
                inst._frames:       dict[int, bytes]            = {}
                inst._frames_lock   = threading.Lock()
                inst._frame_ev:     dict[int, threading.Event]  = {}
                cls._instance = inst
        return cls._instance

    # ── Public ───────────────────────────────────────────────────────────────

    def ensure_running(self, camera_id: int):
        t = self._threads.get(camera_id)
        if t and t.is_alive():
            return
        stop_ev = threading.Event()
        frame_ev = threading.Event()
        self._stop_events[camera_id] = stop_ev
        self._frame_ev[camera_id]    = frame_ev
        t = threading.Thread(
            target=self._run,
            args=(camera_id, stop_ev, frame_ev),
            daemon=True,
            name=f"cam-ann-{camera_id}",
        )
        self._threads[camera_id] = t
        t.start()
        logger.info("cam=%s annotatsiya threadi boshlandi", camera_id)

    def stop(self, camera_id: int):
        ev = self._stop_events.get(camera_id)
        if ev:
            ev.set()

    def get_jpeg(self, camera_id: int) -> bytes | None:
        with self._frames_lock:
            return self._frames.get(camera_id)

    def wait_new_frame(self, camera_id: int, timeout: float = 1.5) -> bytes | None:
        ev = self._frame_ev.get(camera_id)
        if ev:
            ev.wait(timeout=timeout)
            ev.clear()
        return self.get_jpeg(camera_id)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _set_jpeg(self, camera_id: int, jpeg: bytes, frame_ev: threading.Event):
        with self._frames_lock:
            self._frames[camera_id] = jpeg
        frame_ev.set()

    def _run(self, camera_id: int, stop_ev: threading.Event, frame_ev: threading.Event):
        from apps.cameras.models import Camera
        from apps.face_data.services import RecognitionSearchService, get_face_app
        from apps.attendance.services import RecognitionEventService

        try:
            camera = Camera.objects.get(pk=camera_id)
        except Exception as exc:
            logger.error("cam=%s topilmadi: %s", camera_id, exc)
            return

        stream_url = (camera.stream_url or "").strip().rstrip("/")
        if not stream_url:
            logger.error("cam=%s: stream_url bo'sh yoki yo'q", camera_id)
            self._set_jpeg(camera_id, _no_signal_jpeg(), frame_ev)
            return
        if not stream_url.endswith(".m3u8"):
            stream_url = stream_url + "/index.m3u8"

        logger.info("cam=%s stream URL: %s", camera_id, stream_url)

        org_id     = camera.organization_id
        try:
            search_svc = RecognitionSearchService()
            rec_svc    = RecognitionEventService()
        except Exception as exc:
            logger.error("cam=%s service init xato: %s", camera_id, exc)
            self._set_jpeg(camera_id, _no_signal_jpeg(), frame_ev)
            return

        # track_key → (timestamp, result_dict)
        recog_cache: dict[str, tuple[float, dict]] = {}

        cap = None
        frame_count = 0
        consecutive_read_fails = 0
        _MAX_READ_FAILS = 5   # shu qadar ketma-ket xatoda signal yo'q ko'rsatiladi

        while not stop_ev.is_set():
            t_loop_start = time.monotonic()
            try:
                # ── Stream ulanishi ──────────────────────────────────────────
                if cap is None or not cap.isOpened():
                    logger.info("cam=%s ulanmoqda: %s", camera_id, stream_url)
                    cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
                    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10_000)
                    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8_000)
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    if not cap.isOpened():
                        logger.warning("cam=%s ulanmadi (stream_url=%s)", camera_id, stream_url)
                        cap.release()
                        cap = None
                        self._set_jpeg(camera_id, _no_signal_jpeg(), frame_ev)
                        time.sleep(_RECONNECT_DELAY)
                        continue
                    logger.info("cam=%s ulandi", camera_id)
                    consecutive_read_fails = 0

                ret, frame = cap.read()
                if not ret or frame is None:
                    consecutive_read_fails += 1
                    logger.debug("cam=%s frame o'qilmadi (%d/%d)",
                                 camera_id, consecutive_read_fails, _MAX_READ_FAILS)
                    if consecutive_read_fails >= _MAX_READ_FAILS:
                        cap.release()
                        cap = None
                        self._set_jpeg(camera_id, _no_signal_jpeg(), frame_ev)
                        time.sleep(_RECONNECT_DELAY)
                        consecutive_read_fails = 0
                    else:
                        time.sleep(0.2)
                    continue
                consecutive_read_fails = 0

                frame_count += 1

                # ── Yuz aniqlash (50% kichraytirish → 4x tezroq) ────────────
                detector = get_face_app()
                h0, w0   = frame.shape[:2]
                small    = cv2.resize(frame, (w0 // 2, h0 // 2), interpolation=cv2.INTER_LINEAR)
                t_ai = time.monotonic()
                faces    = detector.get(small)
                ai_ms = int((time.monotonic() - t_ai) * 1000)

                annotated = frame.copy()
                now_ts    = time.monotonic()

                for face in faces:
                    # BBox koordinatlarini asl o'lchamga qaytaramiz
                    face.bbox = face.bbox * 2.0
                    if hasattr(face, 'kps') and face.kps is not None:
                        face.kps = face.kps * 2.0
                    x1, y1, x2, y2 = face.bbox.astype(int).tolist()
                    face_w = x2 - x1
                    face_h = y2 - y1

                    # Juda kichik yuzlarni o'tkazib yuboramiz
                    if face_w < 30 or face_h < 30:
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), _COLOR_UNKNOWN, 1)
                        continue

                    tk = _track_key(camera_id, x1, y1, x2, y2)

                    # ── Kesh tekshirish ──────────────────────────────────────
                    cached = recog_cache.get(tk)
                    is_fresh = not (cached and (now_ts - cached[0]) < _RECOG_CACHE_TTL)
                    if not is_fresh:
                        result = cached[1]
                        emb = None
                    else:
                        # Kichik yuz uchun upscale → sifatliroq embedding
                        emb = _get_upscaled_emb(detector, frame, x1, y1, x2, y2) \
                              if (face_w < 120 or face_h < 120) else face.embedding
                        if emb is None:
                            emb = face.embedding
                        if emb is not None:
                            result = search_svc.decide_match_by_embedding(
                                query_embedding=emb.astype(np.float32),
                                organization_id=org_id,
                                top_k=1,
                                accept_threshold=0.55,
                                review_threshold=0.40,
                            )
                        else:
                            result = {"decision": "rejected", "best_match": None}
                        recog_cache[tk] = (now_ts, result)

                    best     = result.get("best_match")
                    decision = result.get("decision")

                    if decision == "accepted" and best:
                        label = f"{best['full_name']}  {best['best_score']*100:.0f}%"
                        color = _COLOR_ACCEPTED
                        # Faqat yangi recognition bo'lganda DB ga yozamiz — background threadda
                        if is_fresh and emb is not None:
                            used_emb = emb.copy()
                            frame_copy = frame.copy()
                            threading.Thread(
                                target=self._try_attend,
                                args=(rec_svc, frame_copy, (x1, y1, x2, y2),
                                      used_emb, org_id, camera_id, tk),
                                daemon=True,
                                name=f"attend-cam{camera_id}",
                            ).start()
                    elif decision == "review" and best:
                        label = f"? {best['full_name']}  {best['best_score']*100:.0f}%"
                        color = _COLOR_REVIEW
                    else:
                        label = "Unknown"
                        color = _COLOR_UNKNOWN

                    cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                    _draw_label(annotated, label, x1, y1, color)

                # ── HUD: yuzlar soni + AI vaqti + FPS ───────────────────────
                elapsed_loop = time.monotonic() - t_loop_start
                fps_est = 1.0 / elapsed_loop if elapsed_loop > 0 else 0
                hud1 = f"Yuzlar: {len(faces)}  AI:{ai_ms}ms  FPS:{fps_est:.1f}"
                cv2.putText(annotated, hud1, (10, 30),
                            _FONT, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

                _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 78])
                self._set_jpeg(camera_id, buf.tobytes(), frame_ev)

                # Har 100 kadrda log + kesh tozalash
                if frame_count % 100 == 0:
                    logger.info(
                        "cam=%s  kadr=%d  yuz=%d  ai=%dms  fps=%.1f",
                        camera_id, frame_count, len(faces), ai_ms, fps_est,
                    )
                    recog_cache = {
                        k: v for k, v in recog_cache.items()
                        if now_ts - v[0] < _RECOG_CACHE_TTL
                    }

            except Exception as exc:
                logger.error("cam=%s xato: %s", camera_id, exc, exc_info=True)
                if cap:
                    cap.release()
                    cap = None
                self._set_jpeg(camera_id, _no_signal_jpeg(), frame_ev)
                time.sleep(_RECONNECT_DELAY)
                continue

            # Qolgan vaqtni kutamiz — AI vaqtini hisobga olib
            elapsed = time.monotonic() - t_loop_start
            remaining = max(0.0, _PROCESS_INTERVAL - elapsed)
            if remaining > 0:
                time.sleep(remaining)

        if cap:
            cap.release()
        logger.info("cam=%s threadi to'xtatildi", camera_id)

    @staticmethod
    def _try_attend(rec_svc, frame, bbox, emb, org_id, camera_id, track_key):
        try:
            x1, y1, x2, y2 = bbox
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0 or emb is None:
                return
            with tempfile.NamedTemporaryFile(suffix="_crop.jpg", delete=False) as tmp:
                path = tmp.name
            try:
                cv2.imwrite(path, crop)
                rec_svc.recognize_track_and_record_by_embedding(
                    track_key=track_key,
                    image_path=path,
                    query_embedding=emb.astype(np.float32),
                    organization_id=org_id,
                    camera_id=camera_id,
                    bbox=bbox,
                    accept_threshold=0.70,
                    review_threshold=0.55,
                    save_base64=False,
                )
            finally:
                if os.path.exists(path):
                    os.remove(path)
        except Exception as exc:
            logger.debug("cam=%s attend xato: %s", camera_id, exc)


def _get_upscaled_emb(detector, frame, x1, y1, x2, y2, target: int = 256):
    """Kichik yuz crop → upscale → qayta detect → sifatli embedding."""
    h, w = frame.shape[:2]
    pad_x = max(8, (x2 - x1) // 4)
    pad_y = max(8, (y2 - y1) // 4)
    cx1 = max(0, x1 - pad_x); cy1 = max(0, y1 - pad_y)
    cx2 = min(w, x2 + pad_x); cy2 = min(h, y2 + pad_y)
    crop = frame[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None
    ch, cw = crop.shape[:2]
    if cw < target or ch < target:
        scale = max(target / cw, target / ch)
        crop = cv2.resize(crop, (int(cw * scale), int(ch * scale)), interpolation=cv2.INTER_CUBIC)
    faces = detector.get(crop)
    if not faces:
        return None
    best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return best.embedding


def _no_signal_jpeg() -> bytes:
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    img[:] = (20, 20, 30)
    cv2.putText(img, "Signal yo'q", (195, 175), _FONT, 1.1, (120,120,140), 2, cv2.LINE_AA)
    cv2.putText(img, "Kamera ulanmagan", (165, 215), _FONT, 0.65, (70,70,90), 1, cv2.LINE_AA)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 60])
    return buf.tobytes()
