"""Tests for the template registry and fallback chain."""
from __future__ import annotations

from cyberalertx.ai.templates import (
    PromptTemplate,
    TemplateRegistry,
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
