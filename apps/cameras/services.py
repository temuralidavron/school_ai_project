import logging
import os
import tempfile
import threading
import time

import cv2
from django.utils import timezone

logger = logging.getLogger(__name__)


class CameraStreamService:
    """
    HTTP/MJPEG stream dan frame olib yuz tanish va davomat yozadi.
    URL format: https://edu-api.devel.uz/cam{org}_{room}
    """

    def __init__(
        self,
        camera,
        frame_interval: float | None = None,
        accept_threshold: float | None = None,
        review_threshold: float | None = None,
        reconnect_delay: float = 5.0,
    ):
        from django.conf import settings
        if frame_interval is None:
            frame_interval = getattr(settings, "AI_FRAME_INTERVAL", 2.0)
        if accept_threshold is None:
            accept_threshold = getattr(settings, "AI_ACCEPT_THRESHOLD", 0.55)
        if review_threshold is None:
            review_threshold = getattr(settings, "AI_REVIEW_THRESHOLD", 0.42)
        self.camera = camera
        self.frame_interval = frame_interval
        self.accept_threshold = accept_threshold
        self.review_threshold = review_threshold
        self.reconnect_delay = reconnect_delay

    def _get_organization_id(self) -> int:
        if self.camera.organization_id:
            return self.camera.organization_id
        from apps.integrations.models import ExternalClassroom
        classroom = ExternalClassroom.objects.filter(
            camera=self.camera
        ).select_related("organization").first()
        if classroom:
            return classroom.organization.organization_id
        raise ValueError(f"Camera id={self.camera.id} uchun organization_id topilmadi")

    def _save_frame(self, frame) -> str:
        ts = timezone.now().strftime("%Y%m%d_%H%M%S_%f")
        suffix = f"_cam{self.camera.id}_{ts}.jpg"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        cv2.imwrite(tmp_path, frame)
        return tmp_path

    def _log_result(self, result: dict, elapsed_ms: int = 0):
        face_count = result.get("face_count", 0)
        cam_id = self.camera.id

        if face_count == 0:
            logger.debug("cam=%s  yuz topilmadi  %dms", cam_id, elapsed_ms)
            return

        for r in result.get("results", []):
            s = r.get("status")
            best = r.get("best_match")
            decision = r.get("decision", "—")
            frontal = r.get("frontal_frames_used", 0)
            face_sz = r.get("face_size", "")

            if s == "recorded_and_locked" and best:
                skud = r.get("skud_push", {})
                logger.info(
                    "✓ DAVOMAT | cam=%-3s | %-30s | pinfl=%s | sim=%.3f | frontal=%d | %dms | skud=%s",
                    cam_id,
                    best.get("full_name", ""),
                    best.get("pinfl", ""),
                    best.get("best_score", 0),
                    frontal,
                    elapsed_ms,
                    skud.get("status", "?"),
                )
            elif s == "skipped_locked_after_search":
                logger.debug(
                    "~ lock    | cam=%-3s | %-30s | sim=%.3f",
                    cam_id, best.get("full_name", "") if best else "", best.get("best_score", 0) if best else 0,
                )
            elif s == "collecting_frontal":
                logger.debug(
                    "… frontal | cam=%-3s | %s/%s kadr | bbox=%s",
                    cam_id, r.get("frontal_count", 0), r.get("needed", 0), face_sz,
                )
            elif s == "skipped_blurry":
                logger.debug("≈ loyqa   | cam=%-3s | bbox=%s", cam_id, face_sz)
            elif s == "skipped_too_small":
                logger.debug("↓ kichik  | cam=%-3s | %s", cam_id, face_sz)
            elif s == "waiting_frontal":
                logger.debug("↺ poza    | cam=%-3s | %s | %s", cam_id, r.get("reason", ""), face_sz)
            elif s == "recorded":
                logger.debug(
                    "? yozildi | cam=%-3s | decision=%s | %s",
                    cam_id, decision, best.get("full_name", "") if best else "—",
                )
            elif s == "error":
                logger.warning("✗ xato    | cam=%-3s | %s", cam_id, r.get("error", ""))

    # Kamera uzilganda kutish vaqti eksponensial oshadi, maksimum shu qiymatda to'xtaydi
    _RECONNECT_MAX_DELAY = 120.0
    # Shu miqdor ketma-ket xato bo'lsa critical log + uzun uyqu
    _MAX_CONSECUTIVE_ERRORS = 30

    def _calc_backoff(self, error_count: int) -> float:
        """Eksponensial backoff: 5s → 10s → 20s → ... → 120s."""
        delay = self.reconnect_delay * (2 ** min(error_count - 1, 6))
        return min(delay, self._RECONNECT_MAX_DELAY)

    # FFMPEG ochish/o'qish timeout (mikrosekund). HLS stream o'lsa cv2.read()
    # abadiy osilib qolmaydi — shu vaqtdan keyin xato qaytaradi → qayta ulanish.
    _FFMPEG_TIMEOUT_US = 8_000_000  # 8 sekund

    def _open_capture(self, stream_url: str):
        """Persistent HLS capture — timeout bilan (qotib qolishni oldini oladi)."""
        cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
        # Bufer 1 kadr — har read() eng yangi kadrni beradi (real-time, lag yo'q)
        for prop, val in (
            (getattr(cv2, "CAP_PROP_BUFFERSIZE", None), 1),
            (getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), 8000),
            (getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), 8000),
        ):
            if prop is not None:
                try:
                    cap.set(prop, val)
                except Exception:
                    pass
        return cap

    def run(self, stop_event: threading.Event | None = None):
        from apps.attendance.services import LiveFrameProcessorService
        processor = LiveFrameProcessorService()

        stream_url = self.camera.stream_url
        if not stream_url:
            logger.error("Camera id=%s uchun stream_url yo'q", self.camera.id)
            return
        if not stream_url.endswith(".m3u8"):
            stream_url = stream_url.rstrip("/") + "/index.m3u8"

        # FFMPEG global timeout — CAP_PROP timeout backend'da ishlamasa, zaxira.
        # Faqat o'rnatilmagan bo'lsa qo'yamiz (boshqa kamera thread'ini buzmaslik).
        os.environ.setdefault(
            "OPENCV_FFMPEG_CAPTURE_OPTIONS",
            f"timeout;{self._FFMPEG_TIMEOUT_US}",
        )

        try:
            org_id = self._get_organization_id()
        except ValueError as e:
            logger.error(str(e))
            return

        cam_id = self.camera.id
        logger.info(
            "Stream boshlandi (persistent): cam=%s  url=%s  org=%s  interval=%.1fs  threshold=%.2f/%.2f",
            cam_id, stream_url, org_id,
            self.frame_interval, self.accept_threshold, self.review_threshold,
        )

        frame_count = 0
        error_count = 0
        cap = None

        try:
            while True:
                if stop_event and stop_event.is_set():
                    break

                # ── 1. Ulanish yo'q/uzilgan bo'lsa — ochamiz (timeout bilan) ──────
                if cap is None or not cap.isOpened():
                    if cap is not None:
                        try:
                            cap.release()
                        except Exception:
                            pass
                    cap = self._open_capture(stream_url)
                    if not cap.isOpened():
                        error_count += 1
                        backoff = self._calc_backoff(error_count)
                        if error_count >= self._MAX_CONSECUTIVE_ERRORS:
                            logger.critical(
                                "cam=%s ULANMADI %d marta ketma-ket! "
                                "Kamera o'chiq yoki tarmoq muammosi. %.0fs kutiladi.",
                                cam_id, error_count, backoff,
                            )
                        else:
                            logger.warning(
                                "cam=%s ulanmadi (#%d), %.0fs kutiladi",
                                cam_id, error_count, backoff,
                            )
                        if stop_event:
                            stop_event.wait(timeout=backoff)
                        else:
                            time.sleep(backoff)
                        continue
                    if error_count > 0:
                        logger.info("cam=%s qayta ulandi (avval %d xato bor edi)", cam_id, error_count)
                    error_count = 0

                t_loop = time.monotonic()

                # ── 2. Eng yangi kadrni olish (uzluksiz ulanishdan) ──────────────
                ret, frame = cap.read()
                if not ret or frame is None:
                    # HLS uzilgan/o'lgan — ulanishni yopib qayta ochamiz
                    error_count += 1
                    try:
                        cap.release()
                    except Exception:
                        pass
                    cap = None
                    backoff = self._calc_backoff(error_count)
                    logger.warning(
                        "cam=%s frame o'qilmadi (#%d) — qayta ulanish, %.0fs kutiladi",
                        cam_id, error_count, backoff,
                    )
                    if stop_event:
                        stop_event.wait(timeout=backoff)
                    else:
                        time.sleep(backoff)
                    continue

                frame_count += 1

                # ── 3. Kadrni qayta ishlash ───────────────────────────────────────
                tmp_path = self._save_frame(frame)
                t_ai = time.monotonic()
                try:
                    result = processor.process_frame_image(
                        image_path=tmp_path,
                        organization_id=org_id,
                        camera_id=cam_id,
                        accept_threshold=self.accept_threshold,
                        review_threshold=self.review_threshold,
                    )
                    elapsed_ms = int((time.monotonic() - t_ai) * 1000)
                    self._log_result(result, elapsed_ms=elapsed_ms)

                    if frame_count % 50 == 0:
                        logger.info(
                            "cam=%-3s  kadr=%-5d  yuz=%-2d  AI=%dms",
                            cam_id, frame_count, result.get("face_count", 0), elapsed_ms,
                        )
                        from apps.attendance.services import _cleanup_frontal_store
                        cleaned = _cleanup_frontal_store()
                        if cleaned:
                            logger.debug("cam=%s frontal_store cleanup: %d stale entry", cam_id, cleaned)
                except Exception as e:
                    error_count += 1
                    logger.error("cam=%s ishlov xatosi (#%d): %s", cam_id, error_count, str(e), exc_info=True)
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

                # ── 4. Interval — kutish vaqtida buferni bo'shatib turamiz ────────
                # (uzluksiz ulanishda eski kadrlar to'planmasligi uchun grab() bilan
                #  drenaj — keyingi read() eng yangi kadrni beradi)
                elapsed = time.monotonic() - t_loop
                remaining = self.frame_interval - elapsed
                while remaining > 0:
                    if stop_event and stop_event.is_set():
                        break
                    # Bufer drenaji — eski kadrlarni tashlab yubor (lag oldini oladi)
                    try:
                        cap.grab()
                    except Exception:
                        pass
                    time.sleep(min(0.2, remaining))
                    remaining = self.frame_interval - (time.monotonic() - t_loop)
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

        logger.info("Stream to'xtatildi: cam=%s  jami_kadr=%d", cam_id, frame_count)
