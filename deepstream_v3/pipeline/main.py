#!/usr/bin/env python3
"""
DeepStream 8.0 to'liq pipeline — B3: nvinfer + nvtracker + ArcFace gibrid + Kafka.

Arxitektura:
  filesrc → qtdemux → h264parse → nvv4l2decoder → nvstreammux
  → nvinfer (det_10g TRT, tensor-meta)
  → [probe A: SCRFD decode → obj_meta + kps + bInferDone]
  → nvtracker (NvDCF GPU, barqaror object_id)
  → nvvideoconvert → RGBA (unified)
  → [probe C: frontal filtr → SCRFD kps bilan align (InsightFace standarti,
     enrollment bilan mos) → 3-embedding pool → ArcFace ORT batch
     → Kafka (v2 bilan AYNAN bir xil format) + katta display crop]
  → fakesink

Django kafka_consumer O'ZGARMAYDI.
"""
import argparse
import base64
import ctypes
import logging
import os
import sys
import time

import cv2
import numpy as np

import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst

import pyds

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrfd_decode import decode, INPUT_SZ
from face_align import align
from arcface_runner import ArcFaceRunner
from kafka_client import KafkaClient
from mjpeg_server import push_frame, start as mjpeg_start

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("ds3_main")

MUX_WIDTH   = int(os.getenv("MUX_WIDTH",  "1920"))
MUX_HEIGHT  = int(os.getenv("MUX_HEIGHT", "1080"))
DET_THR     = float(os.getenv("DET_THRESHOLD", "0.35"))
NMS_THR     = float(os.getenv("NMS_THRESHOLD", "0.40"))
MIN_PX      = int(os.getenv("MIN_FACE_PX", "20"))
PGIE_CFG    = os.getenv("PGIE_CONFIG", "/ds3/configs/pgie_det10g.txt")
TRACKER_LIB = os.getenv("TRACKER_LIB",
                        "/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so")
TRACKER_CFG = os.getenv("TRACKER_CONFIG", "/ds3/configs/tracker_nvdcf_faces.yml")

KAFKA_BOOTSTRAP     = os.getenv("KAFKA_BOOTSTRAP", "")
KAFKA_TOPIC         = os.getenv("KAFKA_TOPIC", "deepstream-faces")
TRACK_SEND_COOLDOWN = float(os.getenv("TRACK_SEND_COOLDOWN", "3"))
EMB_POOL            = int(os.getenv("EMB_POOL", "3"))
MAX_YAW_RATIO       = float(os.getenv("MAX_YAW_RATIO", "0.6"))
MODELS_DIR          = os.getenv("MODELS_DIR", "/root/.insightface/models")
GPU_ID              = int(os.getenv("GPU_ID", "0"))

# source_id -> camera_id (B4 multi-source uchun tayyor)
_cam_ids_env = os.getenv("CAMERA_IDS", "1")
CAMERA_IDS = {i: int(c) for i, c in
              enumerate(x.strip() for x in _cam_ids_env.split(",") if x.strip())}

_state = {"frames": 0, "faces_total": 0, "sent": 0,
          "track_ids": set(), "t0": time.time()}
_kps_store: dict = {}
_KPS_STORE_MAX = 60
# (source_id, track_id) -> [emb, ...] va oxirgi yuborish vaqti
_emb_buffer: dict = {}
_last_sent: dict = {}

_arcface: ArcFaceRunner = None
_kafka: KafkaClient = None

# MJPEG vizualizatsiya: har N-kadrda chiziladi (CPU tejash)
VIS_EVERY   = int(os.getenv("VIS_EVERY", "2"))
_NAMES_FILE = os.getenv("NAMES_FILE", "/data/track_names.json")
_names_cache: dict = {}
_names_mtime = 0.0


def _load_names():
    """kafka_consumer yozgan track_id -> {name, pinfl, score} (2s da bir)."""
    global _names_mtime
    import json
    try:
        mt = os.path.getmtime(_NAMES_FILE)
        if mt <= _names_mtime:
            return
        with open(_NAMES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        _names_cache.clear()
        for k, v in data.items():
            _names_cache[int(k)] = v if isinstance(v, dict) else {"name": str(v)}
        _names_mtime = mt
    except (OSError, ValueError):
        pass

# layer nomi -> (stride, ustun); anchor soni INPUT_SZ dan: (sz/stride)^2 * 2
# (inferDims meta ishonchsiz — B1 tuzoq #3, shuning uchun shakl shu yerda)
_DET10G_LAYERS = {
    "448": (8, 1), "471": (16, 1), "494": (32, 1),
    "451": (8, 4), "474": (16, 4), "497": (32, 4),
    "454": (8, 10), "477": (16, 10), "500": (32, 10),
}
_DET10G_SHAPES = {
    name: ((INPUT_SZ // stride) ** 2 * 2, w)
    for name, (stride, w) in _DET10G_LAYERS.items()
}
_DET10G_SHAPES.update({k + "_b": v for k, v in list(_DET10G_SHAPES.items())})


def _extract_layers(tensor_meta) -> list:
    layers = []
    for i in range(tensor_meta.num_output_layers):
        linfo = pyds.get_nvds_LayerInfo(tensor_meta, i)
        if not linfo.buffer:
            continue
        name = linfo.layerName
        known = _DET10G_SHAPES.get(name)
        if known:
            shape = list(known)
        else:
            dims = linfo.inferDims
            shape = [dims.d[k] for k in range(dims.numDims)]
        n = int(np.prod(shape)) if shape else 0
        if n == 0:
            continue
        ptr = ctypes.cast(pyds.get_ptr(linfo.buffer),
                          ctypes.POINTER(ctypes.c_float))
        arr = np.ctypeslib.as_array(ptr, shape=(n,)).copy().reshape(shape)
        layers.append((name, arr))
    return layers


def _add_obj_meta(batch_meta, frame_meta, det):
    x1, y1, x2, y2 = det["bbox"]
    obj = pyds.nvds_acquire_obj_meta_from_pool(batch_meta)
    obj.unique_component_id = 1
    obj.class_id = 0
    obj.confidence = det["score"]
    obj.obj_label = "face"
    r = obj.rect_params
    r.left = max(0.0, x1)
    r.top = max(0.0, y1)
    r.width = max(1.0, x2 - x1)
    r.height = max(1.0, y2 - y1)
    r.border_width = 0
    obj.object_id = 0xFFFFFFFFFFFFFFFF
    pyds.nvds_add_obj_meta_to_frame(frame_meta, obj, None)


def _pgie_probe(pad, info, _u):
    buf = info.get_buffer()
    if not buf:
        return Gst.PadProbeReturn.OK
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(buf))
    if not batch_meta:
        return Gst.PadProbeReturn.OK

    scale = INPUT_SZ / max(MUX_WIDTH, MUX_HEIGHT)
    l_frame = batch_meta.frame_meta_list
    while l_frame is not None:
        frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        l_user = frame_meta.frame_user_meta_list
        while l_user is not None:
            user_meta = pyds.NvDsUserMeta.cast(l_user.data)
            if (user_meta.base_meta.meta_type
                    == pyds.NvDsMetaType.NVDSINFER_TENSOR_OUTPUT_META):
                tmeta = pyds.NvDsInferTensorMeta.cast(user_meta.user_meta_data)
                dets = decode(_extract_layers(tmeta), scale=scale,
                              score_thr=DET_THR, nms_thr=NMS_THR, min_px=MIN_PX)
                for d in dets:
                    _add_obj_meta(batch_meta, frame_meta, d)
                # nvtracker bInferDone=0 kadrlarni tashlab yuboradi
                frame_meta.bInferDone = 1
                _kps_store[(frame_meta.source_id, frame_meta.frame_num)] = dets
                if len(_kps_store) > _KPS_STORE_MAX:
                    for k in sorted(_kps_store)[:-_KPS_STORE_MAX // 2]:
                        _kps_store.pop(k, None)
            try:
                l_user = l_user.next
            except StopIteration:
                break
        try:
            l_frame = l_frame.next
        except StopIteration:
            break
    return Gst.PadProbeReturn.OK


def _match_kps(dets, l, t, w, h):
    if not dets:
        return None
    cx, cy = l + w / 2, t + h / 2
    best, best_d = None, 1e18
    for d in dets:
        x1, y1, x2, y2 = d["bbox"]
        dx = (x1 + x2) / 2 - cx
        dy = (y1 + y2) / 2 - cy
        dist = dx * dx + dy * dy
        if dist < best_d:
            best_d, best = dist, d
    if best is not None and best_d > (max(w, h) * 0.75) ** 2:
        return None
    return best


def _is_frontal(kps: np.ndarray) -> bool:
    """Yaw filtri (v2 bilan bir xil): burun ko'zlar markazidan uzoq bo'lmasin."""
    left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    eye_cx = (left_eye[0] + right_eye[0]) / 2
    eye_dist = abs(right_eye[0] - left_eye[0])
    if eye_dist < 4:
        return False
    return abs(nose[0] - eye_cx) / eye_dist <= MAX_YAW_RATIO


def _display_crop_b64(frame_bgr, l, t, w, h, pad_ratio=0.4,
                      min_size=220, quality=92) -> str:
    """Ko'rsatish/SKUD rasmi: bbox + atrof, kichigi min_size gacha kattalashadi."""
    H, W = frame_bgr.shape[:2]
    x1, y1, x2, y2 = int(l), int(t), int(l + w), int(t + h)
    px, py = int(w * pad_ratio), int(h * pad_ratio)
    crop = frame_bgr[max(0, y1 - py):min(H, y2 + py),
                     max(0, x1 - px):min(W, x2 + px)]
    if crop.size == 0:
        return ""
    ch, cw = crop.shape[:2]
    m = min(ch, cw)
    if 0 < m < min_size:
        sc = min_size / m
        crop = cv2.resize(crop, (int(cw * sc), int(ch * sc)),
                          interpolation=cv2.INTER_CUBIC)
    ok, jpg = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(jpg).decode("ascii") if ok else ""


def _recog_probe(pad, info, _u):
    """Probe C: RGBA kadr + tracked obj -> align -> ArcFace -> Kafka."""
    buf = info.get_buffer()
    if not buf:
        return Gst.PadProbeReturn.OK
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(buf))
    if not batch_meta:
        return Gst.PadProbeReturn.OK

    now = time.time()
    l_frame = batch_meta.frame_meta_list
    while l_frame is not None:
        frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        sid = frame_meta.source_id
        dets = _kps_store.get((sid, frame_meta.frame_num), [])

        frame_bgr = None  # faqat kerak bo'lganda map qilinadi (CPU tejash)
        pending = []      # (track_id, aligned, bbox)

        n = 0
        l_obj = frame_meta.obj_meta_list
        while l_obj is not None:
            obj = pyds.NvDsObjectMeta.cast(l_obj.data)
            n += 1
            _state["track_ids"].add(obj.object_id)
            r = obj.rect_params
            key = (sid, obj.object_id)

            if now - _last_sent.get(key, 0.0) >= TRACK_SEND_COOLDOWN:
                d = _match_kps(dets, r.left, r.top, r.width, r.height)
                if d is not None:
                    kps = np.asarray(d["kps"], dtype=np.float32)
                    if _is_frontal(kps):
                        if frame_bgr is None:
                            rgba = pyds.get_nvds_buf_surface(
                                hash(buf), frame_meta.batch_id)
                            frame_bgr = np.ascontiguousarray(rgba[:, :, 2::-1])
                        aligned = align(frame_bgr, kps)
                        buf_list = _emb_buffer.setdefault(key, [])
                        buf_list.append(aligned)
                        if len(buf_list) >= EMB_POOL:
                            pending.append(
                                (obj.object_id, list(buf_list),
                                 (r.left, r.top, r.width, r.height)))
                            _emb_buffer[key] = []
                            _last_sent[key] = now
            try:
                l_obj = l_obj.next
            except StopIteration:
                break

        if pending:
            faces = [f for _, pool, _ in pending for f in pool]
            embs = _arcface.get_embeddings(faces)
            cam_id = CAMERA_IDS.get(sid, sid + 1)
            idx = 0
            for tid, pool, (bl, bt, bw, bh) in pending:
                e = embs[idx:idx + len(pool)]
                idx += len(pool)
                avg = e.mean(axis=0)
                nrm = np.linalg.norm(avg)
                if nrm > 0:
                    avg = avg / nrm
                face_b64 = _display_crop_b64(frame_bgr, bl, bt, bw, bh)
                _kafka.send(
                    camera_id=cam_id,
                    frame_id=frame_meta.frame_num,
                    track_id=int(tid),
                    bbox={"x": float(bl), "y": float(bt),
                          "w": float(bw), "h": float(bh)},
                    score=1.0,
                    embedding=avg.tolist(),
                    face_crop=face_b64,
                )
                _state["sent"] += 1

        _state["frames"] += 1
        _state["faces_total"] += n
        f = _state["frames"]
        if f == 1:
            _state["t0"] = time.time()  # fps o'lchovi model yuklashsiz

        # ── MJPEG vizualizatsiya (har manba uchun, har VIS_EVERY-kadrda) ─────
        if VIS_EVERY > 0 and f % VIS_EVERY == 0:
            if frame_bgr is None:
                rgba = pyds.get_nvds_buf_surface(hash(buf), frame_meta.batch_id)
                frame_bgr = np.ascontiguousarray(rgba[:, :, 2::-1])
            _load_names()
            vis = frame_bgr.copy()
            l_obj = frame_meta.obj_meta_list
            while l_obj is not None:
                obj = pyds.NvDsObjectMeta.cast(l_obj.data)
                r = obj.rect_params
                x1, y1 = int(r.left), int(r.top)
                x2, y2 = int(r.left + r.width), int(r.top + r.height)
                info = _names_cache.get(int(obj.object_id))
                if info:
                    nm = info.get("name", "")[:24]
                    sc = info.get("score")
                    label = f"{nm} {sc}%" if sc is not None else nm
                    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 220, 0), 2)
                    fnt = cv2.FONT_HERSHEY_SIMPLEX
                    (tw, th), _b = cv2.getTextSize(label, fnt, 0.55, 1)
                    ty = max(y1 - 4, th + 4)
                    cv2.rectangle(vis, (x1, ty - th - 4),
                                  (x1 + tw + 4, ty + 2), (0, 0, 0), -1)
                    cv2.putText(vis, label, (x1 + 2, ty), fnt, 0.55,
                                (0, 255, 0), 1)
                else:
                    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 200, 255), 2)
                    cv2.putText(vis, f"T{obj.object_id}", (x1, max(y1 - 4, 10)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 1)
                try:
                    l_obj = l_obj.next
                except StopIteration:
                    break
            push_frame(vis, sid)

        if f <= 3 or f % 300 == 0:
            el = time.time() - _state["t0"]
            log.info("frame#%d → %d track | kafka=%d | %.0f fps",
                     f, n, _state["sent"], f / max(el, 0.01))
        try:
            l_frame = l_frame.next
        except StopIteration:
            break
    return Gst.PadProbeReturn.OK


def _cb_demux_pad(demux, pad, parse):
    if "video" in (pad.get_name() or ""):
        sink = parse.get_static_pad("sink")
        if not sink.is_linked():
            pad.link(sink)


def _cb_decoder_pad(decoder, pad, ghost):
    if not ghost.get_target():
        ghost.set_target(pad)


def _make_source_bin(index: int, video_path: str) -> Gst.Bin:
    src_bin = Gst.Bin.new(f"source-bin-{index}")
    filesrc = Gst.ElementFactory.make("filesrc", f"filesrc-{index}")
    demux   = Gst.ElementFactory.make("qtdemux", f"demux-{index}")
    parse   = Gst.ElementFactory.make("h264parse", f"parse-{index}")
    decoder = Gst.ElementFactory.make("nvv4l2decoder", f"dec-{index}")
    filesrc.set_property("location", video_path)
    for el in (filesrc, demux, parse, decoder):
        src_bin.add(el)
    filesrc.link(demux)
    demux.connect("pad-added", _cb_demux_pad, parse)
    parse.link(decoder)
    ghost = Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC)
    src_bin.add_pad(ghost)
    decoder.connect("pad-added", _cb_decoder_pad, ghost)
    static = decoder.get_static_pad("src")
    if static and not ghost.get_target():
        ghost.set_target(static)
    return src_bin


def build_pipeline(video_paths: list):
    Gst.init(None)
    pipeline = Gst.Pipeline()
    loop = GLib.MainLoop()
    n_src = len(video_paths)

    mux = Gst.ElementFactory.make("nvstreammux", "mux")
    mux.set_property("batch-size", n_src)
    mux.set_property("width",  MUX_WIDTH)
    mux.set_property("height", MUX_HEIGHT)
    mux.set_property("batched-push-timeout", 40000)
    mux.set_property("gpu-id", 0)
    # get_nvds_buf_surface uchun unified memory shart (dGPU)
    mux.set_property("nvbuf-memory-type", 3)

    pgie = Gst.ElementFactory.make("nvinfer", "pgie")
    pgie.set_property("config-file-path", PGIE_CFG)
    # Engine qat'iy batch=1 (SCRFD) — nvinfer muxed batch kadrlarini ketma-ket ishlaydi

    tracker = Gst.ElementFactory.make("nvtracker", "tracker")
    tracker.set_property("ll-lib-file", TRACKER_LIB)
    tracker.set_property("ll-config-file", TRACKER_CFG)
    tracker.set_property("tracker-width", 960)
    tracker.set_property("tracker-height", 544)
    tracker.set_property("gpu-id", 0)

    conv = Gst.ElementFactory.make("nvvideoconvert", "conv")
    conv.set_property("nvbuf-memory-type", 3)
    caps = Gst.ElementFactory.make("capsfilter", "caps")
    caps.set_property("caps", Gst.Caps.from_string(
        "video/x-raw(memory:NVMM), format=RGBA"))

    sink = Gst.ElementFactory.make("fakesink", "sink")
    sink.set_property("sync", False)

    for el in (mux, pgie, tracker, conv, caps, sink):
        pipeline.add(el)

    for i, vp in enumerate(video_paths):
        sb = _make_source_bin(i, vp)
        pipeline.add(sb)
        sb.get_static_pad("src").link(mux.request_pad_simple(f"sink_{i}"))

    mux.link(pgie)
    pgie.link(tracker)
    tracker.link(conv)
    conv.link(caps)
    caps.link(sink)

    pgie.get_static_pad("src").add_probe(
        Gst.PadProbeType.BUFFER, _pgie_probe, None)
    caps.get_static_pad("src").add_probe(
        Gst.PadProbeType.BUFFER, _recog_probe, None)

    bus = pipeline.get_bus()
    bus.add_signal_watch()

    def _bus(bus, msg):
        t = msg.type
        if t == Gst.MessageType.EOS:
            log.info("EOS")
            loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            log.error("GStreamer xato: %s — %s", err, dbg)
            loop.quit()
        return True

    bus.connect("message", _bus)
    return pipeline, loop


def main():
    global _arcface, _kafka
    p = argparse.ArgumentParser()
    p.add_argument("--video", nargs="+", required=True,
                   help="Bir yoki bir nechta video (har biri alohida manba)")
    p.add_argument("--max-frames", type=int, default=0)
    args = p.parse_args()

    for vp in args.video:
        if not os.path.exists(vp):
            log.error("Video topilmadi: %s", vp)
            sys.exit(1)

    log.info("B4: multi-source batch pipeline — %d manba", len(args.video))
    log.info("  kafka=%s cam_ids=%s cooldown=%.1fs pool=%d",
             KAFKA_BOOTSTRAP or "OFF", CAMERA_IDS,
             TRACK_SEND_COOLDOWN, EMB_POOL)

    _arcface = ArcFaceRunner(
        os.path.join(MODELS_DIR, "buffalo_l", "w600k_r50.onnx"), gpu_id=GPU_ID)
    _kafka = KafkaClient(KAFKA_BOOTSTRAP, KAFKA_TOPIC)
    if VIS_EVERY > 0:
        mjpeg_start(port=8554)
        log.info("MJPEG vizual: http://localhost:8554/mjpeg/<source>")

    pipeline, loop = build_pipeline(args.video)

    if args.max_frames > 0:
        def _check():
            if _state["frames"] >= args.max_frames:
                loop.quit()
                return False
            return True
        GLib.timeout_add(500, _check)

    pipeline.set_state(Gst.State.PLAYING)
    try:
        loop.run()
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.set_state(Gst.State.NULL)
        _kafka.flush()
        f = _state["frames"]
        el = time.time() - _state["t0"]
        n_src = len(args.video)
        agg = f / max(el, 0.01)
        log.info("=" * 50)
        log.info("YAKUN: kadr=%d | AGG %.0f fps | manba boshiga %.1f fps "
                 "(real-time uchun >=27 kerak) | track/kadr avg=%.1f | "
                 "unique_id=%d | kafka=%d",
                 f, agg, agg / n_src,
                 _state["faces_total"] / max(f, 1),
                 len(_state["track_ids"]), _state["sent"])
        log.info("=" * 50)


if __name__ == "__main__":
    main()
