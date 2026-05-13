"""UA glossary normalizer + russism gate.

Two responsibilities:
  * `normalize_ukrainian` rewrites russism stems to canonical Ukrainian
    in any string. Idempotent.
  * `has_russism` reports whether a string contains any rejection-stem,
    used by the AI response validator to fall back to rule-based.
"""
from __future__ import annotations

import pytest

from cyberalertx.ai.uk_glossary import (
    GLOSSARY,
    RUSSISM_STEMS,
    has_russism,
    normalize_ukrainian,
    normalize_ukrainian_fields,
)


# ---------- glossary normalization ----------------------------------------

@pytest.mark.parametrize("source, expected_fragment", [
    ("уязвимость в системе",       "вразлив"),
    ("обнаружено новую кампанию",  "виявл"),
    ("учётная запись",             "обліков"),
    ("учетная запись",             "обліков"),
    ("вредоносное ПЗ",             "шкідлив"),
    ("взлом серверов",             "злам"),
    ("мошенничество онлайн",       "шахрай"),
    ("обнаружить путём фишинга",   "шляхом"),
])
def test_normalize_replaces_russism_stems(source: str, expected_fragment: str):
    out = normalize_ukrainian(source)
    assert expected_fragment in out, f"expected {expected_fragment!r} in {out!r}"


def test_normalize_preserves_clean_ukrainian():
    """Pure Ukrainian text passes through unchanged — no false-positive
    replacements that would corrupt already-clean copy."""
    text = (
        "BleepingComputer повідомляє про нову фішингову кампанію, що "
        "націлена на користувачів Microsoft 365 у восьми штатах США."
    )
    assert normalize_ukrainian(text) == text


def test_normalize_is_idempotent():
    """Running twice yields the same result — replacements don't introduce
    new russisms that would get re-replaced on a second pass."""
    once = normalize_ukrainian("Уязвимость путём взлома")
    twice = normalize_ukrainian(once)
    assert once == twice


def test_normalize_preserves_first_letter_capitalization():
    """Sentence-initial words start with an uppercase letter; the
    replacement should preserve that case so we don't end up with
    lowercase sentence starters."""
    assert normalize_ukrainian("Уязвимость").startswith("Вразлив")


def test_normalize_empty_input():
    assert normalize_ukrainian("") == ""
    assert normalize_ukrainian(None) is None  # type: ignore[arg-type]


def test_normalize_fields_walks_recursively():
    data = {
        "title": "Уязвимость в системе",
        "list": ["обнаружено", "являются"],
        "nested": {"inner": "взлом"},
        "ignored": 42,
    }
    out = normalize_ukrainian_fields(data)
    assert "Уязвимост" not in out["title"]
    assert "обнаружено" not in out["list"][0]
    assert "взлом" not in out["nested"]["inner"]
    assert out["ignored"] == 42


# ---------- russism gate -------------------------------------------------

@pytest.mark.parametrize("bad", [
    "обнаружено новое",
    "уязвимость в системе",
    "мошенничество банковское",
    "взлом сайта",
    "путем перехвата",
    "только что сообщили",
])
def test_has_russism_flags_known_stems(bad: str):
    assert has_russism(bad) is not None


@pytest.mark.parametrize("clean", [
    "BleepingComputer повідомляє про новий витік",
    "Хакери використали фішинг для крадіжки паролів",
    "Сьогодні CERT-UA опублікував бюлетень",
    "",
])
def test_has_russism_clears_clean_strings(clean: str):
    assert has_russism(clean) is None


def test_glossary_and_stems_stay_in_sync():
    """A safety check: every stem in the rejection list should have at
    least one replacement entry in the glossary. Otherwise the validator
    would reject AI output that the normalizer can't fix."""
    glossary_stems = set(GLOSSARY.keys())
    for rejection in RUSSISM_STEMS:
        # Either an exact match OR a prefix of some glossary stem.
        assert any(g.startswith(rejection[:6]) or rejection.startswith(g[:6])
                   for g in glossary_stems), (
            f"rejection stem {rejection!r} has no glossary entry — "
            "validator would reject without normalizer fixing the text"
        )
