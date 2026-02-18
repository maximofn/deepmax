"""Tests for configuration loading."""

import tempfile
from pathlib import Path

from deepmax.config import AppConfig, load_config


def test_default_config():
    """Loading with no file returns defaults."""
    config = load_config(path="/nonexistent/config.toml")
    assert isinstance(config, AppConfig)
    assert config.channels.terminal.enabled is True
    assert config.channels.telegram.enabled is False
    assert config.provider.model == "anthropic:claude-sonnet-4-5-20250929"


def test_load_from_toml():
    """Loading from a TOML file merges with defaults."""
    toml_content = b"""\
[database]
url = "postgresql://test:test@localhost:5432/testdb"

[provider]
model = "openai:gpt-4.1"

[channels.terminal]
enabled = false

[channels.telegram]
enabled = true
allowed_users = [111, 222]

[identity.links.alice]
terminal = "local"
telegram = "111"
"""
    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
        f.write(toml_content)
        f.flush()
        config = load_config(path=f.name)

    assert config.database.url == "postgresql://test:test@localhost:5432/testdb"
    assert config.provider.model == "openai:gpt-4.1"
    assert config.channels.terminal.enabled is False
    assert config.channels.telegram.enabled is True
    assert config.channels.telegram.allowed_users == [111, 222]
    assert "alice" in config.identity.links
    assert config.identity.links["alice"].terminal == "local"
    assert config.identity.links["alice"].telegram == "111"


def test_partial_config():
    """Partial TOML still fills defaults for missing sections."""
    toml_content = b"""\
[provider]
model = "google_genai:gemini-2.5-flash-lite"
"""
    with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
        f.write(toml_content)
        f.flush()
        config = load_config(path=f.name)

    assert config.provider.model == "google_genai:gemini-2.5-flash-lite"
    # Defaults preserved
    assert config.database.url == "postgresql://user:pass@localhost:5432/deepmax"
    assert config.channels.terminal.enabled is True
    assert config.limits.shutdown_drain == 30
