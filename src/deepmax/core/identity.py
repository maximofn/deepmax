"""Cross-channel identity resolution and conversation management."""

from __future__ import annotations

import logging
import uuid

import asyncpg

from deepmax.channels.base import Conversation, User
from deepmax.config import AppConfig

logger = logging.getLogger(__name__)


class IdentityService:
    """Resolves channel-specific UIDs to canonical users and manages conversations."""

    def __init__(self, pool: asyncpg.Pool, config: AppConfig) -> None:
        self.pool = pool
        self.config = config

    async def bootstrap_from_config(self) -> None:
        """Seed users and channel identities from config.identity.links."""
        async with self.pool.acquire() as conn:
            for user_name, link in self.config.identity.links.items():
                # Upsert user
                row = await conn.fetchrow(
                    """INSERT INTO users (name) VALUES ($1)
                       ON CONFLICT DO NOTHING
                       RETURNING id""",
                    user_name,
                )
                if row is None:
                    row = await conn.fetchrow(
                        "SELECT id FROM users WHERE name = $1", user_name
                    )
                user_id = row["id"]

                # Upsert channel identities
                for channel, channel_uid in [
                    ("terminal", link.terminal),
                    ("telegram", link.telegram),
                ]:
                    if channel_uid is not None:
                        await conn.execute(
                            """INSERT INTO channel_identities (user_id, channel, channel_uid)
                               VALUES ($1, $2, $3)
                               ON CONFLICT (channel, channel_uid)
                               DO UPDATE SET user_id = EXCLUDED.user_id""",
                            user_id,
                            channel,
                            channel_uid,
                        )

                logger.info("Bootstrapped user %s (id=%d)", user_name, user_id)

    async def resolve(self, channel: str, channel_uid: str) -> User | None:
        """Resolve a channel identity to a canonical user."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT u.id, u.name, u.created_at
                   FROM users u
                   JOIN channel_identities ci ON ci.user_id = u.id
                   WHERE ci.channel = $1 AND ci.channel_uid = $2""",
                channel,
                channel_uid,
            )
        if row is None:
            return None
        return User(id=row["id"], name=row["name"], created_at=row["created_at"])

    async def get_active_conversation(self, user_id: int) -> Conversation | None:
        """Get the current active conversation for a user."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, user_id, thread_id, title, model, system_prompt,
                          is_active, created_at, updated_at
                   FROM conversations
                   WHERE user_id = $1 AND is_active = true""",
                user_id,
            )
        if row is None:
            return None
        return _row_to_conversation(row)

    async def get_or_create_active_conversation(
        self, user_id: int, model: str, system_prompt: str | None
    ) -> Conversation:
        """Get the active conversation or create one if none exists."""
        conv = await self.get_active_conversation(user_id)
        if conv is not None:
            return conv
        return await self.create_conversation(user_id, model, system_prompt)

    async def create_conversation(
        self, user_id: int, model: str, system_prompt: str | None
    ) -> Conversation:
        """Create a new conversation, deactivating any current one."""
        thread_id = str(uuid.uuid4())
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE conversations SET is_active = false WHERE user_id = $1 AND is_active = true",
                    user_id,
                )
                row = await conn.fetchrow(
                    """INSERT INTO conversations (user_id, thread_id, model, system_prompt)
                       VALUES ($1, $2, $3, $4)
                       RETURNING id, user_id, thread_id, title, model, system_prompt,
                                 is_active, created_at, updated_at""",
                    user_id,
                    thread_id,
                    model,
                    system_prompt,
                )
        conv = _row_to_conversation(row)
        logger.info("Created conversation %s (thread=%s) for user %d", conv.id, thread_id, user_id)
        return conv

    async def switch_conversation(self, user_id: int, conv_id: int) -> Conversation | None:
        """Switch to a different conversation by id."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Verify the target belongs to this user
                target = await conn.fetchrow(
                    "SELECT id FROM conversations WHERE id = $1 AND user_id = $2",
                    conv_id,
                    user_id,
                )
                if target is None:
                    return None
                # Deactivate current
                await conn.execute(
                    "UPDATE conversations SET is_active = false WHERE user_id = $1 AND is_active = true",
                    user_id,
                )
                # Activate target
                row = await conn.fetchrow(
                    """UPDATE conversations SET is_active = true WHERE id = $1
                       RETURNING id, user_id, thread_id, title, model, system_prompt,
                                 is_active, created_at, updated_at""",
                    conv_id,
                )
        return _row_to_conversation(row) if row else None

    async def update_conversation_model(self, conv_id: int, model: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE conversations SET model = $1 WHERE id = $2", model, conv_id
            )

    async def update_conversation_title(self, conv_id: int, title: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE conversations SET title = $1 WHERE id = $2", title, conv_id
            )

    async def update_conversation_system_prompt(self, conv_id: int, system_prompt: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE conversations SET system_prompt = $1 WHERE id = $2",
                system_prompt,
                conv_id,
            )

    async def list_conversations(self, user_id: int) -> list[Conversation]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, user_id, thread_id, title, model, system_prompt,
                          is_active, created_at, updated_at
                   FROM conversations
                   WHERE user_id = $1
                   ORDER BY updated_at DESC""",
                user_id,
            )
        return [_row_to_conversation(r) for r in rows]


def _row_to_conversation(row: asyncpg.Record) -> Conversation:
    return Conversation(
        id=row["id"],
        user_id=row["user_id"],
        thread_id=row["thread_id"],
        title=row["title"],
        model=row["model"],
        system_prompt=row["system_prompt"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
