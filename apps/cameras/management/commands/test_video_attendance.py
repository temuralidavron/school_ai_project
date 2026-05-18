"""
Video fayl orqali davomat testlash.

Misol:
    python manage.py test_video_attendance \
        --video /path/to/class_video.mp4 \
        --camera-id 5 \
        --org-id 71 \
        --frame-skip 30 \
        --output report.json

    # SKUD ga ham yuborish kerak bo'lsa:
    python manage.py test_video_attendance --video ... --with-skud
"""

import json
import logging
import os
import tempfile
import time

import cv2
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Video fayl orqali davomat testlash — real kamerasiz"

    def add_arguments(self, parser):
        parser.add_argument(
            "--video", required=True,
            help="Video fayl to'liq yo'li (.mp4, .avi, .mkv ...)",
        )
        parser.add_argument(
            "--camera-id", type=int, default=None,
            help="Camera ID (DB da mavjud bo'lishi kerak)",
        )
        parser.add_argument(
            "--org-id", type=int, default=None,
            help="Organization ID",
        )
        parser.add_argument(
            "--frame-skip", type=int, default=30,
            help="Har N-chi kadrni ishlatadi (default 30 = 1 kadr/s @ 30fps)",
        )
        parser.add_argument(
            "--accept-threshold", type=float, default=0.55,
        )
        parser.add_argument(
            "--review-threshold", type=float, default=0.42,
        )
        parser.add_argument(
            "--output", default="test_video_report.json",
            help="JSON hisobot fayli",
        )
        parser.add_argument(
            "--with-skud", action="store_true",
            help="SKUD ga ham yuborsin (default: test rejimida yuborilmaydi)",
        )
        parser.add_argument(
            "--max-frames", type=int, default=0,
            help="Qayta ishlash chegarasi — N ta kadrdan keyin to'xtatadi (0=cheksiz)",
        )

    def handle(self, *args, **options):
        video_path = options["video"]
        camera_id = options["camera_id"]
        org_id = options["org_id"]
        frame_skip = max(1, options["frame_skip"])
        accept_threshold = options["accept_threshold"]
        review_threshold = options["review_threshold"]
        output_path = options["output"]
        with_skud = options["with_skud"]
        max_frames = options["max_frames"]

        if not os.path.exists(video_path):
            self.stderr.write(self.style.ERROR(f"Video fayl topilmadi: {video_path}"))
            return

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            self.stderr.write(self.style.ERROR(f"Video ochmadi: {video_path}"))
            return

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_sec = total_frames / fps if fps > 0 else 0
        expected_processed = total_frames // frame_skip

        self.stdout.write(self.style.HTTP_INFO(
            f"\n{'='*60}\n"
            f"  VIDEO TEST DAVOMATI\n"
            f"{'='*60}\n"
            f"  Fayl       : {video_path}\n"
            f"  FPS        : {fps:.1f}\n"
            f"  Jami kadr  : {total_frames}\n"
            f"  Davomiylik : {duration_sec:.1f}s ({duration_sec/60:.1f} daqiqa)\n"
            f"  Frame-skip : har {frame_skip}-chi → ~{expected_processed} ta kadr\n"
            f"  Camera ID  : {camera_id}\n"
            f"  Org ID     : {org_id}\n"
            f"  Accept     : {accept_threshold}\n"
            f"  Review     : {review_threshold}\n"
            f"  SKUD push  : {'HA' if with_skud else 'YOQ (test rejim)'}\n"
            f"{'='*60}\n"
        ))

        from apps.attendance.services import LiveFrameProcessorService
        processor = LiveFrameProcessorService()

        if not with_skud:
            # SKUD push ni o'chiramiz — test rejimi
            processor.recognition_service._push_to_skud = lambda ev: {"status": "skipped_test"}

        report = {
            "video": video_path,
            "camera_id": camera_id,
            "org_id": org_id,
            "accept_threshold": accept_threshold,
            "review_threshold": review_threshold,
            "frame_skip": frame_skip,
            "fps": round(fps, 2),
            "total_video_frames": total_frames,
            "duration_sec": round(duration_sec, 2),
            "with_skud": with_skud,
            "started_at": timezone.now().isoformat(),
            "frames_processed": 0,
            "recognized": [],
            "reviewed": [],
            "all_events": [],
            "students": [],
            "stats": {},
        }

        frame_num = 0
        processed = 0
        t_start = time.monotonic()
        seen_students: dict[str, dict] = {}

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                frame_num += 1

                if frame_num % frame_skip != 0:
                    continue

                if max_frames and processed >= max_frames:
                    self.stdout.write(f"\n  --max-frames={max_frames} chegarasiga yetdi.")
                    break

                processed += 1
                video_ts = frame_num / fps

                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    tmp_path = tmp.name
                cv2.imwrite(tmp_path, frame)

                try:
                    result = processor.process_frame_image(
                        image_path=tmp_path,
                        organization_id=org_id,
                        camera_id=camera_id,
                        accept_threshold=accept_threshold,
                        review_threshold=review_threshold,
                    )
                except Exception as exc:
                    logger.error("process_frame_image xatosi frame=%d: %s", frame_num, exc)
                    self.stderr.write(f"  [XATO] kadr={frame_num}: {exc}")
                    continue
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

                for r in result.get("results", []):
                    status = r.get("status", "")
                    best = r.get("best_match") or {}
                    pinfl = best.get("pinfl", "")
                    full_name = best.get("full_name", "")
                    sim = best.get("best_score") or 0.0

                    entry = {
                        "frame": frame_num,
                        "video_ts": round(video_ts, 2),
                        "status": status,
                        "pinfl": pinfl,
                        "full_name": full_name,
                        "similarity": round(sim, 4) if sim else None,
                        "bbox": r.get("bbox"),
                        "face_size": r.get("face_size"),
                    }
                    report["all_events"].append(entry)

                    if status == "recorded_and_locked" and pinfl:
                        report["recognized"].append(entry)
                        if pinfl not in seen_students:
                            seen_students[pinfl] = {
                                "pinfl": pinfl,
                                "full_name": full_name,
                                "accepted_count": 0,
                                "best_similarity": 0.0,
                                "first_seen_frame": frame_num,
                                "first_seen_sec": round(video_ts, 1),
                            }
                        seen_students[pinfl]["accepted_count"] += 1
                        seen_students[pinfl]["best_similarity"] = max(
                            seen_students[pinfl]["best_similarity"], sim
                        )
                        self.stdout.write(self.style.SUCCESS(
                            f"  ✓ [{frame_num:5d}/{total_frames}] "
                            f"{video_ts:6.1f}s | {full_name} ({pinfl}) "
                            f"sim={sim:.3f}"
                        ))

                    elif status in ("review_recorded", "review_updated") and pinfl:
                        report["reviewed"].append(entry)
                        self.stdout.write(self.style.WARNING(
                            f"  ? [{frame_num:5d}/{total_frames}] "
                            f"{video_ts:6.1f}s | {full_name} ({pinfl}) "
                            f"sim={sim:.3f} [review]"
                        ))

                if processed % 20 == 0:
                    elapsed = time.monotonic() - t_start
                    speed = processed / elapsed if elapsed > 0 else 0
                    pct = frame_num / total_frames * 100 if total_frames else 0
                    self.stdout.write(
                        f"  ... {frame_num}/{total_frames} kadr ({pct:.0f}%) | "
                        f"tezlik: {speed:.1f} kadr/s | "
                        f"tanildi: {len(seen_students)} ta"
                    )

        finally:
            cap.release()

        elapsed = time.monotonic() - t_start
        report["frames_processed"] = processed
        report["finished_at"] = timezone.now().isoformat()
        report["elapsed_sec"] = round(elapsed, 2)
        report["students"] = list(seen_students.values())
        report["stats"] = {
            "total_video_frames": total_frames,
            "frames_processed": processed,
            "students_recognized": len(seen_students),
            "accepted_events": len(report["recognized"]),
            "review_events": len(report["reviewed"]),
            "elapsed_sec": round(elapsed, 2),
            "avg_frame_per_sec": round(processed / elapsed, 2) if elapsed > 0 else 0,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS("  TEST YAKUNLANDI"))
        self.stdout.write(f"{'='*60}")
        self.stdout.write(f"  Ishlangankadrlar   : {processed} ta")
        self.stdout.write(f"  Tanilgan talabalar : {len(seen_students)} ta")
        self.stdout.write(f"  Accepted events    : {len(report['recognized'])} ta")
        self.stdout.write(f"  Review events      : {len(report['reviewed'])} ta")
        self.stdout.write(f"  Sarflangan vaqt    : {elapsed:.1f}s")

        if seen_students:
            self.stdout.write(f"\n  Tanilgan talabalar:")
            for s in seen_students.values():
                self.stdout.write(
                    f"    ✓ {s['full_name']} ({s['pinfl']}) "
                    f"— sim={s['best_similarity']:.3f}, "
                    f"birinchi {s['first_seen_sec']}s da"
                )
        else:
            self.stdout.write(self.style.WARNING("  Hech kim tanilmadi."))

        self.stdout.write(f"\n  Hisobot saqlandi: {output_path}")
        self.stdout.write(f"{'='*60}\n")
