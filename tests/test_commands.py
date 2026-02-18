"""Tests for command parsing."""

from deepmax.channels.base import parse_slash_command


def test_parse_simple_command():
    assert parse_slash_command("/help") == ("/help", "")


def test_parse_command_with_args():
    assert parse_slash_command("/model openai:gpt-4.1") == ("/model", "openai:gpt-4.1")


def test_parse_command_preserves_args():
    assert parse_slash_command("/title My cool conversation") == (
        "/title",
        "My cool conversation",
    )


def test_parse_not_a_command():
    assert parse_slash_command("hello world") is None


def test_parse_empty_string():
    assert parse_slash_command("") is None


def test_parse_whitespace():
    assert parse_slash_command("   ") is None


def test_parse_command_with_leading_whitespace():
    assert parse_slash_command("  /new") == ("/new", "")


def test_parse_switch_with_id():
    assert parse_slash_command("/switch 42") == ("/switch", "42")


def test_command_is_lowercased():
    assert parse_slash_command("/HELP") == ("/help", "")
    assert parse_slash_command("/Model openai:gpt-4.1") == ("/model", "openai:gpt-4.1")
