"""
Telegram davomat bot — ALOHIDA konteyner, davomat pipeline'ga TEGMAYDI.

Izolyatsiya:
  - GPU ishlatmaydi (faqat DB read + Telegram API)
  - DB faqat O'QIYDI (report_service), BotSentReport'gagina yozadi
  - python-telegram-bot kutubxonasi kerak emas (requests yetadi)

2 parallel vazifa:
  - polling: admin buyruqlari (/bugun, /sinf, /kamera, /start)
  - scheduler: tugagan dars → avtomatik hisobot (har 5 daqiqa)

Ishlatish:
    python manage.py run_bot
"""
import logging
import threading
import time

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger("apps.monitoring.bot")

_API = "https://api.telegram.org/bot{token}/{method}"


class Command(BaseCommand):
    help = "Telegram davomat botini ishga tushiradi (alohida, read-only)"

    def handle(self, *args, **options):
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
        if not token:
            self.stderr.write("TELEGRAM_BOT_TOKEN .env da yo'q")
            return

        self.token = token
        self.admin_chat = str(getattr(settings, "TELEGRAM_ADMIN_CHAT_ID", "") or "")
        self.group_chat = str(getattr(settings, "TELEGRAM_GROUP_CHAT_ID", "") or "")
        self.org_id = getattr(settings, "BOT_ORG_ID", None)
        self.session = requests.Session()

        logger.info("Bot ishga tushdi (admin=%s group=%s org=%s)",
                    self.admin_chat, self.group_chat or "—", self.org_id)

        stop = threading.Event()
        t_sched = threading.Thread(target=self._scheduler_loop, args=(stop,), daemon=True, name="bot-scheduler")
        t_sched.start()

        try:
            self._polling_loop(stop)
        except KeyboardInterrupt:
            stop.set()
        logger.info("Bot to'xtatildi")

    # ─── Telegram API ──────────────────────────────────────────────────────
    def _send(self, chat_id, text):
        """HTML xabar yuboradi (4096 belgi cheklovi — bo'lib yuboradi)."""
        if not chat_id:
            return
        for chunk in self._split(text, 4000):
            try:
                self.session.post(
                    _API.format(token=self.token, method="sendMessage"),
                    json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
                    timeout=20,
                )
            except Exception as e:
                logger.error("sendMessage xato: %s", e)

    @staticmethod
    def _split(text, limit):
        if len(text) <= limit:
            return [text]
        parts, cur = [], ""
        for line in text.split("\n"):
            if len(cur) + len(line) + 1 > limit:
                parts.append(cur)
                cur = line
            else:
                cur = f"{cur}\n{line}" if cur else line
        if cur:
            parts.append(cur)
        return parts

    def _recipients(self):
        """Hisobot kimga: admin + (bo'lsa) guruh."""
        out = []
        if self.admin_chat:
            out.append(self.admin_chat)
        if self.group_chat:
            out.append(self.group_chat)
        return out

    # ─── Polling (buyruqlar) ───────────────────────────────────────────────
    def _polling_loop(self, stop):
        offset = 0
        while not stop.is_set():
            try:
                r = self.session.get(
                    _API.format(token=self.token, method="getUpdates"),
                    params={"offset": offset, "timeout": 25},
                    timeout=30,
                )
                data = r.json()
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    self._handle_update(upd)
            except Exception as e:
                logger.error("polling xato: %s", e)
                time.sleep(5)

    def _handle_update(self, upd):
        msg = upd.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if not text:
            return

        cmd = text.split()[0].lower().lstrip("/").split("@")[0]
        arg = text[len(text.split()[0]):].strip()

        if cmd == "start":
            self._send(chat_id,
                       f"🤖 Davomat bot.\nSizning chat_id: <code>{chat_id}</code>\n\n"
                       "Buyruqlar:\n/bugun — kunlik hisobot\n/sinf 9A — sinf holati\n/kamera — kamera holati")
        elif cmd == "bugun":
            self._cmd_today(chat_id)
        elif cmd == "sinf":
            self._cmd_class(chat_id, arg)
        elif cmd == "kamera":
            self._cmd_cameras(chat_id)

    def _cmd_today(self, chat_id):
        from apps.monitoring.services.report_service import generate_daily_report
        self._send(chat_id, generate_daily_report(organization_id=self.org_id))

    def _cmd_class(self, chat_id, arg):
        from apps.monitoring.services.report_service import generate_lesson_report
        from apps.integrations.models import ExternalSchedule
        from django.utils import timezone
        from zoneinfo import ZoneInfo
        if not arg:
            self._send(chat_id, "Sinf nomini yozing: /sinf 9A")
            return
        today = timezone.now().astimezone(ZoneInfo("Asia/Tashkent")).date()
        # arg "9A" → degree=9, name=A (oddiy parse)
        deg = "".join(c for c in arg if c.isdigit())
        name = "".join(c for c in arg if c.isalpha()).upper()
        scheds = ExternalSchedule.objects.filter(
            date=today,
            class_obj__class_degree=deg or None,
            class_obj__class_name__iexact=name,
        ).select_related("class_obj").order_by("start_at")
        if self.org_id:
            scheds = scheds.filter(organization__organization_id=self.org_id)
        scheds = list(scheds)
        if not scheds:
            self._send(chat_id, f"{arg} uchun bugun dars topilmadi.")
            return
        for s in scheds:
            self._send(chat_id, generate_lesson_report(s))

    def _cmd_cameras(self, chat_id):
        from apps.cameras.models import Camera
        cams = Camera.objects.filter(is_active_stream=True).order_by("id")
        lines = [f"📷 <b>Kameralar ({cams.count()} aktiv):</b>"]
        for c in cams:
            lines.append(f"  • cam={c.id} {c.name}")
        self._send(chat_id, "\n".join(lines))

    # ─── Scheduler (avtomatik push) ────────────────────────────────────────
    def _scheduler_loop(self, stop):
        # Ishga tushganда darrov emas, 30s keyin (warmup)
        stop.wait(30)
        while not stop.is_set():
            try:
                self._push_finished_lessons()
            except Exception as e:
                logger.error("scheduler xato: %s", e)
            stop.wait(300)  # har 5 daqiqa

    def _push_finished_lessons(self):
        from apps.monitoring.services.report_service import (
            generate_lesson_report, find_unsent_finished_lessons,
        )
        from apps.monitoring.models import BotSentReport

        lessons = find_unsent_finished_lessons(organization_id=self.org_id)
        for sch in lessons:
            text = generate_lesson_report(sch)
            for chat in self._recipients():
                self._send(chat, text)
            # Yuborildi deb belgilash (takror yo'q) — bot FAQAT shu jadvalga yozadi
            BotSentReport.objects.get_or_create(
                report_type=BotSentReport.TYPE_LESSON,
                schedule=sch,
            )
            logger.info("Dars hisoboti yuborildi: schedule_id=%s", sch.id)
