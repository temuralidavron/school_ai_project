"""
appsink callback — barcha yuz detection, tracking, recognition va Kafka.

CPU path: GStreamer buffer → BGRx numpy → SCRFD → IouTracker → ArcFace → Kafka → MJPEG
"""
import base64
import json
import logging
import os
import time

import cv2
import numpy as np
from gi.repository import Gst

from pipeline.config import (
    DET_THRESHOLD, NMS_THRESHOLD, MIN_FACE_PX, TRACK_SEND_COOLDOWN, ARCFACE_BATCH_SIZE,
)
from pipeline.face_align  import align, align_from_bbox
from pipeline.iou_tracker import IouTracker
from pipeline.mjpeg_server import push_frame

log = logging.getLogger(__name__)

# /data/track_names.json — kafka_consumer tomonidan yoziladi
_NAMES_FILE      = os.getenv("NAMES_FILE", "/data/track_names.json")
_names_cache: dict[int, dict] = {}   # {track_id: {"name": "...", "pinfl": "..."}}
_names_mtime: float = 0.0
_NAMES_RELOAD_S  = 2.0

# Frontal filter: faqat yaw (chapga/o'ngga burish) tekshiriladi.
# Classroom kamerasi YUQORIDAN qaraydi → pitch tekshiruvi bloklamasligi kerak.
_MAX_YAW_RATIO = float(os.getenv("MAX_YAW_RATIO", "0.42"))  # burun-ko'z nisbati
# Yozib olingan video'ni tez qayta ishlash — har N-kadrda inference (RTSP'da 1).
_FRAME_SKIP = max(1, int(os.getenv("FRAME_SKIP", "1")))


def _is_frontal(kps: np.ndarray) -> bool:
    """Yuz yonboshga qarab turmasin (yaw filter). Classroom yuqori kamera uchun moslashtrilgan."""
    left_eye, right_eye, nose = kps[0], kps[1], kps[2]

    eye_cx   = (left_eye[0] + right_eye[0]) / 2
    eye_dist = abs(right_eye[0] - left_eye[0])
    if eye_dist < 4:
        return False

    # Burun ko'z markaziga qanchalik yaqin → shunchalik frontal (yaw tekshiruvi)
    return abs(nose[0] - eye_cx) / eye_dist <= _MAX_YAW_RATIO


def _display_crop_b64(frame_bgr, bbox, pad_ratio: float = 0.4,
                      min_size: int = 220, quality: int = 92) -> str:
    """Ko'rsatish/SKUD uchun tiniq yuz rasmi: original bbox + atrof padding.
    Orqa qatordagi kichik yuz min_size gacha INTER_CUBIC bilan kattalashtiriladi.
    Aligned 112x112 dan farqli — bu video haqiqiy piksellari (cho'zilmagan)."""
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    bw, bh = x2 - x1, y2 - y1
    if bw <= 0 or bh <= 0:
        return ""
    px, py = int(bw * pad_ratio), int(bh * pad_ratio)
    crop = frame_bgr[max(0, y1 - py):min(h, y2 + py),
                     max(0, x1 - px):min(w, x2 + px)]
    if crop.size == 0:
        return ""
    ch, cw = crop.shape[:2]
    m = min(ch, cw)
    if 0 < m < min_size:
        sc = min_size / m
        crop = cv2.resize(crop, (int(cw * sc), int(ch * sc)), interpolation=cv2.INTER_CUBIC)
    ok, jpg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(jpg).decode("ascii") if ok else ""


def _load_names() -> None:
    """JSON fayldan track_id → {name, pinfl} ma'lumotlarini yuklaydi."""
    global _names_mtime
    try:
        mtime = os.path.getmtime(_NAMES_FILE)
        if mtime <= _names_mtime:
            return
        with open(_NAMES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _names_cache.clear()
        for k, v in data.items():
            _names_cache[int(k)] = v if isinstance(v, dict) else {"name": str(v), "pinfl": ""}
        _names_mtime = mtime
    except (FileNotFoundError, ValueError, OSError):
        pass

# last_sent tozalash davri — 30 daqiqada bir marta
_LAST_SENT_MAX_AGE = 1800.0


def make_appsink_callback(probe_data: dict):
    """
    probe_data: {"detector": Det10gRunner, "landmark": Landmark3d68Runner,
                 "arcface": ArcFaceRunner, "kafka": KafkaClient, "camera_ids": dict}
    """
    detector   = probe_data["detector"]
    landmark   = probe_data["landmark"]
    arcface    = probe_data["arcface"]
    kafka      = probe_data["kafka"]
    camera_ids = probe_data["camera_ids"]

    # Har source uchun alohida IOU tracker (source_id → IouTracker)
    trackers: dict[int, IouTracker] = {}
    # {(source_id, track_id): float} — oxirgi Kafka yuborish vaqti
    last_sent: dict[tuple, float] = {}
    # {(source_id, track_id): list[np.ndarray]} — embedding yig'ish (average uchun)
    emb_buffer: dict[tuple, list] = {}

    # Closure-da saqlanadigan holat (global emas)
    state = {"frame_count": 0, "last_cleanup": time.time(), "last_names_reload": 0.0}

    def _on_new_sample(appsink):
        sample = appsink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.OK

        # Frame skip — yozib olingan video'ni tez qayta ishlash uchun.
        # Har _FRAME_SKIP-kadrda to'liq inference; oradagilar map/inference'siz
        # darrov tashlanadi → callback yengil → pipeline tez → video tez "ko'riladi".
        # RTSP (jonli kamera) uchun FRAME_SKIP=1 qoldiriladi (real-time).
        state["skip_ctr"] = state.get("skip_ctr", 0) + 1
        if _FRAME_SKIP > 1 and (state["skip_ctr"] % _FRAME_SKIP) != 0:
            return Gst.FlowReturn.OK

        gst_buf = sample.get_buffer()
        caps    = sample.get_caps()
        struct  = caps.get_structure(0)
        w = struct.get_value("width")
        h = struct.get_value("height")

        # Buffer → numpy BGR
        ok, mapinfo = gst_buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            # BGRx: 4 bytes per pixel, drop alpha channel
            frame_bgrx = np.frombuffer(mapinfo.data, dtype=np.uint8).reshape(h, w, 4)
            frame_bgr  = frame_bgrx[:, :, :3].copy()
        finally:
            gst_buf.unmap(mapinfo)

        state["frame_count"] += 1
        frame_num = state["frame_count"]

        if frame_num == 1:
            log.info("appsink: BIRINCHI kadr qabul qilindi! (%dx%d)", w, h)

        # source_id = 0 (hozircha bitta manba; ko'p kamera uchun pipeline_builder'da
        # alohida pipeline yaratiladi)
        source_id = 0

        if source_id not in trackers:
            trackers[source_id] = IouTracker()

        # ── 1. Yuz topish ─────────────────────────────────────────────────────
        dets = detector.detect(frame_bgr, score_thr=DET_THRESHOLD,
                               nms_thr=NMS_THRESHOLD, min_px=MIN_FACE_PX)

        if frame_num <= 3 or frame_num % 300 == 0:
            log.info("appsink: frame#%d → %d yuz topildi", frame_num, len(dets))

        # ── 2. Tracking ───────────────────────────────────────────────────────
        tracked = trackers[source_id].update(dets)

        # ── 3. Recognition + Kafka ────────────────────────────────────────────
        # Har track uchun 3 ta embedding to'planadi, average qilib Kafka'ga yuboriladi.
        # Bu top-down kamera uchun aniqlikni oshiradi.
        _EMB_POOL = int(os.getenv("EMB_POOL_SIZE", "3"))

        now = time.time()
        for t in tracked:
            tid = t["track_id"]
            key = (source_id, tid)

            # 1k3d68 landmark + frontal filter — har kadrda (bufferga qo'shish uchun)
            kps_1k3d68 = landmark.get_5pts(frame_bgr, t["bbox"])
            if kps_1k3d68 is None or not _is_frontal(kps_1k3d68):
                continue

            aligned = align(frame_bgr, kps_1k3d68)
            emb = arcface.get_embeddings([aligned])[0]

            # Bufferga qo'sh
            if key not in emb_buffer:
                emb_buffer[key] = []
            emb_buffer[key].append(emb)

            # Yetarli embedding to'plangan va cooldown o'tgan bo'lsa — Kafka'ga yubor
            if len(emb_buffer[key]) < _EMB_POOL:
                continue
            if now - last_sent.get(key, 0.0) < TRACK_SEND_COOLDOWN:
                emb_buffer[key] = []   # yangi pool boshlash
                continue

            # 3 ta embedding o'rtacha → normallashtir
            avg_emb = np.mean(emb_buffer[key], axis=0)
            norm = np.linalg.norm(avg_emb)
            if norm > 0:
                avg_emb = avg_emb / norm
            emb_buffer[key] = []

            cam_id = camera_ids.get(source_id, source_id + 1)
            bbox   = t["bbox"]
            # Ko'rsatish/SKUD rasmi: aligned 112x112 emas, original bbox'dan
            # kattaroq crop (atrof padding bilan) — video haqiqiy piksellari,
            # tiniqroq. Embedding baribir aligned'dan olingan (tanish o'zgarmaydi).
            face_b64 = _display_crop_b64(frame_bgr, bbox)

            kafka.send(
                camera_id = cam_id,
                frame_id  = frame_num,
                track_id  = tid,
                bbox      = {"x": bbox[0], "y": bbox[1],
                             "w": bbox[2] - bbox[0], "h": bbox[3] - bbox[1]},
                score     = t["score"],
                embedding = avg_emb.tolist(),
                face_crop = face_b64,
            )
            last_sent[key] = now

        # ── 4. last_sent / emb_buffer xotira tozalash (30 daqiqada bir marta) ───
        if now - state["last_cleanup"] > _LAST_SENT_MAX_AGE:
            cutoff = now - _LAST_SENT_MAX_AGE
            stale  = [k for k, v in last_sent.items() if v < cutoff]
            for k in stale:
                del last_sent[k]
                emb_buffer.pop(k, None)
            if stale:
                log.debug("last_sent tozalandi: %d yozuv o'chirildi", len(stale))
            state["last_cleanup"] = now

        # ── 5. MJPEG vizualizatsiya ───────────────────────────────────────────
        if now - state["last_names_reload"] > _NAMES_RELOAD_S:
            _load_names()
            state["last_names_reload"] = now

        vis = frame_bgr.copy()
        for t in tracked:
            x1, y1, x2, y2 = [int(v) for v in t["bbox"]]
            tid = t["track_id"]
            info = _names_cache.get(tid)
            if info:
                # Talaba tanilgan — yashil to'rtburchak + ism + o'xshashlik foizi + PINFL
                _score = info.get("score")
                name_str  = info.get("name",  "")[:24]
                if _score is not None:
                    name_str = f"{name_str} {_score}%"
                pinfl_str = info.get("pinfl", "")
                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 220, 0), 2)

                # Ism (bbox ustida, qora fon)
                font, fs, ft = cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1
                (nw, nh), _ = cv2.getTextSize(name_str, font, fs, ft)
                ny = max(y1 - 4, nh + 4)
                cv2.rectangle(vis, (x1, ny - nh - 4), (x1 + nw + 4, ny + 2), (0, 0, 0), -1)
                cv2.putText(vis, name_str, (x1 + 2, ny), font, fs, (0, 255, 0), ft)

                # PINFL (bbox ichida yoki pastida, kichikroq)
                if pinfl_str:
                    py = min(y2 + 16, vis.shape[0] - 4)
                    (pw, ph), _ = cv2.getTextSize(pinfl_str, font, 0.42, 1)
                    cv2.rectangle(vis, (x1, py - ph - 2), (x1 + pw + 4, py + 2), (0, 0, 0), -1)
                    cv2.putText(vis, pinfl_str, (x1 + 2, py), font, 0.42, (0, 230, 0), 1)
            else:
                # Hali tanilmagan — sariq to'rtburchak + track_id
                cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 200, 255), 2)
                cv2.putText(vis, f"T{tid}", (x1, max(y1 - 4, 10)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 1)
        push_frame(vis)

        return Gst.FlowReturn.OK

    return _on_new_sample
