"""
Kamera ROI tanlash scripti.
Ishlatish:
    python select_roi.py --camera-id 1
    python select_roi.py --all

Qanday ishlaydi:
    1. Kameradan frame oladi
    2. Oyna ochiladi — sichqoncha bilan to'rtburchak chizasiz
    3. ENTER — ROI saqlanadi, S — o'tkazib yuborish, Q — chiqish
"""

import argparse
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

import cv2
from apps.cameras.models import Camera, CameraROI


def get_frame(stream_url: str):
    if not stream_url.endswith(".m3u8"):
        stream_url = stream_url.rstrip("/") + "/index.m3u8"
    cap = cv2.VideoCapture(stream_url)
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return None, stream_url
    return frame, stream_url


def select_roi_for_camera(cam: Camera) -> bool:
    print(f"\n[cam {cam.id}] {cam.name} — frame olinmoqda...")
    frame, url = get_frame(cam.stream_url or "")
    if frame is None:
        print(f"  ❌ Frame olinmadi: {url}")
        return False

    h, w = frame.shape[:2]
    print(f"  Frame: {w}x{h}")
    print(f"  Yo'riqnoma: sichqoncha bilan to'rtburchak chizing")
    print(f"  ENTER = saqlash | S = o'tkazish | Q = chiqish")

    # Mavjud ROI ni ko'rsatish
    existing = CameraROI.objects.filter(camera=cam).first()
    if existing:
        overlay = frame.copy()
        cv2.rectangle(overlay,
                      (existing.roi_x, existing.roi_y),
                      (existing.roi_x + existing.roi_width, existing.roi_y + existing.roi_height),
                      (0, 255, 0), 2)
        cv2.putText(overlay, "MAVJUD ROI", (existing.roi_x, existing.roi_y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        frame = overlay

    window_name = f"ROI: {cam.name} (ENTER=saqlash, S=o'tkazish, Q=chiqish)"

    # OpenCV ROI tanlash
    roi = cv2.selectROI(window_name, frame, showCrosshair=True, fromCenter=False)
    cv2.destroyAllWindows()

    x, y, rw, rh = roi
    if rw == 0 or rh == 0:
        print("  ⏭  ROI tanlanmadi, o'tkazildi")
        return False

    print(f"  ROI: x={x}, y={y}, width={rw}, height={rh}")

    # Saqlash
    CameraROI.objects.update_or_create(
        camera=cam,
        defaults={
            "roi_x": x,
            "roi_y": y,
            "roi_width": rw,
            "roi_height": rh,
            "frame_width": w,
            "frame_height": h,
        },
    )
    print(f"  ✅ ROI saqlandi!")
    return True


def main():
    parser = argparse.ArgumentParser(description="Kamera ROI tanlash")
    parser.add_argument("--camera-id", type=int, default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if args.all:
        cameras = list(Camera.objects.filter(
            is_active_stream=True,
            stream_url__isnull=False
        ).exclude(stream_url="").order_by("id"))
    elif args.camera_id:
        cameras = list(Camera.objects.filter(id=args.camera_id))
    else:
        print("--camera-id <N> yoki --all bering")
        return

    if not cameras:
        print("Kamera topilmadi")
        return

    print(f"Jami {len(cameras)} ta kamera")
    saved = 0
    for cam in cameras:
        result = select_roi_for_camera(cam)
        if result:
            saved += 1

    print(f"\nNatija: {saved}/{len(cameras)} kamera uchun ROI saqlandi")
    print("\nHozirgi ROI lar:")
    for roi in CameraROI.objects.select_related("camera").all():
        print(f"  {roi.camera.name}: ({roi.roi_x},{roi.roi_y}) {roi.roi_width}x{roi.roi_height}")


if __name__ == "__main__":
    main()
