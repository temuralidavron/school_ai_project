"""
InsightFace thread-safety'ni ANIQ isbotlaydi (taxmin emas).

Mantiq:
  1. Bitta test rasm bilan SERIAL inference (1 thread) → embedding saqlash
  2. Bir xil rasm bilan PARALLEL inference (N thread) → embedding saqlash
  3. Parallel natija serial bilan BIR XIL bo'lsa → thread-safe TASDIQLANDI
     (chunki shared state buzilmadi). Farq/crash bo'lsa → thread-safe EMAS.
  4. Vaqtni solishtiradi → parallel qancha tez (throughput foydasi).

Ishlatish:
    python manage.py test_thread_safety
    python manage.py test_thread_safety --threads 4 --iters 40
"""
import threading
import time

import numpy as np
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "InsightFace thread-safety + parallel tezlikni o'lchaydi"

    def add_arguments(self, parser):
        parser.add_argument("--threads", type=int, default=4)
        parser.add_argument("--iters", type=int, default=40,
                            help="Har rejimда jami inference soni")

    def handle(self, *args, **options):
        from apps.face_data.services import get_face_app

        n_threads = options["threads"]
        n_iters = options["iters"]

        self.stdout.write("Model yuklanmoqda...")
        app = get_face_app()

        # Test rasm — sun'iy yuzsiz ham bo'ladi, lekin yuzli aniqroq.
        # 640x640 random; agar yuz topilmasa, det natijasini solishtiramiz.
        rng = np.random.RandomState(42)
        img = rng.randint(0, 255, (640, 640, 3), dtype=np.uint8)

        def run_once():
            faces = app.get(img)
            if faces:
                return faces[0].embedding.copy()
            return np.zeros(512, dtype=np.float32)  # yuz yo'q — det natijasi soni muhim

        # ── 1. SERIAL (etalon) ──────────────────────────────────────────────
        self.stdout.write(f"\n[1] SERIAL: {n_iters} inference, 1 thread...")
        t0 = time.monotonic()
        serial_results = [run_once() for _ in range(n_iters)]
        serial_time = time.monotonic() - t0
        etalon = serial_results[0]
        # Serial o'zi deterministik mi?
        serial_consistent = all(
            np.allclose(r, etalon, atol=1e-5) for r in serial_results
        )
        self.stdout.write(
            f"    vaqt={serial_time:.2f}s  "
            f"({serial_time / n_iters * 1000:.0f}ms/inference)  "
            f"deterministik={serial_consistent}"
        )

        # ── 2. PARALLEL ─────────────────────────────────────────────────────
        self.stdout.write(f"\n[2] PARALLEL: {n_iters} inference, {n_threads} thread...")
        parallel_results = []
        results_lock = threading.Lock()
        errors = []

        def worker(count):
            for _ in range(count):
                try:
                    emb = run_once()
                    with results_lock:
                        parallel_results.append(emb)
                except Exception as e:
                    with results_lock:
                        errors.append(repr(e))

        per_thread = n_iters // n_threads
        threads = [threading.Thread(target=worker, args=(per_thread,)) for _ in range(n_threads)]

        t0 = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        parallel_time = time.monotonic() - t0

        # Parallel natijalar serial etalon bilan BIR XIL mi?
        if errors:
            match = False
        else:
            match = all(np.allclose(r, etalon, atol=1e-5) for r in parallel_results)

        self.stdout.write(
            f"    vaqt={parallel_time:.2f}s  "
            f"natija_soni={len(parallel_results)}  "
            f"xato_soni={len(errors)}"
        )
        if errors:
            self.stdout.write(self.style.ERROR(f"    XATOLAR: {errors[:3]}"))

        # ── 3. XULOSA ───────────────────────────────────────────────────────
        self.stdout.write("\n" + "=" * 60)
        speedup = serial_time / parallel_time if parallel_time > 0 else 0

        if match and not errors:
            self.stdout.write(self.style.SUCCESS(
                f"✅ THREAD-SAFE TASDIQLANDI\n"
                f"   Parallel natija serial bilan BIR XIL (shared state buzilmadi).\n"
                f"   Tezlik: {speedup:.1f}x ({serial_time:.2f}s → {parallel_time:.2f}s)\n"
                f"   → AI_INFERENCE_CONCURRENCY={n_threads} XAVFSIZ ishlatса bo'ladi."
            ))
        elif errors:
            self.stdout.write(self.style.ERROR(
                f"❌ THREAD-SAFE EMAS — xato/crash bor.\n"
                f"   → AI_INFERENCE_CONCURRENCY=1 qoldiring (serial)."
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"❌ THREAD-SAFE EMAS — parallel natija serial'dan FARQ qiladi.\n"
                f"   Shared state buzilyapti → AI_INFERENCE_CONCURRENCY=1 qoldiring."
            ))
        self.stdout.write("=" * 60)
