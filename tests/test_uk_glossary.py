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


# --------------------- script gate vs machine identifiers ------------------

def test_package_names_do_not_read_as_untranslated_english() -> None:
    """Identifiers carry no language signal, so they must not count as English.

    A bullet naming the npm packages a reader has to remove is 79 Latin
    letters against 7 Cyrillic. The raw ratio said "English" and the pre-send
    gate blocked the most actionable advice in a supply-chain post from the
    Ukrainian channel.
    """
    from cyberalertx.ai.validation import _wrong_script_for_language

    assert _wrong_script_for_language(
        "Видаліть @joyfill/layouts@0.1.2-2773.beta.0 та "
        "@joyfill/components@4.0.0-rc24-2773-beta.4.",
        "ua",
    ) is False
    assert _wrong_script_for_language(
        "Оновіть Chrome до версії 126.0.6478 через меню Довідка.", "ua",
    ) is False


def test_real_untranslated_english_is_still_rejected() -> None:
    """Stripping identifiers must not blunt the check it guards."""
    from cyberalertx.ai.validation import _wrong_script_for_language

    assert _wrong_script_for_language(
        "Install the vendor patch and reboot the affected hosts now.", "ua",
    ) is True
    assert _wrong_script_for_language(
        "Attackers are exploiting this flaw in the wild against servers.", "ua",
    ) is True
    assert _wrong_script_for_language(
        "Оновіть Chrome негайно, зловмисники вже атакують.", "en",
    ) is True


# --------------------- calque / anglicism table ----------------------------

def test_threat_actor_is_ugrupovannya_not_ugrupuvannya() -> None:
    """«Угрупування» is the process noun — the ACT of grouping. A threat actor
    is «угруповання». The wrong form was the majority form in the live cache
    (36 of the 71 substitutions this table makes)."""
    from cyberalertx.ai.uk_glossary import normalize_ukrainian_calques

    assert normalize_ukrainian_calques(
        "Угрупування, що стоїть за атакою, не назване",
    ) == "Угруповання, що стоїть за атакою, не назване"
    assert normalize_ukrainian_calques(
        "атаки цього угрупування тривають",
    ) == "атаки цього угруповання тривають"


def test_patch_participles_are_not_ukrainian_words() -> None:
    from cyberalertx.ai.uk_glossary import normalize_ukrainian_calques

    assert "неоновлені" in normalize_ukrainian_calques("непропатчені сервери")
    assert "виправлено" in normalize_ukrainian_calques("пропатчено вчора")


def test_firewall_calque_is_repaired() -> None:
    """«Міжсітьовий екран» is a half-translated «межсетевой экран»."""
    from cyberalertx.ai.uk_glossary import normalize_ukrainian_calques

    assert normalize_ukrainian_calques(
        "захищено міжсітьовим бар'єром",
    ) == "захищено мережевим екраном"


def test_vrazlyvist_is_the_shipped_form() -> None:
    from cyberalertx.ai.uk_glossary import normalize_ukrainian_calques

    assert normalize_ukrainian_calques("Уразливість у ядрі") == "Вразливість у ядрі"
    # Must NOT touch «ураження» / «уражати» — different stem entirely.
    assert normalize_ukrainian_calques("ураження систем") == "ураження систем"
    assert normalize_ukrainian_calques("уражені пристрої") == "уражені пристрої"


def test_calque_pass_is_idempotent() -> None:
    from cyberalertx.ai.uk_glossary import normalize_ukrainian_calques

    text = "Угрупування використало непропатчені сервери за міжсітьовим бар'єром"
    once = normalize_ukrainian_calques(text)
    assert normalize_ukrainian_calques(once) == once


def test_calque_pass_leaves_correct_ukrainian_alone() -> None:
    from cyberalertx.ai.uk_glossary import normalize_ukrainian_calques

    for text in (
        "Оновіть Chrome через меню Довідка до версії 126.",
        "Зловмисники викрали дані клієнтів компанії.",
        "Мережевий захист не допоміг проти цієї атаки.",
    ):
        assert normalize_ukrainian_calques(text) == text
