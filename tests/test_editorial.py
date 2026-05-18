"""Editorial refinement — anti-fluff, generic-advice, paragraph dedup.

These tests pin the SPECIFIC failure modes the refinement layer exists
to catch. Each AI cliché phrase that hits feed quality gets a fixture
here so a regression on the regex shows up as a named failure.
"""
from __future__ import annotations

import pytest

from cyberalertx.ai.editorial import (
    AI_FLUFF_PATTERNS_EN,
    AI_FLUFF_PATTERNS_UA,
    contains_fluff,
    dedupe_detail_paragraphs,
    paragraph_overlap_ratio,
    refine_response,
    strip_fluff_sentences,
    strip_generic_actions,
)
from cyberalertx.ai.models import ThreatPostResponse


def _good_response(**overrides) -> ThreatPostResponse:
    base = dict(
        title="Storm-1124 phishing kit targets US school staff",
        short_summary=(
            "BleepingComputer reports a credential-harvesting phishing kit "
            "operated by a group tracked as Storm-1124."
        ),
        threat_level="High",
        why_it_matters=(
            "If attackers got into a school's M365 inbox they can read "
            "every 2FA code that gets delivered there."
        ),
        affected_users=["Microsoft 365 admins"],
        what_to_do=[
            "Open security.microsoft.com → Sign-in activity",
            "Switch the account from SMS to Authenticator-app 2FA",
            "Revoke OAuth permissions for any unfamiliar app",
        ],
        what_not_to_do=["Don't approve a 2FA prompt you didn't trigger"],
        quick_facts=["Microsoft 365", "Credential theft"],
        emotional_weight=0.7,
        reading_time_seconds=25,
        detail_body="",
    )
    base.update(overrides)
    return ThreatPostResponse(**base)


# ---------- strip_fluff_sentences ------------------------------------------

@pytest.mark.parametrize("fluffy", [
    "Acme reports a phishing campaign. Users should stay vigilant.",
    "Acme reports a phishing campaign. This serves as a reminder of cybersecurity.",
    "Acme reports a phishing campaign. In today's digital landscape, threats evolve.",
    "Acme reports a phishing campaign. The incident highlights the importance of good cyber hygiene.",
])
def test_strip_drops_fluff_keeps_content_en(fluffy):
    out = strip_fluff_sentences(fluffy, "en")
    # The factual sentence survives.
    assert "Acme reports a phishing campaign" in out
    # The fluff doesn't.
    assert "vigilant" not in out.lower()
    assert "reminder" not in out.lower()
    assert "today's digital" not in out.lower()
    assert "hygiene" not in out.lower()


@pytest.mark.parametrize("fluffy", [
    "Розкрито нову кампанію фішингу. Користувачам варто бути уважним до листів.",
    "Розкрито нову кампанію. У сучасному цифровому світі загрози швидко еволюціонують.",
    "Розкрито нову кампанію. Це підкреслює важливість кібербезпеки.",
    "Розкрито нову кампанію. Важливо залишатися пильним щодо фішингу.",
])
def test_strip_drops_fluff_keeps_content_ua(fluffy):
    out = strip_fluff_sentences(fluffy, "ua")
    assert "Розкрито нову кампанію" in out
    assert "пильн" not in out.lower()
    assert "сучасному" not in out.lower()
    assert "важливіст" not in out.lower()


def test_strip_passes_clean_content_through_unchanged():
    """A summary with no fluff sentences must come out byte-identical."""
    text = (
        "BleepingComputer reports a Storm-1124 phishing kit. "
        "Targets are US school staff using Microsoft 365 mailboxes."
    )
    assert strip_fluff_sentences(text, "en") == text


def test_strip_handles_empty():
    assert strip_fluff_sentences("", "en") == ""
    assert strip_fluff_sentences("", "ua") == ""


# ---------- strip_generic_actions ------------------------------------------

def test_drops_generic_advice_en():
    actions = [
        "Open security.microsoft.com → Sign-in activity",
        "Improve your security posture",
        "Switch to Authenticator-app 2FA",
        "Stay vigilant against phishing attempts",
        "Maintain good cyber hygiene",
    ]
    out = strip_generic_actions(actions, "en")
    assert "Open security.microsoft.com → Sign-in activity" in out
    assert "Switch to Authenticator-app 2FA" in out
    # All fluffy entries gone.
    assert not any("security posture" in a.lower() for a in out)
    assert not any("vigilant" in a.lower() for a in out)
    assert not any("cyber hygiene" in a.lower() for a in out)


def test_drops_generic_advice_ua():
    actions = [
        "Зайдіть на security.microsoft.com → Sign-in activity",
        "Будьте обережні з листами",
        "Увімкніть двофакторну автентифікацію через Authenticator",
        "Дотримуйтеся правил кібергігієни",
    ]
    out = strip_generic_actions(actions, "ua")
    # Concrete actions survive.
    assert any("security.microsoft.com" in a for a in out)
    assert any("Authenticator" in a for a in out)
    # Generic advice gone.
    assert not any("обережн" in a.lower() for a in out)
    assert not any("кіберг" in a.lower() for a in out)


def test_empty_action_list_stays_empty():
    assert strip_generic_actions([], "en") == []


# ---------- paragraph_overlap_ratio ----------------------------------------

def test_overlap_zero_for_disjoint_paragraphs():
    a = "Phishing kit Storm-1124 targets Microsoft 365 users in eight US states"
    b = "Apache disclosed a critical RCE vulnerability tracked as CVE-2026-1234"
    assert paragraph_overlap_ratio(a, b) < 0.1


def test_overlap_high_for_paraphrased_paragraph():
    title = "Storm-1124 phishing kit targets US school staff"
    para = (
        "The Storm-1124 phishing kit specifically targets US school staff "
        "by tricking them with credential-harvesting login pages."
    )
    # Both mention Storm-1124, phishing, school, staff — high overlap.
    assert paragraph_overlap_ratio(para, title) >= 0.3


# ---------- dedupe_detail_paragraphs --------------------------------------

def test_dedup_drops_paragraph_that_echoes_summary():
    summary = (
        "BleepingComputer reports a credential-harvesting phishing kit "
        "tracked as Storm-1124 hitting Microsoft 365 school accounts."
    )
    detail = (
        "BleepingComputer reports a credential-harvesting phishing kit "
        "tracked as Storm-1124 hitting Microsoft 365 school accounts.\n\n"
        "The attackers chain OAuth abuse with lookalike domains. Once a "
        "victim signs in, the kit forwards every incoming 2FA code to "
        "the operator within seconds."
    )
    out = dedupe_detail_paragraphs(detail, against=[summary])
    assert "BleepingComputer reports" not in out
    assert "OAuth abuse" in out


def test_dedup_keeps_paragraph_with_novel_information():
    summary = "BleepingComputer reports a Storm-1124 phishing kit."
    detail = (
        "The kit forwards 2FA codes within seconds and pivots into OneDrive "
        "to harvest financial documents before the victim notices."
    )
    out = dedupe_detail_paragraphs(detail, against=[summary])
    assert "2FA codes" in out
    assert "OneDrive" in out


def test_dedup_empty_body_yields_empty():
    assert dedupe_detail_paragraphs("", against=["whatever"]) == ""


# ---------- refine_response (the full pipeline) ----------------------------

def test_refine_strips_fluff_from_summary_and_detail():
    response = _good_response(
        short_summary=(
            "BleepingComputer reports a Storm-1124 phishing kit. "
            "Users should stay vigilant against phishing attempts."
        ),
        why_it_matters=(
            "If attackers got M365 access they read every 2FA code. "
            "This highlights the importance of good cyber hygiene."
        ),
        detail_body=(
            "The kit chains OAuth abuse with lookalike domains.\n\n"
            "In today's digital landscape, organizations must take "
            "proactive steps to strengthen their security posture."
        ),
    )
    refine_response(response, "en")
    assert "vigilant" not in response.short_summary.lower()
    assert "BleepingComputer reports" in response.short_summary
    assert "hygiene" not in response.why_it_matters.lower()
    assert "2FA code" in response.why_it_matters
    assert "digital landscape" not in response.detail_body.lower()
    assert "OAuth abuse" in response.detail_body


def test_refine_drops_generic_actions_from_lists():
    response = _good_response(
        what_to_do=[
            "Open security.microsoft.com → Sign-in activity",
            "Improve your security posture",
            "Switch to Authenticator-app 2FA",
        ],
    )
    refine_response(response, "en")
    assert len(response.what_to_do) == 2
    assert all("security posture" not in a.lower() for a in response.what_to_do)


def test_refine_dedups_detail_against_summary():
    response = _good_response(
        short_summary="Storm-1124 phishing kit targets M365 school accounts.",
        why_it_matters="Attackers can read every email and 2FA code.",
        detail_body=(
            "Storm-1124 phishing kit targets M365 school accounts.\n\n"
            "The operator forwards intercepted 2FA codes within 3 seconds, "
            "then pivots into OneDrive to harvest financial records."
        ),
    )
    refine_response(response, "en")
    # First paragraph echoes summary → dropped.
    assert "Storm-1124 phishing kit targets M365" not in response.detail_body
    # Second paragraph carries novel facts → kept.
    assert "3 seconds" in response.detail_body
    assert "OneDrive" in response.detail_body


def test_refine_idempotent():
    response = _good_response(
        short_summary="BleepingComputer reports a Storm-1124 phishing kit.",
        why_it_matters="Attackers read 2FA codes in real time.",
        detail_body="The kit pivots into OneDrive within minutes.",
        what_to_do=["Revoke OAuth permissions"],
    )
    refine_response(response, "en")
    summary_snapshot = response.short_summary
    why_snapshot = response.why_it_matters
    detail_snapshot = response.detail_body
    actions_snapshot = list(response.what_to_do)
    # Running again over clean content changes nothing.
    refine_response(response, "en")
    assert response.short_summary == summary_snapshot
    assert response.why_it_matters == why_snapshot
    assert response.detail_body == detail_snapshot
    assert response.what_to_do == actions_snapshot


# ---------- contains_fluff (defensive validation hook) --------------------

def test_contains_fluff_returns_phrase_for_match():
    assert contains_fluff("Users should stay vigilant.", "en") is not None
    assert contains_fluff("Будьте уважними у сучасному цифровому світі.", "ua") is not None


def test_contains_fluff_returns_none_for_clean_text():
    assert contains_fluff("CISA reports a zero-day in Apache.", "en") is None
    assert contains_fluff("CERT-UA повідомляє про нову атаку на пошту.", "ua") is None


# ---------- pattern coverage ----------------------------------------------

def test_no_empty_patterns():
    """Sanity: every pattern was compiled with at least one alternative."""
    for p in AI_FLUFF_PATTERNS_EN + AI_FLUFF_PATTERNS_UA:
        assert p.pattern, "empty pattern would match everything"


# ---------- harvested humanizer patterns (EN) ------------------------------

@pytest.mark.parametrize("fluffy", [
    # Significance inflation
    "CISA published an advisory. The disclosure is a testament to coordinated response.",
    "Vendor patched the CVE. This marks a pivotal moment in OT security.",
    "The breach was disclosed. It was a watershed moment for the sector.",
    # Authority tropes
    "Attackers used a stolen token. At its core, the issue is identity hygiene.",
    "Patch is available. The real question is whether IT can roll it out fast enough.",
    # Generic positive endings
    "The vendor pushed a fix. The future looks bright for customers.",
    "Patches landed. Exciting times lie ahead for defenders.",
    "The vendor shipped a fix. Only time will tell whether it holds.",
    # Cutoff disclaimers
    "Details are emerging. As of my last training, no PoC was public.",
    "The campaign is active. Based on the available information, three regions are hit.",
    # Chatbot artifacts
    "Run the patch. I hope this helps.",
    "Of course! The fix is in version 2.4.1.",
    "Great question — here is the workaround.",
])
def test_strip_drops_harvested_humanizer_fluff_en(fluffy):
    """Patterns adopted from the blader/humanizer skill (Nov 2026 harvest).
    Each captures a category of AI-tell that survived the original rule set.

    We only assert the fluff phrases vanish — not that any particular
    factual sentence survives. The strip is whole-sentence; if the
    factual content was in the SAME sentence as the fluff phrase, the
    sentence is gone too (and that's the contract)."""
    out = strip_fluff_sentences(fluffy, "en").lower()
    for forbidden in (
        "testament", "pivotal moment", "watershed",
        "at its core", "real question is",
        "future looks bright", "exciting times", "only time will tell",
        "last training", "available information",
        "i hope this helps", "of course!", "great question",
    ):
        assert forbidden not in out, f"{forbidden!r} survived strip"


@pytest.mark.parametrize("fluffy", [
    "Розкрито нову атаку. Це поворотний момент для сектору.",
    "CERT-UA повідомив про інцидент. По суті, проблема в гігієні ідентичності.",
    "Виробник випустив патч. Майбутнє виглядає яскраво для клієнтів.",
    "Атаку зафіксовано. Станом на моє останнє оновлення, PoC не публічний.",
    "Запустіть оновлення. Сподіваюсь, це допоможе.",
])
def test_strip_drops_harvested_humanizer_fluff_ua(fluffy):
    out = strip_fluff_sentences(fluffy, "ua")
    lowered = out.lower()
    for forbidden in (
        "поворотний момент", "по суті,", "майбутнє виглядає",
        "станом на", "сподіваюсь",
    ):
        assert forbidden not in lowered, f"{forbidden!r} survived strip"


def test_harvested_patterns_dont_eat_innocent_security_prose():
    """The new patterns must not match legitimate technical phrasing —
    cybersec briefs routinely use words like 'core' (CPU), 'right'
    (direction), 'last' (version), 'helps' (utility). Regressions here
    cause real content to vanish."""
    samples_en = [
        "The vulnerability lives in the kernel core scheduler.",
        "Apply the patch right after the maintenance window.",
        "This is the last supported version of OpenSSL 1.1.",
        "Wireshark helps confirm the C2 beacon pattern.",
        "Set the right ACL on the storage bucket.",
        "Only the latest firmware fixes the issue.",
    ]
    for sample in samples_en:
        assert strip_fluff_sentences(sample, "en") == sample, sample
    samples_ua = [
        "Вразливість живе в ядрі планувальника.",
        "Запустіть патч одразу після вікна обслуговування.",
        "Це остання підтримувана версія OpenSSL 1.1.",
        "Wireshark допомагає підтвердити патерн C2.",
    ]
    for sample in samples_ua:
        assert strip_fluff_sentences(sample, "ua") == sample, sample
