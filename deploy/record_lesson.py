"""
Dars videosini yozib oladi — jonli sinov isboti uchun.

Ikki rejim:
  raw — kameradan to'g'ridan (HLS/RTSP), AI belgilarisiz "xom" tasvir
  ai  — ds3 pipeline'ning MJPEG oqimidan (bbox, track ID, tanilgan ism bilan)

MAVJUD KODGA TEGMAYDI — faqat tashqaridan oqimni o'qib mp4 ga yozadi.

Ishlatish:
    python3.14 record_lesson.py --mode raw --url https://edu-api.devel.uz/cam16_9/index.m3u8 \
        --out /out/xom.mp4 --duration 2700
    python3.14 record_lesson.py --mode ai --url http://school_ai_ds3_run:8554/mjpeg/0 \
        --out /out/ai.mp4 --duration 2700

Ctrl+C (SIGINT/SIGTERM) bilan erta to'xtatilsa ham video TO'G'RI yopiladi.
"""
import argparse
import os
import signal
import sys
import time

import cv2
import numpy as np

_stop = False


def _on_signal(signum, frame):
    global _stop
    _stop = True


signal.signal(signal.SIGINT, _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


def _log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def record_raw(url, out_path, duration, fps):
    """Kamera oqimini to'g'ridan yozadi (HLS/RTSP)."""
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                          "rtsp_transport;tcp|stimeout;10000000")
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        _log(f"XATO: manba ochilmadi — {url}")
        return 1

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1920
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
    src_fps = cap.get(cv2.CAP_PROP_FPS)
    out_fps = fps or (src_fps if 1 < src_fps < 61 else 25)
    _log(f"raw: {w}x{h} @ {out_fps:.1f} fps -> {out_path}")

    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), out_fps, (w, h))
    t0, n, xato = time.time(), 0, 0
    while not _stop and (time.time() - t0) < duration:
        ok, frame = cap.read()
        if not ok or frame is None:
            xato += 1
            if xato > 150:            # ~ketma-ket uzilish — manba o'ldi
                _log("manba javob bermayapti, to'xtatildi")
                break
            time.sleep(0.05)
            continue
        xato = 0
        writer.write(frame)
        n += 1
        if n % 500 == 0:
            _log(f"raw: {n} kadr ({int(time.time()-t0)}s)")
    cap.release()
    writer.release()
    _log(f"raw TUGADI: {n} kadr, {int(time.time()-t0)}s -> {out_path}")
    return 0


def record_mjpeg(url, out_path, duration, fps):
    """ds3 ning MJPEG oqimini yozadi (AI belgilari bilan).

    MJPEG — multipart/x-mixed-replace; OpenCV uni ishonchsiz o'qiydi,
    shuning uchun JPEG chegaralarini (SOI/EOI) qo'lda ajratamiz.
    """
    import requests

    try:
        r = requests.get(url, stream=True, timeout=20)
        r.raise_for_status()
    except Exception as e:
        _log(f"XATO: MJPEG ochilmadi — {e}")
        return 1

    # Chiqish fps ni BOSHIDA aniqlab bo'lmaydi: pipeline dastlab buferdan tez
    # beradi (o'lchangan 31 fps), keyin haqiqiy tezligiga tushadi (~10 fps).
    # Boshiga qarab fps qo'ysak video bir necha barobar tez ko'rinadi
    # (2026-08-20: AI tasvir asl videodan 3x ilgarilab ketgan edi).
    #
    # Shuning uchun: kadrlarni JPEG holida diskka yozib boramiz, oxirida
    # HAQIQIY davomiylik bo'yicha fps = kadr/vaqt hisoblab videoga yig'amiz.
    # Disk sarfi kichik (JPEG ~100 KB), RAM da 1000+ kadr saqlashdan xavfsizroq.
    import shutil
    import tempfile

    tmpdir = tempfile.mkdtemp(prefix="ai_frames_", dir=os.path.dirname(out_path) or ".")
    buf = b""
    t0, n = time.time(), 0
    t_first = None
    size_wh = None

    for chunk in r.iter_content(chunk_size=8192):
        if _stop or (time.time() - t0) >= duration:
            break
        if not chunk:
            continue
        buf += chunk
        while True:
            a = buf.find(b"\xff\xd8")          # JPEG boshi
            b = buf.find(b"\xff\xd9", a + 2)   # JPEG oxiri
            if a == -1 or b == -1:
                break
            jpg, buf = buf[a:b + 2], buf[b + 2:]
            if t_first is None:
                t_first = time.time()
                # o'lchamni bir marta aniqlaymiz (dekodlash faqat shu yerda)
                fr0 = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                if fr0 is None:
                    t_first = None
                    continue
                size_wh = (fr0.shape[1], fr0.shape[0])
                _log(f"ai: {size_wh[0]}x{size_wh[1]} — kadrlar yig'ilmoqda...")

            # JPEG ni o'zgartirmasdan saqlaymiz — dekod/enkod qilmaymiz
            with open(os.path.join(tmpdir, f"{n:07d}.jpg"), "wb") as fh:
                fh.write(jpg)
            n += 1
            if n % 300 == 0:
                _log(f"ai: {n} kadr ({int(time.time()-t0)}s)")
        if len(buf) > 8_000_000:     # buzuq oqimda xotira o'smasin
            buf = b""

    # ── Yig'ish: HAQIQIY davomiylik bo'yicha fps ─────────────────────────────
    # Endi kadr soni ham, o'tgan vaqt ham aniq ma'lum — taxmin qilmaymiz.
    elapsed = (time.time() - t_first) if t_first else 0
    if n == 0 or elapsed <= 0 or size_wh is None:
        shutil.rmtree(tmpdir, ignore_errors=True)
        _log("ai: kadr olinmadi")
        return 1

    real_fps = round(n / elapsed, 2)
    real_fps = min(max(real_fps, 1.0), 60.0)
    _log(f"ai: {n} kadr / {elapsed:.1f}s -> {real_fps} fps (haqiqiy) — video yig'ilmoqda...")

    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"),
                             real_fps, size_wh)
    written = 0
    for name in sorted(os.listdir(tmpdir)):
        fr = cv2.imread(os.path.join(tmpdir, name), cv2.IMREAD_COLOR)
        if fr is None:
            continue
        if (fr.shape[1], fr.shape[0]) != size_wh:
            fr = cv2.resize(fr, size_wh)
        writer.write(fr)
        written += 1
    writer.release()
    shutil.rmtree(tmpdir, ignore_errors=True)

    _log(f"ai TUGADI: {written} kadr @ {real_fps} fps = {written/real_fps:.1f}s -> {out_path}")
    return 0 if written else 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["raw", "ai"], required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--duration", type=int, default=2700)
    p.add_argument("--fps", type=float, default=0)
    a = p.parse_args()

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    fn = record_raw if a.mode == "raw" else record_mjpeg
    return fn(a.url, a.out, a.duration, a.fps)


if __name__ == "__main__":
    sys.exit(main())
