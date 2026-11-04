"""Editorial scorecard, the UA calque table, and the prompt rules that go with them."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from cyberalertx.ai.fact_check import Finding
from cyberalertx.ai.scorecard import (
    DEFAULT_REVIEW_THRESHOLD,
    WEIGHTS,
    review_threshold,
    score_post,
    source_name_candidates,
)
from cyberalertx.ai.uk_glossary import CALQUES, find_calques, find_term_deviations
from cyberalertx.models import NewsItem

BODY = ("Threat actors began exploiting CVE-2026-44338, a missing authentication flaw in "
        "PraisonAI, four hours after disclosure. Version 2.4.59 fixes it. The project "
        "maintainers published an advisory and urged every operator to update. " * 2)


def _item(**over: Any) -> NewsItem:
    base: dict[str, Any] = dict(
        title="PraisonAI auth bypass exploited within hours", source="The Hacker News",
        url="https://thn.test/praison", published_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
        raw_content=BODY, language="en",
    )
    base.update(over)
    return NewsItem(**base)


def _good_en(**over: Any) -> dict[str, Any]:
    post: dict[str, Any] = {
        "title": "PraisonAI servers are being hijacked hours after the bug went public",
        "plain_summary": ("Anyone running the PraisonAI agent framework should update to 2.4.59 "
                          "today, because attackers already use this bug."),
        "short_summary": ("The Hacker News reports attacks on CVE-2026-44338 in PraisonAI began "
                          "four hours after disclosure; version 2.4.59 closes the hole."),
        "why_it_matters": "An exposed PraisonAI server runs attacker tasks with its own API keys.",
        "detail_body": ("Exploitation four hours after disclosure means the window between "
                        "advisory and attack is now shorter than most patch cycles, so operators "
                        "who batch updates weekly are exposed for days.\n\n"
                        "Instances reachable from the internet are the first targets; internal "
                        "deployments buy time but not safety, because agent tasks often hold "
                        "database and cloud credentials that make any foothold valuable."),
        "quick_facts": ["CVE-2026-44338", "Fixed in 2.4.59", "Exploited 4 hours after disclosure"],
        "affected_users": ["PraisonAI operators"],
        "what_to_do": ["Upgrade PraisonAI to 2.4.59 now."],
        "what_not_to_do": [],
        "am_i_affected": ["Run `pip show praisonai`. Below 2.4.59 means you are affected."],
        "severity_reason": "Attacks already started and an exposed server needs no password.",
    }
    post.update(over)
    return post


def test_a_clean_post_scores_high_and_needs_no_review() -> None:
    card = score_post(_good_en(), language="en", item=_item(), threshold=85)
    assert card.score >= 90, card.issues
    assert not card.needs_review
    assert set(card.dimensions) == set(WEIGHTS)
    assert sum(WEIGHTS.values()) == 100


def test_a_hard_fact_issue_forces_review_regardless_of_score() -> None:
    post = _good_en(detail_body=_good_en()["detail_body"] + " It mirrors CVE-2023-22518.")
    card = score_post(post, language="en", item=_item(), threshold=0)
    assert card.needs_review
    assert card.dimensions["accuracy"] == 0
    assert any(r.startswith("not in source") for r in card.review_reasons)


def test_a_cross_locale_conflict_forces_review() -> None:
    conflict = Finding(kind="date", value="EN says November 1; UA says 2 листопада",
                       field="cross_locale", severity="major", message="date differs")
    card = score_post(_good_en(), language="en", item=_item(), cross_locale=[conflict],
                      threshold=0)
    assert card.needs_review
    assert any("editions disagree" in r for r in card.review_reasons)


def test_language_checks_en() -> None:
    post = _good_en(
        why_it_matters="This reshapes the threat landscape — and it matters — a lot!",
        plain_summary=("PraisonAI, a framework that runs AI agents, has a flaw that lets "
                       "attackers take over servers."),
    )
    codes = {i.code for i in score_post(post, language="en", item=_item()).issues}
    assert {"ai_cliche", "em_dash_overuse", "exclamation", "inline_gloss_formula"} <= codes


def test_language_checks_ua_flag_russisms_calques_and_terms() -> None:
    post = _good_en(
        title="Нападники атакують сервери PraisonAI через вразливість",
        short_summary="The Hacker News повідомляє: даний інцидент являє собою атаку шляхом обходу входу.",
        why_it_matters="Уязвимость дає атакувальнику доступ до ключів.",
        plain_summary="Оновіть PraisonAI до 2.4.59 сьогодні, бо зловмисники вже використовують помилку.",
    )
    issues = score_post(post, language="ua", item=_item()).issues
    codes = [i.code for i in issues]
    assert "russism" in codes
    calques = {i.message for i in issues if i.code == "calque"}
    assert any("шляхом" in m for m in calques)
    assert any("являє собою" in m for m in calques)
    assert any("даний" in m.lower() for m in calques)
    assert any(i.code == "terminology" for i in issues)


def test_originality_flags_restated_analysis_and_near_copy() -> None:
    restated = _good_en(detail_body=_good_en()["short_summary"])
    codes = {i.code for i in score_post(restated, language="en", item=_item()).issues}
    assert "analysis_restates_summary" in codes
    copied = _good_en(why_it_matters=BODY[:220])
    codes = {i.code for i in score_post(copied, language="en", item=_item()).issues}
    assert "near_copy" in codes


def test_attribution_needs_a_named_source_and_a_link() -> None:
    post = _good_en(short_summary="Attacks on PraisonAI began four hours after the bug became public.")
    codes = {i.code for i in score_post(post, language="en", item=_item()).issues}
    assert "no_attribution" in codes
    no_url = score_post(_good_en(), language="en", item=_item(url=""))
    assert "no_source_url" in {i.code for i in no_url.issues}


def test_colon_lead_counts_as_attribution() -> None:
    post = _good_en(short_summary="The Hacker News: attacks on CVE-2026-44338 began within hours.")
    assert "no_attribution" not in {i.code for i in score_post(post, language="en", item=_item()).issues}


def test_without_the_source_accuracy_is_skipped_and_the_total_rescaled() -> None:
    card = score_post(_good_en(), language="en", item=None, threshold=85)
    assert "accuracy" not in card.dimensions
    assert card.source_checked is False
    assert 0 <= card.score <= 100


def test_threshold_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CYBERALERTX_REVIEW_THRESHOLD", raising=False)
    assert review_threshold() == DEFAULT_REVIEW_THRESHOLD
    monkeypatch.setenv("CYBERALERTX_REVIEW_THRESHOLD", "70")
    assert review_threshold() == 70
    monkeypatch.setenv("CYBERALERTX_REVIEW_THRESHOLD", "nonsense")
    assert review_threshold() == DEFAULT_REVIEW_THRESHOLD


def test_source_name_candidates() -> None:
    assert "Kaspersky" in source_name_candidates("Securelist (Kaspersky)")
    assert "CISA" in source_name_candidates("CISA Alerts")
    assert "Hacker News" in source_name_candidates("The Hacker News")


def test_scoring_is_pure() -> None:
    post = _good_en()
    before = dict(post)
    score_post(post, language="en", item=_item())
    assert post == before


# ---------------------------------------------------------------------------
# Calque table (uk_glossary)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,rule", [
    ("проникли шляхом фішингу", "shlyakhom"),
    ("це являється проблемою", "yavlyatysya"),
    ("сервіс являє собою шлюз", "yavlyatysya"),
    ("приймали участь в атаці", "pryimaty_uchast"),
    ("на протязі тижня", "na_protyazi"),
    ("у відповідності до закону", "u_vidpovidnosti"),
    ("в якості приманки", "v_yakosti"),
    ("даний інцидент", "danyi"),
    ("слідуючий крок", "sliduyuchyi"),
    ("хеші співпадають", "spivpadaty"),
    ("прийняти міри", "pryinyaty_miry"),
    ("Microsoft закрила дві критичні уразливості", "zakryty_vrazlyvist"),
    ("невірний пароль", "virno"),
])
def test_every_calque_rule_fires(text: str, rule: str) -> None:
    assert rule in {cid for cid, _, _ in find_calques(text)}


def test_the_calque_table_is_data_with_a_preferred_form_per_row() -> None:
    assert len(CALQUES) >= 12
    assert all(len(row) == 4 and row[3] for row in CALQUES)


@pytest.mark.parametrize("text", [
    "витік даних користувачів", "за даними CERT-UA", "дані клієнтів", "даними з серверів",
    "протягом тижня", "відповідно до закону", "Microsoft виправила вразливість",
])
def test_correct_ukrainian_is_not_flagged(text: str) -> None:
    assert find_calques(text) == []


def test_attacker_terminology() -> None:
    hits = {cid for cid, _, _ in find_term_deviations("нападники й атакувальник")}
    assert hits == {"napadnyk", "atakuvalnyk"}
    assert find_term_deviations("зловмисники атакують") == []


# ---------------------------------------------------------------------------
# Prompt rules
# ---------------------------------------------------------------------------

def test_ua_prompt_no_longer_teaches_shlyakhom_and_has_the_new_blocks() -> None:
    from cyberalertx.ai.templates import _SHARED_RULES_UK as uk
    assert "є, шляхом," not in uk                       # was listed as "canonical"
    assert "ТЕРМІНОЛОГІЯ" in uk and "УНИКАЙТЕ КАЛЬОК" in uk
    for term in ("зловмисник", "програма-вимагач", "витік даних", "віддалене виконання коду",
                 "підвищення привілеїв", "уразливість нульового дня", "облікові дані",
                 "фішинг", "оновлення безпеки"):
        assert term in uk, term
    for calque, fix in (("на протязі", "протягом"), ("в якості", "як"),
                        ("співпадати", "збігатися"), ("прийняти міри", "вжити заходів")):
        assert calque in uk and fix in uk
    assert "атакувальнику" not in uk                   # the worked example used it
    assert "уразливість → вразливість" not in uk       # euphony now decides


@pytest.mark.parametrize("name", ["_SHARED_RULES_EN", "_SHARED_RULES_UK"])
def test_both_prompts_require_sourced_facts_and_code_formatting(name: str) -> None:
    from cyberalertx.ai import templates
    rules = getattr(templates, name)
    assert "FACT SHEET" in rules
    assert "`uname -r`" in rules and "'uname -r'" not in rules
    assert "Cerber" in rules                            # the labelled-background example


def test_en_prompt_discourages_the_inline_gloss_formula() -> None:
    from cyberalertx.ai.templates import _SHARED_RULES_EN
    assert "VARY THE CONSTRUCTION" in _SHARED_RULES_EN
