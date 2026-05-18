"""
Kamera patrul (aylanish) tizimi — 3 nomli rejim.

Rejimlar (Camera.patrol_mode yoki settings.PATROL_MODE):
    "off"     — aylanmaydi (statik)
    "preset"  — CameraPatrolPoint ONVIF preset tokenlari bo'ylab
    "sweep"   — patrol_pan_min..patrol_pan_max avtomatik gradus sweep
    "hybrid"  — preset bor bo'lsa preset, yo'q bo'lsa sweep

Deploy paytida tanlash:
    1) Global: .env da PATROL_MODE=preset|sweep|hybrid|off
    2) Har kamera: Camera.patrol_mode (admin/DB) — "default" bo'lsa global ishlatiladi

Arxitektura:
    Stream thread (CameraStreamService) frame o'qiydi va yuz taniydi.
    PatrolService alohida thread — kamerani nuqtadan nuqtaga ko'chiradi.
    Ko'chish paytida blur → kod skipped_blurry bilan tashlaydi.
    Nuqtada dwell_seconds davomida kamera qotadi → AI taniydi.
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


# ─── Bitta patrul pozitsiyasi ─────────────────────────────────────────────────

@dataclass
class PatrolPosition:
    label: str
    dwell: float
    move: Callable  # move(ptz_service) -> None


# ─── Strategiyalar ────────────────────────────────────────────────────────────

class BasePatrolStrategy:
    name = "base"

    def __init__(self, camera):
        self.camera = camera

    def positions(self) -> list[PatrolPosition]:
        """Aylanish nuqtalari ro'yxati (bir tsikl)."""
        raise NotImplementedError

    def is_usable(self) -> bool:
        """Bu strategiya shu kamera uchun ishlay oladimi."""
        return bool(self.positions())


class PresetPatrolStrategy(BasePatrolStrategy):
    """'preset' — CameraPatrolPoint preset tokenlari bo'ylab aylanadi."""
    name = "preset"

    def positions(self) -> list[PatrolPosition]:
        points = list(self.camera.patrol_points.all().order_by("order"))
        result = []
        default_dwell = self.camera.patrol_dwell_seconds
        for p in points:
            token = p.preset_token
            dwell = p.dwell_seconds if p.dwell_seconds else default_dwell
            result.append(PatrolPosition(
                label=p.label or f"preset:{token}",
                dwell=dwell,
                move=lambda ptz, t=token: ptz.goto_preset(t),
            ))
        return result


class SweepPatrolStrategy(BasePatrolStrategy):
    """'sweep' — pan_min..pan_max oralig'ida patrol_steps nuqta, avtomatik."""
    name = "sweep"

    def positions(self) -> list[PatrolPosition]:
        cam = self.camera
        steps = max(2, cam.patrol_steps)
        pan_min = cam.patrol_pan_min
        pan_max = cam.patrol_pan_max
        tilt = cam.patrol_tilt
        zoom = cam.patrol_zoom
        dwell = cam.patrol_dwell_seconds

        result = []
        for i in range(steps):
            frac = i / (steps - 1)
            pan = pan_min + (pan_max - pan_min) * frac
            result.append(PatrolPosition(
                label=f"sweep:{pan:+.2f}",
                dwell=dwell,
                move=lambda ptz, p=pan: ptz.absolute_move(p, tilt, zoom),
            ))
        return result


class HybridPatrolStrategy(BasePatrolStrategy):
    """'hybrid' — preset nuqta bor bo'lsa preset, aks holda sweep."""
    name = "hybrid"

    def __init__(self, camera):
        super().__init__(camera)
        self._preset = PresetPatrolStrategy(camera)
        self._sweep = SweepPatrolStrategy(camera)
        self._delegate = (
            self._preset if self.camera.patrol_points.exists() else self._sweep
        )

    def positions(self) -> list[PatrolPosition]:
        return self._delegate.positions()


_STRATEGY_MAP = {
    "preset": PresetPatrolStrategy,
    "sweep": SweepPatrolStrategy,
    "hybrid": HybridPatrolStrategy,
}


def resolve_patrol_mode(camera) -> str:
    """Camera.patrol_mode 'default' bo'lsa global settings.PATROL_MODE."""
    from django.conf import settings
    mode = (camera.patrol_mode or "default").lower()
    if mode == "default":
        mode = getattr(settings, "PATROL_MODE", "off").lower()
    return mode


def get_patrol_strategy(camera) -> BasePatrolStrategy | None:
    """Kamera uchun strategiya obyekti yoki None (off / nuqta yo'q)."""
    mode = resolve_patrol_mode(camera)
    if mode == "off":
        return None
    cls = _STRATEGY_MAP.get(mode)
    if cls is None:
        logger.warning("cam=%s noma'lum patrol_mode=%s — off", camera.id, mode)
        return None
    strat = cls(camera)
    if not strat.is_usable():
        logger.warning(
            "cam=%s patrol_mode=%s lekin nuqta yo'q — aylanmaydi", camera.id, mode
        )
        return None
    return strat


# ─── Patrul thread ────────────────────────────────────────────────────────────

class PatrolService:
    """
    Bitta kamerani patrul qiladi. Alohida thread da run() chaqiriladi.
    Stream thread bilan parallel ishlaydi — bir-biriga bog'liq emas.
    """

    def __init__(self, camera):
        self.camera = camera

    def _lesson_active(self) -> bool:
        """Hozir shu kamerada aktiv dars bormi (schedule asosida)."""
        from apps.attendance.services import _get_cached_schedule
        return _get_cached_schedule(self.camera.id) is not None

    def _go_home(self, ptz):
        """Dars yo'q paytda home preset ga qaytadi (bor bo'lsa)."""
        token = self.camera.ptz_preset_token
        if token:
            try:
                ptz.goto_preset(token)
                logger.debug("cam=%s home preset=%s", self.camera.id, token)
            except Exception as e:
                logger.warning("cam=%s home preset xato: %s", self.camera.id, e)

    def run(self, stop_event: threading.Event):
        from django.conf import settings
        from apps.cameras.ptz_service import PtzService

        strategy = get_patrol_strategy(self.camera)
        if strategy is None:
            logger.info("cam=%s patrul o'chiq — thread tugadi", self.camera.id)
            return

        only_lesson = getattr(settings, "PATROL_ONLY_DURING_LESSON", True)
        ptz = PtzService(self.camera)

        logger.info(
            "Patrul boshlandi: cam=%s rejim=%s nuqta=%d only_lesson=%s",
            self.camera.id, strategy.name, len(strategy.positions()), only_lesson,
        )

        was_home = False
        while not stop_event.is_set():
            # Dars vaqti tekshiruvi
            if only_lesson and not self._lesson_active():
                if not was_home:
                    self._go_home(ptz)
                    was_home = True
                stop_event.wait(timeout=30.0)
                continue
            was_home = False

            positions = strategy.positions()
            if not positions:
                stop_event.wait(timeout=30.0)
                continue

            for pos in positions:
                if stop_event.is_set():
                    break
                if only_lesson and not self._lesson_active():
                    break
                try:
                    pos.move(ptz)
                except Exception as e:
                    logger.error("cam=%s patrul move(%s) xato: %s",
                                 self.camera.id, pos.label, e)
                    stop_event.wait(timeout=10.0)
                    continue
                # Nuqtada qotib turish — AI shu paytda yuz taniydi
                logger.debug("cam=%s patrul nuqta=%s dwell=%.1fs",
                             self.camera.id, pos.label, pos.dwell)
                stop_event.wait(timeout=pos.dwell)

        try:
            ptz.stop()
        except Exception:
            pass
        logger.info("Patrul to'xtatildi: cam=%s", self.camera.id)
