"""Terminal channel using prompt_toolkit for async input."""

from __future__ import annotations

import asyncio
import logging
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from deepmax.channels.base import IncomingMessage

logger = logging.getLogger(__name__)


class TerminalChannel:
    """Interactive terminal channel with streaming token output."""

    name: str = "terminal"

    def __init__(self, user_name: str = "user") -> None:
        self.user_name = user_name
        self._session: PromptSession | None = None

    @property
    def max_message_length(self) -> int:
        return 100_000

    async def start(self, orchestrator, shutdown_event: asyncio.Event) -> None:
        self._session = PromptSession()
        prompt = f"{self.user_name}> "

        with patch_stdout():
            while not shutdown_event.is_set():
                try:
                    text = await self._session.prompt_async(prompt)
                except (EOFError, KeyboardInterrupt):
                    shutdown_event.set()
                    break

                text = text.strip()
                if not text:
                    continue

                msg = IncomingMessage(channel="terminal", channel_uid="local", text=text)
                await orchestrator.handle_message(msg, self)

    async def stop(self) -> None:
        logger.info("Terminal channel stopped")

    async def send_token(self, channel_uid: str, token: str) -> None:
        sys.stdout.write(token)
        sys.stdout.flush()

    async def flush(self, channel_uid: str) -> None:
        sys.stdout.write("\n")
        sys.stdout.flush()

    async def send_typing(self, channel_uid: str) -> None:
        pass  # No typing indicator in terminal

    async def send_text(self, channel_uid: str, text: str) -> None:
        print(text)
