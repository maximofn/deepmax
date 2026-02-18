"""Telegram channel using aiogram with streaming message edits."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction, ParseMode
from aiogram.types import Message

from deepmax.channels.base import IncomingMessage

if TYPE_CHECKING:
    from deepmax.core.orchestrator import Orchestrator

logger = logging.getLogger(__name__)

MAX_TELEGRAM_LENGTH = 4096
CHUNK_SIZE = 3500
EDIT_INTERVAL = 1.0
TYPING_INTERVAL = 4.0


def chunk_markdown(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """Split text into chunks respecting code fences and line boundaries."""
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    lines = text.split("\n")
    current: list[str] = []
    current_len = 0
    in_code_block = False
    code_fence = ""

    for line in lines:
        line_len = len(line) + 1  # +1 for newline

        # Track code fence state
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_fence = "```"
            elif stripped == "```" or stripped.startswith("```"):
                in_code_block = False
                code_fence = ""

        # Would this line exceed the limit?
        if current_len + line_len > size and current:
            chunk_text = "\n".join(current)
            if in_code_block:
                # Close the code block in current chunk
                chunk_text += "\n```"
            chunks.append(chunk_text)

            current = []
            current_len = 0
            if in_code_block:
                # Reopen code block in next chunk
                current.append(code_fence)
                current_len = len(code_fence) + 1

        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks


class TelegramStreamBuffer:
    """Accumulates tokens and periodically edits a Telegram message."""

    def __init__(self, bot: Bot, chat_id: int) -> None:
        self.bot = bot
        self.chat_id = chat_id
        self._buffer = ""
        self._message: Message | None = None
        self._last_edit_len = 0
        self._edit_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    async def add_token(self, token: str) -> None:
        async with self._lock:
            self._buffer += token
            if self._edit_task is None or self._edit_task.done():
                self._edit_task = asyncio.create_task(self._schedule_edit())

    async def _schedule_edit(self) -> None:
        await asyncio.sleep(EDIT_INTERVAL)
        await self._do_edit()

    async def _do_edit(self) -> None:
        async with self._lock:
            text = self._buffer
            if not text or len(text) == self._last_edit_len:
                return

            try:
                if self._message is None:
                    self._message = await self.bot.send_message(
                        self.chat_id, text[:MAX_TELEGRAM_LENGTH]
                    )
                else:
                    # Only edit if text actually changed
                    await self._message.edit_text(text[:MAX_TELEGRAM_LENGTH])
                self._last_edit_len = len(text)
            except Exception:
                # Telegram may reject edits if text hasn't changed enough
                pass

    async def finalize(self) -> None:
        """Send the final complete response, chunked if needed."""
        if self._edit_task and not self._edit_task.done():
            self._edit_task.cancel()
            try:
                await self._edit_task
            except asyncio.CancelledError:
                pass

        text = self._buffer
        if not text:
            return

        chunks = chunk_markdown(text)

        try:
            if self._message is not None and len(chunks) == 1:
                # Edit existing message with final text
                await self._message.edit_text(chunks[0])
            else:
                # Delete the partial message and send chunked
                if self._message is not None:
                    try:
                        await self._message.delete()
                    except Exception:
                        pass
                for chunk in chunks:
                    await self.bot.send_message(self.chat_id, chunk)
        except Exception:
            logger.exception("Error finalizing telegram message for chat %d", self.chat_id)


class TelegramChannel:
    """Telegram bot channel with streaming edits and typing indicators."""

    name: str = "telegram"

    def __init__(self, allowed_users: list[int] | None = None) -> None:
        self.allowed_users = set(allowed_users or [])
        self._bot: Bot | None = None
        self._dp: Dispatcher | None = None
        self._orchestrator: Orchestrator | None = None
        self._buffers: dict[int, TelegramStreamBuffer] = {}
        self._shutdown_event: asyncio.Event | None = None

    @property
    def max_message_length(self) -> int:
        return MAX_TELEGRAM_LENGTH

    async def start(self, orchestrator: Orchestrator, shutdown_event: asyncio.Event) -> None:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            logger.error("TELEGRAM_BOT_TOKEN not set, Telegram channel disabled")
            return

        self._orchestrator = orchestrator
        self._shutdown_event = shutdown_event
        self._bot = Bot(token=token, default=DefaultBotProperties(parse_mode=None))
        self._dp = Dispatcher()

        @self._dp.message(F.text)
        async def on_message(message: Message) -> None:
            if not message.from_user or not message.text:
                return

            user_id = message.from_user.id

            # Access control: silently ignore unauthorized users
            if self.allowed_users and user_id not in self.allowed_users:
                return

            msg = IncomingMessage(
                channel="telegram",
                channel_uid=str(user_id),
                text=message.text,
            )
            await orchestrator.handle_message(msg, self)

        logger.info("Starting Telegram polling")
        await self._dp.start_polling(self._bot, handle_signals=False)

    async def stop(self) -> None:
        if self._dp:
            await self._dp.stop_polling()
        if self._bot:
            await self._bot.session.close()
        logger.info("Telegram channel stopped")

    async def send_token(self, channel_uid: str, token: str) -> None:
        chat_id = int(channel_uid)
        if chat_id not in self._buffers:
            self._buffers[chat_id] = TelegramStreamBuffer(self._bot, chat_id)
        await self._buffers[chat_id].add_token(token)

    async def flush(self, channel_uid: str) -> None:
        chat_id = int(channel_uid)
        buf = self._buffers.pop(chat_id, None)
        if buf:
            await buf.finalize()

    async def send_typing(self, channel_uid: str) -> None:
        if self._bot is None:
            return
        try:
            await self._bot.send_chat_action(int(channel_uid), ChatAction.TYPING)
        except Exception:
            pass

    async def send_text(self, channel_uid: str, text: str) -> None:
        if self._bot is None:
            return
        chunks = chunk_markdown(text)
        for chunk in chunks:
            try:
                await self._bot.send_message(int(channel_uid), chunk)
            except Exception:
                logger.exception("Error sending message to chat %s", channel_uid)
