"""Cross-channel identity resolution and conversation management.

Identity is resolved from config.toml (dict lookup).
Conversations are persisted in a JSON file with atomic writes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from deepmax.channels.base import Conversation, User
from deepmax.config import AppConfig

logger = logging.getLogger(__name__)


class IdentityService:
    """Resolves channel-specific UIDs to canonical users and manages conversations."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._lock = asyncio.Lock()

        # Build reverse lookup: (channel, uid) -> user_name
        self._identity_map: dict[tuple[str, str], str] = {}
        for user_name, link in config.identity.links.items():
            if link.terminal is not None:
                self._identity_map[("terminal", link.terminal)] = user_name
            if link.telegram is not None:
                self._identity_map[("telegram", link.telegram)] = user_name

        # Data file path
        self._data_dir = Path(config.storage.data_dir)
        self._data_path = self._data_dir / "conversations.json"

        logger.info(
            "IdentityService initialized with %d identity mappings", len(self._identity_map)
        )

    def resolve(self, channel: str, channel_uid: str) -> User | None:
        """Resolve a channel identity to a canonical user (synchronous dict lookup)."""
        user_name = self._identity_map.get((channel, channel_uid))
        if user_name is None:
            return None
        return User(name=user_name)

    async def get_active_conversation(self) -> Conversation | None:
        """Get the current active conversation."""
        convs = await self._load()
        for c in convs:
            if c["is_active"]:
                return _dict_to_conversation(c)
        return None

    async def get_or_create_active_conversation(
        self, model: str, system_prompt: str | None
    ) -> Conversation:
        """Get the active conversation or create one if none exists."""
        conv = await self.get_active_conversation()
        if conv is not None:
            return conv
        return await self.create_conversation(model, system_prompt)

    async def create_conversation(
        self, model: str, system_prompt: str | None
    ) -> Conversation:
        """Create a new conversation, deactivating any current one."""
        thread_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        async with self._lock:
            convs = await self._load()
            # Deactivate all active conversations
            for c in convs:
                c["is_active"] = False
            # Add new conversation
            new_conv = {
                "thread_id": thread_id,
                "title": None,
                "model": model,
                "system_prompt": system_prompt,
                "is_active": True,
                "created_at": now,
            }
            convs.append(new_conv)
            await self._save(convs)

        conv = _dict_to_conversation(new_conv)
        logger.info("Created conversation (thread=%s)", thread_id)
        return conv

    async def switch_conversation(self, thread_id_prefix: str) -> Conversation | None:
        """Switch to a different conversation by thread_id prefix."""
        async with self._lock:
            convs = await self._load()
            # Find matching conversation
            target = None
            for c in convs:
                if c["thread_id"].startswith(thread_id_prefix):
                    target = c
                    break
            if target is None:
                return None
            # Deactivate all, activate target
            for c in convs:
                c["is_active"] = False
            target["is_active"] = True
            await self._save(convs)

        return _dict_to_conversation(target)

    async def update_conversation_model(self, thread_id: str, model: str) -> None:
        async with self._lock:
            convs = await self._load()
            for c in convs:
                if c["thread_id"] == thread_id:
                    c["model"] = model
                    break
            await self._save(convs)

    async def update_conversation_title(self, thread_id: str, title: str) -> None:
        async with self._lock:
            convs = await self._load()
            for c in convs:
                if c["thread_id"] == thread_id:
                    c["title"] = title
                    break
            await self._save(convs)

    async def update_conversation_system_prompt(self, thread_id: str, system_prompt: str) -> None:
        async with self._lock:
            convs = await self._load()
            for c in convs:
                if c["thread_id"] == thread_id:
                    c["system_prompt"] = system_prompt
                    break
            await self._save(convs)

    async def list_conversations(self) -> list[Conversation]:
        convs = await self._load()
        return [_dict_to_conversation(c) for c in convs]

    async def _load(self) -> list[dict[str, Any]]:
        """Load conversations from JSON file."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._load_sync)

    def _load_sync(self) -> list[dict[str, Any]]:
        if not self._data_path.exists():
            return []
        with open(self._data_path) as f:
            return json.load(f)

    async def _save(self, data: list[dict[str, Any]]) -> None:
        """Save conversations to JSON file with atomic write."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._save_sync, data)

    def _save_sync(self, data: list[dict[str, Any]]) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self._data_path.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, self._data_path)


def _dict_to_conversation(d: dict[str, Any]) -> Conversation:
    return Conversation(
        thread_id=d["thread_id"],
        title=d.get("title"),
        model=d["model"],
        system_prompt=d.get("system_prompt"),
        is_active=d["is_active"],
        created_at=d["created_at"],
    )
