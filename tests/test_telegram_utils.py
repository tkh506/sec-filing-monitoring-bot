from telegram_utils import split_for_telegram


def test_short_text_returns_single_chunk():
    assert split_for_telegram("hello", limit=100) == ["hello"]


def test_splits_on_paragraph_boundary_when_possible():
    text = "A" * 50 + "\n\n" + "B" * 50
    chunks = split_for_telegram(text, limit=60)
    assert len(chunks) == 2
    assert chunks[0] == "A" * 50
    assert chunks[1] == "B" * 50


def test_splits_on_line_boundary_when_no_paragraph_break():
    text = "A" * 50 + "\n" + "B" * 50
    chunks = split_for_telegram(text, limit=60)
    assert chunks[0] == "A" * 50
    assert chunks[1] == "B" * 50


def test_falls_back_to_word_boundary():
    text = " ".join(["word"] * 20)  # 99 chars, no newlines
    chunks = split_for_telegram(text, limit=30)
    assert all(len(c) <= 30 for c in chunks)
    assert " ".join(chunks).replace("  ", " ") == text or "".join(chunks).count("word") == 20


def test_hard_cut_when_no_boundary_exists():
    text = "A" * 100  # one unbroken token, longer than the limit
    chunks = split_for_telegram(text, limit=40)
    assert all(len(c) <= 40 for c in chunks)
    assert "".join(chunks) == text


def test_reassembled_chunks_preserve_all_content():
    text = ("Bullet one fact.\n\n" * 5) + ("word " * 500)
    chunks = split_for_telegram(text, limit=200)
    assert all(len(c) <= 200 for c in chunks)
    # No content lost -- every non-whitespace character from the original appears in order.
    assert "".join(c.replace(" ", "").replace("\n", "") for c in chunks) == text.replace(" ", "").replace("\n", "")
