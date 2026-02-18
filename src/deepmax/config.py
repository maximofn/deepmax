"""Configuration loading from TOML files with pydantic validation."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class DatabaseConfig(BaseModel):
    url: str = "postgresql://user:pass@localhost:5432/deepmax"


class ProviderConfig(BaseModel):
    model: str = "anthropic:claude-sonnet-4-5-20250929"
    system_prompt: str = "You are a helpful and concise personal assistant."


class TerminalChannelConfig(BaseModel):
    enabled: bool = True
    user_name: str = "user"


class TelegramChannelConfig(BaseModel):
    enabled: bool = False
    allowed_users: list[int] = Field(default_factory=list)


class ChannelsConfig(BaseModel):
    terminal: TerminalChannelConfig = Field(default_factory=TerminalChannelConfig)
    telegram: TelegramChannelConfig = Field(default_factory=TelegramChannelConfig)


class IdentityLink(BaseModel):
    terminal: str | None = None
    telegram: str | None = None


class IdentityConfig(BaseModel):
    links: dict[str, IdentityLink] = Field(default_factory=dict)


class LimitsConfig(BaseModel):
    shutdown_drain: int = 30


class AppConfig(BaseModel):
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load configuration from a TOML file, merging with defaults."""
    if path is None:
        candidates = [Path("config.toml"), Path(__file__).parent.parent.parent / "config.toml"]
        for candidate in candidates:
            if candidate.exists():
                path = candidate
                break

    data: dict[str, Any] = {}
    if path is not None:
        p = Path(path)
        if p.exists():
            with open(p, "rb") as f:
                data = tomllib.load(f)

    return AppConfig.model_validate(data)
