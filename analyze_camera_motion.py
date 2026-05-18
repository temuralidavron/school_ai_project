"""
Kamera harakati tahlili — optical flow asosida.

Ishlatish:
    python analyze_camera_motion.py --video <fayl.mp4> [--step 15] [--output harakat.txt]

Chiqaradi:
    - Terminaldagi qisqa hisobot
    - harakat.txt — batafsil vaqt jadvali
    - harakat.json — JSON format (dasturda ishlatish uchun)
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np


# ─── MOTION CLASSIFIER ───────────────────────────────────────────────────────

def _analyze_flow(flow: np.ndarray) -> dict:
    """
    Optical flow matritsasidan kamera harakati turini aniqlaydi.

    flow shape: (H, W, 2) — har piksel uchun (dx, dy)

    Qaytaradi:
      type  — "static" | "pan_right" | "pan_left" | "tilt_down" | "tilt_up"
               | "zoom_in" | "zoom_out" | "rotation" | "complex"
      magnitude  — o'rtacha harakat miqdori (px)
      dx, dy     — o'rtacha gorizontal / vertikal siljish
      confidence — 0..1, klassifikatsiya ishonchliligi
    """
    h, w = flow.shape[:2]
    dx = float(np.mean(flow[..., 0]))
    dy = float(np.mean(flow[..., 1]))
    mag = float(np.mean(np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)))

    # Static threshold
    if mag < 0.4:
        return {"type": "static", "magnitude": mag, "dx": dx, "dy": dy, "confidence": 1.0}

    # Zoom detection: markazdan chetga (in) yoki chetdan markaza (out) radiyal flow
    cx, cy = w / 2, h / 2
    ys, xs = np.mgrid[0:h, 0:w]
    rx = xs - cx   # radial direction x
    ry = ys - cy   # radial direction y
    r_norm = np.sqrt(rx ** 2 + ry ** 2) + 1e-6
    rx_n = rx / r_norm
    ry_n = ry / r_norm

    radial_component = flow[..., 0] * rx_n + flow[..., 1] * ry_n
    mean_radial = float(np.mean(radial_component))
    radial_ratio = abs(mean_radial) / (mag + 1e-6)

    if radial_ratio > 0.55:
        return {
            "type": "zoom_in" if mean_radial > 0 else "zoom_out",
            "magnitude": mag,
            "dx": dx,
            "dy": dy,
            "confidence": float(radial_ratio),
        }

    # Rotation detection: tangensial komponent
    tx_n = -ry_n
    ty_n = rx_n
    tangential = flow[..., 0] * tx_n + flow[..., 1] * ty_n
    mean_tangential = float(np.mean(tangential))
    tangential_ratio = abs(mean_tangential) / (mag + 1e-6)

    if tangential_ratio > 0.5 and abs(mean_radial) < 0.3:
        return {
            "type": "rotation",
            "magnitude": mag,
            "dx": dx,
            "dy": dy,
            "confidence": float(tangential_ratio),
        }

    # Pan / Tilt
    adx, ady = abs(dx), abs(dy)
    if adx < 0.3 and ady < 0.3:
        return {"type": "complex", "magnitude": mag, "dx": dx, "dy": dy, "confidence": 0.5}

    if adx >= ady:
        motion_type = "pan_right" if dx > 0 else "pan_left"
        confidence = adx / (adx + ady + 1e-6)
    else:
        motion_type = "tilt_down" if dy > 0 else "tilt_up"
        confidence = ady / (adx + ady + 1e-6)

    return {
        "type": motion_type,
        "magnitude": mag,
        "dx": dx,
        "dy": dy,
        "confidence": float(confidence),
    }


_TYPE_LABELS = {
    "static":    "📷 STATIK",
    "pan_right": "→ PAN O'NG",
    "pan_left":  "← PAN CHAP",
    "tilt_down": "↓ TILT PAST",
    "tilt_up":   "↑ TILT YUQORI",
    "zoom_in":   "🔍 ZOOM IN",
    "zoom_out":  "🔎 ZOOM OUT",
    "rotation":  "↺ AYLANISH",
    "complex":   "⚡ MURAKKAB",
}


# ─── MAIN ANALYSIS ───────────────────────────────────────────────────────────

def analyze_video(video_path: str, step: int = 15, output_txt: str = "harakat.txt",
                  output_json: str = "harakat.json", small_w: int = 320):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[XATO] Video ochilmadi: {video_path}")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps
    w0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h0 = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Optical flow uchun kichik o'lcham (tezlik)
    scale = small_w / w0
    small_h = int(h0 * scale)

    print(f"\n{'='*62}")
    print(f"  KAMERA HARAKAT TAHLILI")
    print(f"{'='*62}")
    print(f"  Fayl      : {os.path.basename(video_path)}")
    print(f"  O'lcham   : {w0}×{h0}")
    print(f"  FPS       : {fps:.1f}")
    print(f"  Davomiylik: {duration_sec:.0f}s ({duration_sec/60:.1f} daqiqa)")
    print(f"  Tahlil    : har {step}-chi kadr (~{step/fps:.1f}s)")
    print(f"{'='*62}\n")

    prev_gray = None
    segments = []
    frame_num = 0
    processed = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_num += 1

        if frame_num % step != 0:
            continue

        small = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        if prev_gray is not None:
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, gray,
                None,
                pyr_scale=0.5, levels=3, winsize=13,
                iterations=3, poly_n=5, poly_sigma=1.2,
                flags=0,
            )
            info = _analyze_flow(flow)
            video_ts = frame_num / fps
            info["frame"] = frame_num
            info["time_sec"] = round(video_ts, 1)
            info["time_str"] = f"{int(video_ts//60):02d}:{int(video_ts%60):02d}"
            segments.append(info)
            processed += 1

        prev_gray = gray

    cap.release()

    if not segments:
        print("Tahlil uchun yetarli kadr yo'q.")
        return

    # ─── STATISTIKA ──────────────────────────────────────────────────────────
    type_counts: dict[str, int] = {}
    for s in segments:
        t = s["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    total_seg = len(segments)
    static_pct = type_counts.get("static", 0) / total_seg * 100
    motion_types_sorted = sorted(type_counts.items(), key=lambda x: -x[1])

    all_mags = [s["magnitude"] for s in segments if s["type"] != "static"]
    avg_motion_mag = float(np.mean(all_mags)) if all_mags else 0.0

    # Harakat qismlari (consecutive non-static segments)
    motion_events = []
    in_motion = False
    ev_start = None
    ev_type = None

    for s in segments:
        if s["type"] != "static":
            if not in_motion:
                in_motion = True
                ev_start = s
                ev_type = s["type"]
            elif s["type"] != ev_type:
                # Tur o'zgardi — yangi event
                motion_events.append({
                    "start": ev_start["time_str"],
                    "start_sec": ev_start["time_sec"],
                    "type": ev_type,
                    "label": _TYPE_LABELS.get(ev_type, ev_type),
                })
                ev_start = s
                ev_type = s["type"]
        else:
            if in_motion:
                motion_events.append({
                    "start": ev_start["time_str"],
                    "start_sec": ev_start["time_sec"],
                    "end": s["time_str"],
                    "end_sec": s["time_sec"],
                    "type": ev_type,
                    "label": _TYPE_LABELS.get(ev_type, ev_type),
                })
                in_motion = False

    if in_motion:
        motion_events.append({
            "start": ev_start["time_str"],
            "start_sec": ev_start["time_sec"],
            "end": segments[-1]["time_str"],
            "end_sec": segments[-1]["time_sec"],
            "type": ev_type,
            "label": _TYPE_LABELS.get(ev_type, ev_type),
        })

    # ─── TXT HISOBOT ─────────────────────────────────────────────────────────
    lines = []
    lines.append("=" * 62)
    lines.append("  KAMERA HARAKAT TAHLILI — BATAFSIL HISOBOT")
    lines.append("=" * 62)
    lines.append(f"  Video       : {os.path.basename(video_path)}")
    lines.append(f"  O'lcham     : {w0}x{h0}")
    lines.append(f"  Davomiylik  : {duration_sec:.0f}s ({duration_sec/60:.1f} daqiqa)")
    lines.append(f"  Tahlil qilingan segmentlar: {total_seg}")
    lines.append("")

    lines.append("── UMUMIY STATISTIKA ──────────────────────────────────────")
    for mtype, cnt in motion_types_sorted:
        pct = cnt / total_seg * 100
        bar = "█" * int(pct / 2)
        label = _TYPE_LABELS.get(mtype, mtype)
        lines.append(f"  {label:<20} {pct:5.1f}%  {bar}")
    lines.append("")
    lines.append(f"  Statik vaqt    : {static_pct:.1f}%")
    lines.append(f"  Harakatli vaqt : {100 - static_pct:.1f}%")
    lines.append(f"  O'rtacha harakat miqdori (non-static): {avg_motion_mag:.2f} px")
    lines.append("")

    lines.append("── HARAKAT HODISALARI (consecutive) ───────────────────────")
    if not motion_events:
        lines.append("  Harakat aniqlanmadi — kamera to'liq statik.")
    else:
        for ev in motion_events:
            end_str = ev.get("end", "—")
            lines.append(f"  {ev['start']} → {end_str}  |  {ev['label']}")
    lines.append("")

    lines.append("── VAQT BO'YICHA JADVAL ───────────────────────────────────")
    lines.append("  Vaqt    | Tur             | Mag  | dx     | dy")
    lines.append("  --------|-----------------|------|--------|--------")
    for s in segments:
        label = _TYPE_LABELS.get(s["type"], s["type"])
        lines.append(
            f"  {s['time_str']}   | {label:<16}| "
            f"{s['magnitude']:4.1f} | {s['dx']:+6.2f} | {s['dy']:+6.2f}"
        )
    lines.append("")

    lines.append("── KAMERA UCHUN TAVSIYALAR ────────────────────────────────")

    dominant_type = motion_types_sorted[0][0] if motion_types_sorted else "static"
    if static_pct > 85:
        lines.append("  ✓ Kamera asosan STATIK — maktab uchun ideal.")
        lines.append("    Kamerani devorga mahkam o'rnating, qo'shimcha")
        lines.append("    stabilizatsiya kerak emas.")
    elif static_pct > 60:
        lines.append("  ⚠ Kamerada ba'zi harakatlar bor — o'rniga qarab")
        lines.append("    bracket yoki bracket+suv pasi o'rnating.")
    else:
        lines.append("  ✗ Kamera ko'p harakat qilmoqda — avtomatik")
        lines.append("    PTZ (pan-tilt-zoom) bo'lishi mumkin.")
        lines.append("    AI davomati uchun STATIK rejimga o'tkazing.")

    for mtype, cnt in motion_types_sorted:
        if mtype == "static":
            continue
        pct = cnt / total_seg * 100
        if pct > 5:
            label = _TYPE_LABELS.get(mtype, mtype)
            if "pan" in mtype:
                lines.append(f"  → {label} ({pct:.0f}%): kamera gorizontal harakatlanmoqda.")
                lines.append("    AI bilan ishlash uchun avtomatik PTZ ni o'chiring.")
            elif "tilt" in mtype:
                lines.append(f"  → {label} ({pct:.0f}%): kamera vertikal harakatlanmoqda.")
            elif "zoom" in mtype:
                lines.append(f"  → {label} ({pct:.0f}%): kamera zoom qilmoqda.")
                lines.append("    Fixed focal length (zoom=1x) ni tavsiya etamiz.")

    lines.append("")
    lines.append("=" * 62)

    # Ekranga chiqarish
    print("\n".join(lines))

    # TXT faylga yozish
    with open(output_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nHisobot saqlandi: {output_txt}")

    # JSON faylga yozish
    report = {
        "video": os.path.basename(video_path),
        "resolution": f"{w0}x{h0}",
        "fps": round(fps, 2),
        "duration_sec": round(duration_sec, 1),
        "total_segments_analyzed": total_seg,
        "static_percent": round(static_pct, 1),
        "motion_percent": round(100 - static_pct, 1),
        "avg_motion_magnitude": round(avg_motion_mag, 3),
        "type_distribution": {
            t: {"count": c, "percent": round(c / total_seg * 100, 1)}
            for t, c in motion_types_sorted
        },
        "dominant_motion": dominant_type,
        "motion_events": motion_events,
        "timeline": segments,
        "recommendation": {
            "is_stable": static_pct > 85,
            "needs_ptz_disable": any(
                "pan" in t or "tilt" in t or "zoom" in t
                for t, c in motion_types_sorted
                if c / total_seg > 0.1
            ),
        },
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"JSON saqlandi   : {output_json}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kamera harakat tahlili")
    parser.add_argument("--video", required=True, help="Video fayl yo'li")
    parser.add_argument("--step", type=int, default=15,
                        help="Har N-chi kadrni tahlil qiladi (default 15 = ~0.5s @ 30fps)")
    parser.add_argument("--output", default="harakat.txt", help="TXT hisobot fayli")
    parser.add_argument("--json", default="harakat.json", help="JSON hisobot fayli")
    parser.add_argument("--small-width", type=int, default=320,
                        help="Optical flow uchun kadr kengligi (default 320)")
    args = parser.parse_args()

    analyze_video(
        video_path=args.video,
        step=args.step,
        output_txt=args.output,
        output_json=args.json,
        small_w=args.small_width,
    )
