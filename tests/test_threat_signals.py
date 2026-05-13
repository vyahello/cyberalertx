"""Threat signal extraction + the derived UX fields.

Each signal has a small derivation ladder (category, audience, platform,
body keywords). These tests pin the most-likely false-positive and
false-negative paths for each signal — they're cheap to run and quick
to diagnose when the upstream classifier shifts.
"""
from __future__ import annotations

from datetime import datetime, timezone

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.signals import (
    ThreatSignals,
    extract_signals,
    potential_impact,
    who_should_care,
)


def _item(**overrides) -> NewsItem:
    base = dict(
        title="Generic cyber story",
        source="t",
        url=f"https://e.test/{abs(hash(str(overrides)))}",
        published_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        raw_content="",
        category="other",
        affected_platforms=[],
        audience_targets=[],
        actionability_level="informational",
        actionability_score=0.0,
        threat_score=10.0,
        language="en",
        source_tier="verified",
        source_credibility_score=0.6,
    )
    base.update(overrides)
    return NewsItem(**base)


# --------------------- active_exploitation -------------------------------

def test_active_exploitation_from_urgent_actionability():
    sig = extract_signals(_item(actionability_level="urgent_action"))
    assert sig.active_exploitation is True
    assert sig.requires_immediate_action is True


def test_active_exploitation_from_phrase():
    sig = extract_signals(_item(raw_content="A flaw is being actively exploited."))
    assert sig.active_exploitation is True


def test_active_exploitation_not_triggered_by_unrelated_text():
    sig = extract_signals(_item(raw_content="The fix is scheduled for Q3."))
    assert sig.active_exploitation is False


# --------------------- credential / email / sessions ---------------------

def test_phishing_category_implies_cred_theft():
    sig = extract_signals(_item(category="phishing", raw_content="credentials harvested"))
    assert sig.credential_theft_risk is True


def test_breach_category_implies_data_exposure_and_creds():
    sig = extract_signals(_item(category="breach"))
    assert sig.data_exposure_risk is True
    assert sig.credential_theft_risk is True


def test_session_hijacking_detected_via_keywords():
    sig = extract_signals(_item(raw_content="Attackers steal session cookies and MFA bypass."))
    assert sig.steals_sessions is True


def test_email_account_detected_via_platform():
    sig = extract_signals(_item(
        category="phishing",
        affected_platforms=["Microsoft 365"],
        raw_content="Phishing kit harvests credentials.",
    ))
    assert sig.affects_email_accounts is True


def test_email_account_not_triggered_for_unrelated_phishing():
    """A phishing item with no M365/Gmail/Exchange signal — credential
    theft fires but email-account does NOT."""
    sig = extract_signals(_item(
        category="phishing", raw_content="Phishing campaign targets bank customers.",
    ))
    assert sig.credential_theft_risk is True
    assert sig.affects_email_accounts is False


# --------------------- financial -----------------------------------------

def test_financial_risk_from_scam_category():
    sig = extract_signals(_item(category="scam"))
    assert sig.financial_risk is True


def test_financial_risk_from_crypto_keywords():
    sig = extract_signals(_item(
        category="malware",
        raw_content="The wallet drainer steals crypto wallet contents.",
    ))
    assert sig.financial_risk is True


def test_financial_risk_quiet_for_unrelated_story():
    sig = extract_signals(_item(category="vulnerability"))
    assert sig.financial_risk is False


# --------------------- enterprise vs consumer ----------------------------

def test_enterprise_risk_from_audience():
    sig = extract_signals(_item(audience_targets=["enterprise"]))
    assert sig.enterprise_risk is True
    assert sig.consumer_risk is False


def test_consumer_risk_from_consumer_category():
    sig = extract_signals(_item(category="scam"))
    assert sig.consumer_risk is True


def test_enterprise_and_consumer_can_both_fire():
    """A phishing campaign aimed at both audiences should flag both."""
    sig = extract_signals(_item(
        category="phishing",
        audience_targets=["normal_users", "enterprise"],
    ))
    assert sig.enterprise_risk is True
    assert sig.consumer_risk is True


# --------------------- malware delivery ----------------------------------

def test_malware_delivery_implied_by_ransomware():
    sig = extract_signals(_item(category="ransomware"))
    assert sig.malware_delivery is True


def test_malware_delivery_from_infostealer_keyword():
    sig = extract_signals(_item(
        category="other",
        raw_content="A new infostealer family targets browsers.",
    ))
    assert sig.malware_delivery is True


# --------------------- who_should_care -----------------------------------

def test_who_should_care_uses_platform_label():
    item = _item(affected_platforms=["Microsoft 365"], audience_targets=["enterprise"])
    sig = extract_signals(item)
    assert who_should_care(item, sig, language="en") == "Microsoft 365 users"
    # UK variant must be Ukrainian — not the EN label.
    assert who_should_care(item, sig, language="ua") == "Користувачі Microsoft 365"


def test_who_should_care_falls_back_to_audience_when_no_platform():
    item = _item(audience_targets=["sysadmins"])
    sig = extract_signals(item)
    assert who_should_care(item, sig, language="en") == "IT administrators"


def test_who_should_care_falls_back_to_signal_for_bare_items():
    item = _item(category="phishing")  # no platform, no audience
    sig = extract_signals(item)
    # phishing → consumer_risk → "Everyday internet users"
    assert who_should_care(item, sig, language="en") == "Everyday internet users"


def test_who_should_care_final_fallback():
    item = _item()  # nothing — neither consumer nor enterprise risk
    sig = extract_signals(item)
    assert who_should_care(item, sig, language="en") == "Cybersecurity professionals"
    assert who_should_care(item, sig, language="ua") == "Фахівці з кібербезпеки"


# --------------------- potential_impact ----------------------------------

def test_potential_impact_orders_by_severity():
    """Active exploitation comes first regardless of other flags."""
    sig = ThreatSignals(
        active_exploitation=True,
        affects_email_accounts=True,
        credential_theft_risk=True,
    )
    labels = potential_impact(sig, language="en")
    assert labels[0] == "Active exploitation"
    assert "Email account takeover" in labels
    assert "Credential compromise" in labels


def test_potential_impact_caps_at_three():
    sig = ThreatSignals(
        active_exploitation=True,
        affects_email_accounts=True,
        credential_theft_risk=True,
        financial_risk=True,
        steals_sessions=True,
        data_exposure_risk=True,
        malware_delivery=True,
    )
    assert len(potential_impact(sig, language="en", limit=3)) == 3


def test_potential_impact_empty_for_no_signals():
    sig = ThreatSignals()
    assert potential_impact(sig, language="en") == []


def test_potential_impact_uk_labels_are_ukrainian():
    sig = ThreatSignals(active_exploitation=True, credential_theft_risk=True)
    labels = potential_impact(sig, language="ua")
    # Must NOT contain English fallbacks.
    assert "Active exploitation" not in labels
    assert "Активна експлуатація" in labels
