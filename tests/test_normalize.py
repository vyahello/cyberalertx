from datetime import datetime, timezone

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.normalize import (
    detect_language,
    normalize_item,
    safe_text,
)


def _item(title: str, body: str = "") -> NewsItem:
    return NewsItem(
        title=title,
        source="t",
        url=f"https://e.test/{abs(hash(title))}",
        published_at=datetime.now(timezone.utc),
        raw_content=body,
    )


# ---------- safe_text ----------

def test_safe_text_nfc_normalizes():
    decomposed = "café"  # "café" with combining acute accent
    composed = "café"
    assert safe_text(decomposed) == composed


def test_safe_text_strips_control_chars():
    assert safe_text("hello\x00\x07world") == "hello world"


def test_safe_text_collapses_whitespace():
    assert safe_text("a   b\n\tc") == "a b c"


def test_safe_text_handles_lone_surrogate_without_crashing():
    # An unpaired high surrogate — represents a malformed feed.
    bad = "ok\ud800ish"
    out = safe_text(bad)
    # No exception, and the surrogate gets replaced (we don't care what with).
    assert "ok" in out and "ish" in out


def test_safe_text_non_string_returns_empty():
    assert safe_text(None) == ""  # type: ignore[arg-type]
    assert safe_text(123) == ""   # type: ignore[arg-type]


# ---------- detect_language ----------

def test_detect_english():
    assert detect_language(
        "Critical zero-day actively exploited in Windows kernel"
    ) == "en"


def test_detect_ukrainian():
    # Real Ukrainian with і / ї / є
    assert detect_language(
        "Кібератака на українські банки: зафіксовано витік даних клієнтів"
    ) == "uk"


def test_non_ukrainian_cyrillic_returns_other():
    # We no longer claim to identify Russian (or any other Cyrillic-using
    # language); anything Cyrillic without Ukrainian-only letters is "other".
    assert detect_language(
        "Хакеры взломали серверы крупной компании, украдены данные клиентов"
    ) == "other"


def test_detect_too_short_returns_unknown():
    assert detect_language("hi") == "unknown"
    assert detect_language("") == "unknown"


def test_detect_mixed_script_prefers_dominant():
    txt = "CVE-2024-9999 critical vulnerability — patch released by vendor"
    assert detect_language(txt) == "en"


# ---------- normalize_item ----------

def test_normalize_item_sets_language_and_cleans_text():
    item = _item("Атака на банк", body="Зафіксовано фішингову кампанію\x00")
    normalize_item(item)
    assert item.language == "uk"
    assert item.original_language == "uk"
    assert "\x00" not in item.raw_content


def test_normalize_item_preserves_original_language_when_already_set():
    item = _item("Phishing campaign", body="Targets banks")
    item.original_language = "uk"  # imagine a future translator set this
    normalize_item(item)
    assert item.language == "en"
    assert item.original_language == "uk"
