from __future__ import annotations

import asyncio
import logging
import random
from datetime import timedelta
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, RetryAfter
from telegram.ext import Application, CommandHandler, ContextTypes, filters

from vintedbot.commands import HELP, Commands
from vintedbot.config import Settings
from vintedbot.monitor import Monitor
from vintedbot.storage import Search, Storage
from vintedbot.vinted.client import VintedClient
from vintedbot.vinted.models import Item

log = logging.getLogger(__name__)

MAX_TITLE = 200
SEEN_RETENTION_S = 30 * 86400


def format_caption(search: Search, item: Item) -> str:
    title = item.title if len(item.title) <= MAX_TITLE else item.title[: MAX_TITLE - 1] + "…"
    price = f"💶 {escape(item.price)} {escape(item.currency)}".rstrip()
    if item.total_price and item.total_price != item.price:
        price += f" ({escape(item.total_price)} {escape(item.currency)} c/ proteção)"
    lines = [f"<b>{escape(title)}</b>", price]
    details = " · ".join(part for part in (item.brand, item.size) if part)
    if details:
        lines.append(escape(details))
    if item.country:
        lines.append(f"📍 {escape(item.country)}")
    lines.append(f"🔎 {escape(search.name)}")
    return "\n".join(lines)


async def _with_flood_retry(send, **kwargs) -> None:
    try:
        await send(**kwargs)
    except RetryAfter as exc:
        delay = exc.retry_after
        if isinstance(delay, timedelta):
            delay = delay.total_seconds()
        log.warning("Telegram pediu para esperar %ss; a repetir", delay)
        await asyncio.sleep(float(delay) + 1)
        await send(**kwargs)


class TelegramNotifier:
    def __init__(self, bot) -> None:
        self._bot = bot

    async def send_item(self, chat_id: int, search: Search, item: Item) -> None:
        caption = format_caption(search, item)
        markup = (
            InlineKeyboardMarkup([[InlineKeyboardButton("Abrir na Vinted", url=item.url)]]) if item.url else None
        )
        if item.photo_url:
            try:
                await _with_flood_retry(
                    self._bot.send_photo,
                    chat_id=chat_id,
                    photo=item.photo_url,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return
            except BadRequest:
                log.warning("Telegram rejeitou a foto do artigo %s; a enviar só texto", item.id)
        await _with_flood_retry(
            self._bot.send_message, chat_id=chat_id, text=caption, parse_mode=ParseMode.HTML, reply_markup=markup
        )

    async def send_text(self, chat_id: int, text: str) -> None:
        await _with_flood_retry(self._bot.send_message, chat_id=chat_id, text=text)


def build_application(settings: Settings, storage: Storage, client: VintedClient) -> Application:
    async def on_shutdown(_app: Application) -> None:
        await client.close()
        storage.close()

    app = Application.builder().token(settings.telegram_token).post_shutdown(on_shutdown).build()
    monitor = Monitor(storage, client, TelegramNotifier(app.bot))
    commands = Commands(storage, monitor, poll_interval=settings.poll_interval)
    if settings.allowed_chat_id is None:
        log.warning("ALLOWED_CHAT_ID não definido: envia /id ao bot e põe o valor no .env")
    allowed = filters.Chat(chat_id=[] if settings.allowed_chat_id is None else [settings.allowed_chat_id])

    async def reply(update: Update, text: str) -> None:
        await update.effective_message.reply_text(text)

    async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, HELP)

    async def on_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, f"O teu chat id é {update.effective_chat.id}")

    async def on_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, await commands.add(update.effective_chat.id, context.args))

    async def on_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.list(update.effective_chat.id))

    async def on_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.remove(update.effective_chat.id, context.args))

    async def on_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.set_active(update.effective_chat.id, context.args, False))

    async def on_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.set_active(update.effective_chat.id, context.args, True))

    async def on_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await reply(update, commands.status(update.effective_chat.id))

    app.add_handler(CommandHandler("id", on_id))
    app.add_handler(CommandHandler(["start", "help"], on_start, filters=allowed))
    app.add_handler(CommandHandler("add", on_add, filters=allowed))
    app.add_handler(CommandHandler("list", on_list, filters=allowed))
    app.add_handler(CommandHandler("remove", on_remove, filters=allowed))
    app.add_handler(CommandHandler("pause", on_pause, filters=allowed))
    app.add_handler(CommandHandler("resume", on_resume, filters=allowed))
    app.add_handler(CommandHandler("status", on_status, filters=allowed))

    jitter_s = min(30.0, settings.poll_interval * 0.25)

    async def poll_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        await asyncio.sleep(random.uniform(0, jitter_s))
        await monitor.run_cycle()

    async def purge_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        removed = storage.purge_seen(SEEN_RETENTION_S)
        log.info("Limpeza: %s artigos vistos antigos removidos", removed)

    app.job_queue.run_repeating(
        poll_job,
        interval=settings.poll_interval,
        first=10,
        name="poll",
        job_kwargs={"max_instances": 1, "coalesce": True},
    )
    app.job_queue.run_repeating(purge_job, interval=86400, first=60, name="purge")
    return app
