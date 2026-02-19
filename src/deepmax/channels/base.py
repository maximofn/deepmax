"""Shared data models and channel protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import asyncio

    from deepmax.core.orchestrator import Orchestrator


@dataclass(frozen=True)
class IncomingMessage:
    """A normalized message from any channel."""

    channel: str
    channel_uid: str
    text: str


@dataclass(frozen=True)
class User:
    name: str


@dataclass
class Conversation:
    thread_id: str
    title: str | None
    model: str
    system_prompt: str | None
    is_active: bool
    created_at: str  # ISO 8601


@runtime_checkable
class Channel(Protocol):
    """Interface that every channel adapter must implement."""

    name: str

    async def start(self, orchestrator: Orchestrator, shutdown_event: asyncio.Event) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def send_token(self, channel_uid: str, token: str) -> None:
        ...

    async def flush(self, channel_uid: str) -> None:
        ...

    async def send_typing(self, channel_uid: str) -> None:
        ...

    async def send_text(self, channel_uid: str, text: str) -> None:
        ...

    @property
    def max_message_length(self) -> int:
        ...


def parse_slash_command(text: str) -> tuple[str, str] | None:
    """Parse a slash command from text. Returns (command, args) or None."""
    text = text.strip()
    if not text.startswith("/"):
        return None
    parts = text.split(None, 1)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    return command, args
