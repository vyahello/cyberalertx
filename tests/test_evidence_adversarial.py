"""Adversarial wording for the evidence assessment (pipeline/evidence.py).

Strong labels need a statement, not a topic word: "campaign" or "data breach"
alone, hedged ("could", "possible"), preventive ("how to prevent"), capability
("designed to steal", "lets attackers") or negated wording must not confirm
anything. Cases 1-9 are the required regression set; the rest pin the
boundaries found while reviewing 2,811 stored source items.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.evidence import Evidence, assess


def _ev(text: str, category: str = "other", body: str = "") -> Evidence:
    return assess(NewsItem(
        title=text, source="Test", url=f"https://e.test/{abs(hash(text + body))}",
        published_at=datetime(2026, 11, 5, tzinfo=timezone.utc), raw_content=body, category=category,
    ))


OBSERVED = ("confirmed", "attacks_observed")


# ----- the nine required cases ---------------------------------------------------
def test_1_campaign_that_could_target_is_not_an_attack() -> None:
    ev = _ev("Researchers warn that a phishing campaign could target users.", "phishing")
    assert ev.exploitation not in OBSERVED


def test_2_investigated_campaign_without_confirmed_attacks() -> None:
    ev = _ev("The campaign was investigated, but no attacks were confirmed.", "phishing")
    assert ev.exploitation not in OBSERVED
    assert ev.compromise != "confirmed"


def test_3_prevention_advice_is_not_a_breach() -> None:
    ev = _ev("How organizations can prevent a data breach.", "breach")
    assert ev.compromise != "confirmed"


def test_4_possible_breach_under_investigation_is_not_confirmed() -> None:
    ev = _ev("A company is investigating a possible data breach.", "breach")
    assert ev.compromise == "not_confirmed"
    assert "exposure_unconfirmed" in ev.unknowns


def test_5_stolen_records_confirm_exposure() -> None:
    assert _ev("Attackers stole customer records.", "breach").compromise == "confirmed"


def test_6_kev_listing_confirms_exploitation() -> None:
    assert _ev("The vulnerability is listed in CISA KEV.", "vulnerability").exploitation == "confirmed"


def test_7_could_be_exploited_is_not_confirmed() -> None:
    ev = _ev("The flaw could be exploited.", "vulnerability")
    assert ev.exploitation == "not_reported"
    assert "exploitation_unconfirmed" in ev.unknowns


def test_8_disrupted_then_resumed_is_active() -> None:
    assert _ev("The campaign was disrupted and later resumed.", "malware").campaign == "active"


def test_9_disrupted_with_unknown_end() -> None:
    ev = _ev("The campaign was disrupted, but no evidence of its end is available.", "malware")
    assert ev.campaign == "disrupted"
    assert "campaign_end_unconfirmed" in ev.unknowns


# ----- boundaries ----------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "A new phishing campaign targets bank customers with fake invoices.",
    "Researchers observed a large-scale campaign distributing a stealer.",
    "Lazarus Exploits Windows Zero-Day to Gain SYSTEM Access",
    "Hackers Use Compromised ConnectWise Credential to Sign In to 173 Microsoft 365 Tenants",
    "New Shai-Hulud malware wave compromises 600 npm packages",
    "Fake LastPass Authenticator GitHub repos push new Rapuncel infostealer",
    "Кампанія поширює шкідливе ПЗ через фейкові оновлення.",
])
def test_reported_attacks_are_observed(text: str) -> None:
    assert _ev(text, "malware").exploitation in OBSERVED


@pytest.mark.parametrize("text", [
    "Public Exploits Released for Four Linux Kernel Flaws That Enable Local Root",
    "Weekly Recap: UniFi Exploits, macOS Stealers and More",
    "Webinar: How attackers bypass MFA and how defenders can respond",
    "Microsoft Defender can now automatically isolate hacked endpoints",
    "Targeted phishing could hit finance teams next quarter.",
])
def test_topics_and_capabilities_are_not_observed_attacks(text: str) -> None:
    assert _ev(text, "malware").exploitation not in OBSERVED


@pytest.mark.parametrize("text", [
    "Police Dismantle Kratos Phishing Kit Built to Steal Microsoft 365 Sessions",
    "Rogue Agent Flaw Could Have Let Attackers Hijack Chatbots and steal data",
    "Official SDK Flaw Can Let Malicious Servers Steal OAuth Credentials",
    "Council of Europe investigates ShinyHunters data breach claims",
    "Attackers did not steal any customer data, the company said.",
    "Change your password to prevent hackers from stealing your data.",
])
def test_capability_claims_and_denials_do_not_confirm_compromise(text: str) -> None:
    assert _ev(text, "breach").compromise != "confirmed"


@pytest.mark.parametrize("text", [
    "Chick-fil-A data breach affects more than 13,000 customers",
    "Japan's Digital Agency says VPN flaw exposed 246,000 personnel records",
    "ASOS links data breach to social engineering attack",
    "South Korea fines telco giant KT $39 million for customer data breach",
    "Unknown threat actors breached TeamUpdraft's website.",
    "Ernst & Young discloses data breach after support system hack",
])
def test_stated_breaches_stay_confirmed(text: str) -> None:
    assert _ev(text, "breach").compromise == "confirmed"


def test_clause_break_keeps_a_later_statement() -> None:
    body = ("The flaw allows unauthenticated remote code execution, with the flaw actively "
            "exploited in data theft attacks.")
    assert _ev("Vendor warns about a critical flaw", "vulnerability", body).exploitation == "confirmed"


def test_hedge_in_one_clause_does_not_cancel_the_next() -> None:
    ev = _ev("Officials said more systems could be affected, but attackers stole payroll data.", "breach")
    assert ev.compromise == "confirmed"


def test_negated_kev_listing_does_not_confirm() -> None:
    assert _ev("The flaw is not listed in CISA KEV.", "vulnerability").exploitation != "confirmed"


def test_statistic_about_exploited_flaws_is_not_this_event() -> None:
    ev = _ev("Exploited vulnerabilities rose by 20% in 2026, a report says.", "vulnerability")
    assert ev.exploitation != "confirmed"


def test_a_forecast_of_return_is_not_a_comeback() -> None:
    ev = _ev("The botnet was disrupted; researchers say it could return.", "botnet")
    assert ev.campaign == "disrupted"


def test_takedown_then_return_wording() -> None:
    assert _ev("Botnet returns after takedown with new infrastructure", "botnet").campaign == "active"
    assert _ev("The operation came back online after the takedown.", "botnet").campaign == "active"


def test_past_exploitation_still_counts_as_exploited() -> None:
    # Historical exploitation is still exploitation of this flaw; the brief
    # dates it. Only hedged or negated wording is excluded.
    assert _ev("The bug was exploited in the wild in 2019.", "vulnerability").exploitation == "confirmed"


def test_ukrainian_hedge_and_negation() -> None:
    assert _ev("Вразливість може використовуватися в атаках.", "vulnerability").exploitation != "confirmed"
    assert _ev("Зловмисники не викрали дані клієнтів.", "breach").compromise != "confirmed"
    assert _ev("Зловмисники викрали дані клієнтів.", "breach").compromise == "confirmed"


def test_adjective_after_a_conjunction_is_not_a_verb() -> None:
    ev = _ev("TeamViewer Flaw Lets Remote Computers Attack Users", "exploit",
             "A malicious or compromised host can exploit the flaw to crash the viewer.")
    assert ev.exploitation not in OBSERVED


# ----- O34: brief-side claim check (scorecard) -------------------------------
def _flags(brief_text: str, source_text: str, category: str = "vulnerability") -> list[str]:
    from types import SimpleNamespace
    from cyberalertx.ai.scorecard import _evidence_issues
    post = SimpleNamespace(title="", short_summary=brief_text, plain_summary="", why_it_matters="",
                           severity_reason="", detail_body="", quick_facts=[], affected_users=[],
                           what_to_do=[], if_already_affected=[], what_to_avoid=[], am_i_affected=[])
    item = NewsItem(title=source_text, source="Test", url="https://e.test/s",
                    published_at=datetime(2026, 11, 5, tzinfo=timezone.utc), raw_content="", category=category)
    return [i.code for i in _evidence_issues(post, item=item)]


@pytest.mark.parametrize("brief", [
    "Siemens rebadged it, so the underlying code change has been in the wild for a while.",
    "Linux kernel vulnerabilities are in the wild, legacy systems remain exposed.",
    "Discovery via autonomous scanning rather than active exploitation in the wild suggests a low risk.",
])
def test_idiomatic_or_denied_in_the_wild_is_not_an_exploitation_claim(brief: str) -> None:
    assert "unsupported_exploitation" not in _flags(brief, "Vendor patches an out-of-bounds read flaw")


@pytest.mark.parametrize("brief", [
    "Attack logs already observed in the wild against unpatched routers.",
    "The Chrome zero-day was exploited in the wild.",
    "The flaw is being actively exploited.",
])
def test_real_exploitation_claims_are_still_checked(brief: str) -> None:
    assert "unsupported_exploitation" in _flags(brief, "Vendor patches an out-of-bounds read flaw")


def test_rather_than_negates_the_source_claim_too() -> None:
    ev = _ev("Researchers found it by scanning rather than active exploitation in the wild.", "vulnerability")
    assert ev.exploitation != "confirmed"
