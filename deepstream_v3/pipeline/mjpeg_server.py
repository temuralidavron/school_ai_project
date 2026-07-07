"""
Annotatsiyalangan kadrlarni MJPEG stream sifatida serve qilish.
Per-source: har nvstreammux manbasi alohida oqim.
  http://localhost:8554/mjpeg/0   (0-manba)
  http://localhost:8554/mjpeg/1   (1-manba)
  http://localhost:8554/mjpeg      → 0-manba (eski manzil, backward-compat)
"""
import logging
import queue
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np

log = logging.getLogger(__name__)

# source_id -> so'nggi kadr navbati (lazy yaratiladi)
_queues: dict = {}
_lock = threading.Lock()


def _queue_for(source_id: int) -> queue.Queue:
    q = _queues.get(source_id)
    if q is None:
        with _lock:
            q = _queues.get(source_id)
            if q is None:
                q = queue.Queue(maxsize=2)
                _queues[source_id] = q
    return q


def push_frame(frame_bgr: np.ndarray, source_id: int = 0):
    """Pipeline dan kadr qo'shish (eski kadr tashlanadi)."""
    q = _queue_for(source_id)
    if q.full():
        try:
            q.get_nowait()
        except queue.Empty:
            pass
    try:
        q.put_nowait(frame_bgr)
    except queue.Full:
        pass


def _parse_source(path: str):
    # "/mjpeg" -> 0 ; "/mjpeg/2" -> 2 ; boshqasi -> None
    if path == "/mjpeg":
        return 0
    if path.startswith("/mjpeg/"):
        tail = path[len("/mjpeg/"):].split("?", 1)[0]
        try:
            return int(tail)
        except ValueError:
            return None
    return None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # HTTP loglarni o'chirish

    def do_GET(self):
        source_id = _parse_source(self.path)
        if source_id is None:
            self.send_error(404)
            return

        q = _queue_for(source_id)

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        while True:
            try:
                frame = q.get(timeout=5.0)
                _, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                data = jpg.tobytes()
                try:
                    header = (
                        f"--frame\r\nContent-Type: image/jpeg\r\n"
                        f"Content-Length: {len(data)}\r\n\r\n"
                    ).encode()
                    self.wfile.write(header + data + b"\r\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    return
            except queue.Empty:
                continue


class _ThreadedServer(socketserver.ThreadingMixIn, HTTPServer):
    """Har client uchun alohida thread — bir vaqtda ko'p browser ko'rishi mumkin."""
    daemon_threads = True


def start(port: int = 8554):
    """MJPEG server'ni background thread'da boshlash."""
    server = _ThreadedServer(("0.0.0.0", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    log.info("MJPEG server: http://localhost:%d/mjpeg/<source>", port)
    return server
