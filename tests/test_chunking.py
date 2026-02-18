"""Tests for Telegram markdown chunking."""

from deepmax.channels.telegram import chunk_markdown


def test_short_text_returns_single_chunk():
    text = "Hello, world!"
    assert chunk_markdown(text) == [text]


def test_empty_text():
    assert chunk_markdown("") == [""]


def test_splits_at_line_boundaries():
    lines = [f"Line {i}" for i in range(100)]
    text = "\n".join(lines)
    chunks = chunk_markdown(text, size=200)
    assert len(chunks) > 1
    # Verify all content is preserved
    rejoined = ""
    for i, chunk in enumerate(chunks):
        if i > 0:
            rejoined += "\n"
        rejoined += chunk
    assert set(text.split("\n")) == set(rejoined.split("\n"))


def test_respects_code_fences():
    text = "Before\n```python\n" + "x = 1\n" * 200 + "```\nAfter"
    chunks = chunk_markdown(text, size=300)
    assert len(chunks) > 1
    # Every chunk with an opening ``` should have a closing ```
    for chunk in chunks[:-1]:
        opens = chunk.count("```")
        assert opens % 2 == 0, f"Unclosed code fence in chunk: {chunk[:80]}..."


def test_single_line_longer_than_size():
    text = "A" * 5000
    chunks = chunk_markdown(text, size=3500)
    # Even a single line should be returned (can't split mid-line)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_multiple_code_blocks():
    text = "Intro\n```\ncode1\n```\nMiddle\n```\ncode2\n```\nEnd"
    chunks = chunk_markdown(text, size=5000)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_size_respected():
    lines = [f"This is line number {i} with some padding text" for i in range(200)]
    text = "\n".join(lines)
    chunks = chunk_markdown(text, size=500)
    # All chunks except possibly the last should be <= size (plus code fence overhead)
    for chunk in chunks[:-1]:
        assert len(chunk) <= 500 + 10  # small tolerance for fence closing
