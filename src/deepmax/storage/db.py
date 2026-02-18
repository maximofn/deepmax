"""Database pool and schema management for application tables."""

from __future__ import annotations

import logging

import asyncpg

logger = logging.getLogger(__name__)

SCHEMA_SQL = """\
-- Canonical users
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Per-channel identities
CREATE TABLE IF NOT EXISTS channel_identities (
    id          SERIAL PRIMARY KEY,
    user_id     INT REFERENCES users(id) ON DELETE CASCADE,
    channel     TEXT NOT NULL,
    channel_uid TEXT NOT NULL,
    metadata    JSONB DEFAULT '{}',
    UNIQUE(channel, channel_uid)
);

-- Conversations: maps user -> LangGraph thread_id
CREATE TABLE IF NOT EXISTS conversations (
    id            SERIAL PRIMARY KEY,
    user_id       INT REFERENCES users(id) ON DELETE CASCADE,
    thread_id     TEXT NOT NULL UNIQUE,
    title         TEXT,
    model         TEXT NOT NULL,
    system_prompt TEXT,
    is_active     BOOLEAN DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- Auto-update updated_at trigger
DO $$ BEGIN
    CREATE OR REPLACE FUNCTION update_updated_at()
    RETURNS TRIGGER AS $fn$
    BEGIN NEW.updated_at = now(); RETURN NEW; END;
    $fn$ LANGUAGE plpgsql;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_conversations_updated_at
        BEFORE UPDATE ON conversations
        FOR EACH ROW EXECUTE FUNCTION update_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Only one active conversation per user
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_conv
    ON conversations(user_id) WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_channel_identities_lookup
    ON channel_identities(channel, channel_uid);
"""


async def init_pool(database_url: str) -> asyncpg.Pool:
    """Create a connection pool and apply the application schema."""
    pool = await asyncpg.create_pool(database_url)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
    logger.info("Database schema applied")
    return pool


async def close_pool(pool: asyncpg.Pool) -> None:
    """Close the connection pool."""
    await pool.close()
    logger.info("Database pool closed")
