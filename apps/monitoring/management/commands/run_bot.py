"""
Telegram davomat bot — TUGMALI (inline keyboard), IZOLYATSIYALANGAN.

Davomat pipeline'ga TEGMAYDI:
  - GPU yo'q (faqat DB read + Telegram API)
  - DB read-only (report_service) + faqat BotSentReport'ga write
  - requests yetadi (python-telegram-bot kerak emas)

UX — tugmalar (buyruq yozish shart emas):
  Asosiy menyu: [📅 Bugun] [🏫 Sinflar] [📷 Kameralar]
  Sinflar → har sinf tugma → bosса o'sha sinf hisoboti
  ⬅️ Orqaga — navigatsiya

2 parallel:
  - polling: message + callback_query (tugma bosish)
  - scheduler: dars tugaganда → avtomatik hisobot (har 5 daqiqa)

Ishlatish: python manage.py run_bot
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
    help = "Telegram davomat botini ishga tushiradi (tugmali, read-only)"

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

        logger.info("Bot ishga tushdi (tugmali, admin=%s org=%s)", self.admin_chat, self.org_id)

        stop = threading.Event()
        threading.Thread(target=self._scheduler_loop, args=(stop,), daemon=True, name="bot-scheduler").start()
        try:
            self._polling_loop(stop)
        except KeyboardInterrupt:
            stop.set()
        logger.info("Bot to'xtatildi")

    # ─── Telegram API ──────────────────────────────────────────────────────
    def _post(self, method, payload):
        try:
            return self.session.post(
                _API.format(token=self.token, method=method), json=payload, timeout=20,
            ).json()
        except Exception as e:
            logger.error("%s xato: %s", method, e)
            return {}

    def _send(self, chat_id, text, keyboard=None):
        if not chat_id:
            return
        for chunk in self._split(text, 3800):
            payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"}
            if keyboard:
                payload["reply_markup"] = {"inline_keyboard": keyboard}
            self._post("sendMessage", payload)

    def _edit(self, chat_id, message_id, text, keyboard=None):
        """Tugma bosилganда xabarni O'ZGARTIRADI (yangi xabar emas — toza UX)."""
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text[:3800], "parse_mode": "HTML"}
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        self._post("editMessageText", payload)

    def _answer_cb(self, cb_id):
        self._post("answerCallbackQuery", {"callback_query_id": cb_id})

    @staticmethod
    def _split(text, limit):
        if len(text) <= limit:
            return [text]
        parts, cur = [], ""
        for line in text.split("\n"):
            if len(cur) + len(line) + 1 > limit:
                parts.append(cur); cur = line
            else:
                cur = f"{cur}\n{line}" if cur else line
        if cur:
            parts.append(cur)
        return parts

    def _recipients(self):
        out = []
        if self.admin_chat:
            out.append(self.admin_chat)
        if self.group_chat:
            out.append(self.group_chat)
        return out

    # ─── Tugmalar (inline keyboard) ────────────────────────────────────────
    def _main_menu_kb(self):
        return [
            [{"text": "📅 Bugungi hisobot", "callback_data": "today"}],
            [{"text": "🏫 Sinflar", "callback_data": "classes"},
             {"text": "📷 Kameralar", "callback_data": "cameras"}],
        ]

    def _classes_kb(self):
        from apps.monitoring.services.report_service import get_today_classes
        classes = get_today_classes(self.org_id)
        rows, row = [], []
        for c in classes:
            row.append({"text": c["label"], "callback_data": f"cls:{c['degree']}:{c['name']}"})
            if len(row) == 3:           # 3 ustun
                rows.append(row); row = []
        if row:
            rows.append(row)
        rows.append([{"text": "⬅️ Orqaga", "callback_data": "menu"}])
        return rows

    def _back_kb(self):
        return [[{"text": "⬅️ Asosiy menyu", "callback_data": "menu"}]]

    # ─── Polling ───────────────────────────────────────────────────────────
    def _polling_loop(self, stop):
        offset = 0
        while not stop.is_set():
            try:
                r = self.session.get(
                    _API.format(token=self.token, method="getUpdates"),
                    params={"offset": offset, "timeout": 25}, timeout=30,
                )
                for upd in r.json().get("result", []):
                    offset = upd["update_id"] + 1
                    if "callback_query" in upd:
                        self._handle_callback(upd["callback_query"])
                    elif "message" in upd:
                        self._handle_message(upd["message"])
            except Exception as e:
                logger.error("polling xato: %s", e)
                time.sleep(5)

    def _handle_message(self, msg):
        text = (msg.get("text") or "").strip().lower()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if text.startswith("/start") or text.startswith("/menu"):
            self._send(chat_id,
                       "🤖 <b>225 Maktab — Davomat</b>\n\nKerakli bo'limni tanlang:",
                       keyboard=self._main_menu_kb())
        else:
            self._send(chat_id, "Menyu uchun /start bosing.", keyboard=self._main_menu_kb())

    def _handle_callback(self, cb):
        from apps.monitoring.services.report_service import (
            generate_daily_report, generate_class_today,
        )
        cb_id = cb["id"]
        data = cb.get("data", "")
        msg = cb.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        msg_id = msg.get("message_id")
        self._answer_cb(cb_id)          # tugma "loading" ni to'xtatadi

        if data == "menu":
            self._edit(chat_id, msg_id,
                       "🤖 <b>225 Maktab — Davomat</b>\n\nKerakli bo'limni tanlang:",
                       keyboard=self._main_menu_kb())
        elif data == "today":
            self._edit(chat_id, msg_id, generate_daily_report(organization_id=self.org_id),
                       keyboard=self._back_kb())
        elif data == "classes":
            self._edit(chat_id, msg_id, "🏫 <b>Sinfni tanlang:</b>", keyboard=self._classes_kb())
        elif data.startswith("cls:"):
            _, deg, name = data.split(":", 2)
            self._edit(chat_id, msg_id,
                       generate_class_today(deg, name, organization_id=self.org_id),
                       keyboard=[[{"text": "⬅️ Sinflar", "callback_data": "classes"}],
                                 [{"text": "🏠 Asosiy menyu", "callback_data": "menu"}]])
        elif data == "cameras":
            self._edit(chat_id, msg_id, self._cameras_text(), keyboard=self._back_kb())

    def _cameras_text(self):
        from apps.cameras.models import Camera
        cams = Camera.objects.filter(is_active_stream=True).order_by("id")
        lines = [f"📷 <b>Aktiv kameralar ({cams.count()}):</b>", ""]
        for c in cams:
            lines.append(f"  • cam={c.id} — {c.name}")
        return "\n".join(lines)

    # ─── Scheduler (avtomatik push) ────────────────────────────────────────
    def _scheduler_loop(self, stop):
        stop.wait(30)
        while not stop.is_set():
            try:
                self._push_finished_lessons()
            except Exception as e:
                logger.error("scheduler xato: %s", e)
            stop.wait(300)

    def _push_finished_lessons(self):
        from apps.monitoring.services.report_service import (
            generate_lesson_report, find_unsent_finished_lessons,
        )
        from apps.monitoring.models import BotSentReport

        for sch in find_unsent_finished_lessons(organization_id=self.org_id):
            text = "🔔 <b>Dars tugadi</b>\n\n" + generate_lesson_report(sch)
            for chat in self._recipients():
                self._send(chat, text, keyboard=[[{"text": "📅 Bugungi hisobot", "callback_data": "today"}]])
            BotSentReport.objects.get_or_create(report_type=BotSentReport.TYPE_LESSON, schedule=sch)
            logger.info("Dars hisoboti yuborildi: schedule_id=%s", sch.id)
