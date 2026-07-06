"""
Annotatsiyalangan kadrlarni MJPEG stream sifatida serve qilish.
Brauzerda: http://localhost:8554/mjpeg
"""
import logging
import queue
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np

log = logging.getLogger(__name__)

_frame_queue: queue.Queue = queue.Queue(maxsize=2)


def push_frame(frame_bgr: np.ndarray):
    """Pipeline dan kadr qo'shish (eski kadr tashlanadi)."""
    if _frame_queue.full():
        try:
            _frame_queue.get_nowait()
        except queue.Empty:
            pass
    try:
        _frame_queue.put_nowait(frame_bgr)
    except queue.Full:
        pass


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # HTTP loglarni o'chirish

    def do_GET(self):
        if self.path != "/mjpeg":
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        while True:
            try:
                frame = _frame_queue.get(timeout=5.0)
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
    log.info("MJPEG server: http://localhost:%d/mjpeg", port)
    return server
