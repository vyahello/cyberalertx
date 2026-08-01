"""Tests for the template registry and fallback chain."""
from __future__ import annotations

from cyberalertx.ai.templates import (
    PromptTemplate,
    TemplateRegistry,
    _RAW_CONTENT_MAX_CHARS,
    _truncate_source_body,
    default_template_registry,
)


def test_exact_match_wins():
    reg = default_template_registry()
    t = reg.select("en", "phishing", "normal_users")
    assert t.id == "en/phishing/normal_users"


def test_falls_back_to_general_audience_within_category():
    reg = default_template_registry()
    t = reg.select("en", "ransomware", "developers")
    # No (en, ransomware, developers); should land on (en, ransomware, general).
    assert t.id == "en/ransomware/general"


def test_falls_back_to_default_category():
    reg = default_template_registry()
    t = reg.select("en", "nonexistent_category", "general")
    assert t.id == "en/default/general"


def test_unknown_audience_in_unknown_category_lands_on_default_default():
    reg = default_template_registry()
    t = reg.select("en", "nonexistent_category", "nonexistent_audience")
    assert t.id == "en/default/general"


def test_ukrainian_specific_template_used_when_present():
    reg = default_template_registry()
    t = reg.select("ua", "phishing", "normal_users")
    assert t.id == "uk/phishing/normal_users"
    assert t.language == "ua"


def test_unknown_language_falls_through_to_english_default():
    reg = default_template_registry()
    t = reg.select("ja", "phishing", "normal_users")
    # No ja templates at all → cross-language safety net hits en/default/general.
    assert t.id == "en/default/general"


def test_custom_registry_overrides_defaults():
    custom = PromptTemplate(
        id="en/custom/general",
        language="en",
        category="custom",
        audience="general",
        persona="custom",
        style_notes="custom",
    )
    base = PromptTemplate(
        id="en/default/general",
        language="en",
        category="default",
        audience="general",
        persona="base",
        style_notes="base",
    )
    reg = TemplateRegistry([custom, base])
    assert reg.select("en", "custom", "general").id == "en/custom/general"
    assert reg.select("en", "something_else", "any").id == "en/default/general"


# ---------- _truncate_source_body -----------------------------------------

def test_truncate_passes_short_body_through_unchanged():
    body = "BleepingComputer reports a Storm-1124 phishing kit. Targets are M365."
    assert _truncate_source_body(body) == body


def test_truncate_caps_long_body_below_limit_plus_marker():
    body = "Lorem ipsum dolor sit amet. " * (_RAW_CONTENT_MAX_CHARS // 20)
    out = _truncate_source_body(body)
    assert "[…truncated]" in out
    # Final length cannot exceed the limit + the marker (~20 chars buffer).
    assert len(out) <= _RAW_CONTENT_MAX_CHARS + 25


def test_truncate_prefers_paragraph_break_when_available():
    # Sizes are derived from the cap, not hardcoded: the constant moved from
    # 1200 to 3000 once we measured that the only bodies it ever cut were
    # CISA advisories, whose CVSS vectors and version strings live in the
    # back half. A fixture pinned to the old number silently stopped
    # exercising truncation at all.
    cap = _RAW_CONTENT_MAX_CHARS
    lede = "A" * int(cap * 0.875)      # inside the last 30% of the cap
    tail = "B" * (cap + 500)           # guarantees we are over the limit
    out = _truncate_source_body(f"{lede}\n\n{tail}")
    # Cut should land on the paragraph break, dropping all the B's.
    assert "B" not in out
    assert out.endswith("[…truncated]")


def test_truncate_falls_back_to_sentence_when_no_paragraph_break():
    # One running paragraph (no `\n\n`) with a sentence end near the cap,
    # then trailing boilerplate well past the cap. Cap-relative for the same
    # reason as the paragraph case above.
    cap = _RAW_CONTENT_MAX_CHARS
    body = ("X" * int(cap * 0.92)) + ". " + ("Y" * (cap + 800)) + ". Trailing tail boilerplate."
    out = _truncate_source_body(body)
    assert "Trailing tail" not in out
    assert "[…truncated]" in out


def test_truncate_hard_cuts_when_no_natural_break_in_window():
    # Worst case: a wall of a single token with no punctuation anywhere.
    body = "X" * (_RAW_CONTENT_MAX_CHARS * 2)
    out = _truncate_source_body(body)
    assert out.endswith("[…truncated]")
    assert len(out) <= _RAW_CONTENT_MAX_CHARS + 25


def test_truncate_handles_empty_and_none_like_input():
    assert _truncate_source_body("") == ""
