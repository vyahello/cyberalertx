"""Evidence before conclusions: regression tests for the editorial-quality
upgrade.

Case A and Case B are real CyberAlertX stories (4 Nov 2026) whose published
labels overstated the evidence. Their fixtures are the feed excerpts the
pipeline actually had, so these tests check what the system can know, not
what the full articles say.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from cyberalertx.ai.models import ThreatPost
from cyberalertx.ai.scorecard import _evidence_issues, score_post
from cyberalertx.models import NewsItem
from cyberalertx.pipeline.audience import classify_audience
from cyberalertx.pipeline.evidence import assess
from cyberalertx.pipeline.signals import extract_signals, potential_impact, who_should_care

NOW = datetime(2026, 11, 4, 13, 0, tzinfo=timezone.utc)

CASE_A_EXCERPT = (
    "A phishing campaign used Google Calendar invites, trusted redirects, and fake login pages to "
    "hijack corporate Google sessions and bypass MFA protections. Material Security examines how "
    "Operation CloudFire tracked the attacks, blocked malicious messages, and helped take down nearly "
    "900 domains used by the attackers. [...]"
)
CASE_B_EXCERPT = (
    "Customers of the mSecure password manager are being urged to act now to protect the confidential "
    "information they store in it, possibly by changing passwords, resetting two-factor authentication "
    "(2FA), and removing passkeys. The warning came in an email sent on November 3 in the name of "
    "developer mSeven Software. It says the company recently learned of suspicious activity linked to "
    "the app but does not say what happened or whether anyone's stored data was exposed."
)


def _item(title: str, body: str, *, category: str = "other", actionability: str = "informational",
          byline: str = "", source: str = "BleepingComputer") -> NewsItem:
    it = NewsItem(title=title, source=source, url=f"https://e.test/{abs(hash(title))}",
                  published_at=NOW, raw_content=body, category=category,
                  actionability_level=actionability, byline=byline)
    it.audience_targets = classify_audience(it)[0]
    return it


def case_a(**kw: str) -> NewsItem:
    return _item("Google Calendar phishing campaign hijacks sessions, bypasses MFA", CASE_A_EXCERPT,
                 category="phishing", **kw)


def case_b() -> NewsItem:
    return _item("mSecure Warns Users to Change Passwords, Reset 2FA and Passkeys After Suspicious Activity",
                 CASE_B_EXCERPT, category="other", actionability="urgent_action", source="The Hacker News")


def _brief(**fields: object) -> ThreatPost:
    base: dict[str, object] = dict(
        title="mSecure tells customers to replace saved passwords after suspicious activity",
        short_summary="The Hacker News reports that mSeven Software warned mSecure customers about "
                      "suspicious activity and advised password changes.",
        plain_summary="The maker of mSecure told customers to change saved passwords after spotting "
                      "suspicious activity linked to the app.",
        threat_level="High", why_it_matters="x", affected_users=["mSecure customers"],
        what_to_do=["Change your email password first."], language="en",
        source_fingerprint="f", generated_by="mock:test",
    )
    base.update(fields)
    return ThreatPost(**base)  # type: ignore[arg-type]


# ----------------------------------------------------------- Case A: AitM session theft
def test_case_a_is_observed_attacks_not_confirmed_exploitation() -> None:
    ev = assess(case_a())
    assert ev.exploitation == "attacks_observed"          # a campaign happened; no flaw "exploited"
    assert ev.campaign == "disrupted"                     # the excerpt: domains taken down
    assert "campaign_end_unconfirmed" in ev.unknowns      # a takedown is not a confirmed end
    assert extract_signals(case_a()).active_exploitation is False


def test_case_a_audience_is_workplace_not_the_public() -> None:
    it = case_a()
    assert "enterprise" in it.audience_targets and "normal_users" not in it.audience_targets
    sig = extract_signals(it)
    assert sig.enterprise_risk and sig.steals_sessions
    assert who_should_care(it, sig, language="en") == "Organisations and their IT teams"
    assert who_should_care(it, sig, language="ua") == "Організації та їхні ІТ-команди"


def test_case_a_sponsored_research_is_detected_from_the_byline() -> None:
    ev = assess(case_a(byline="Sponsored by Material Security"))
    assert ev.sponsored and ev.sponsor == "Material Security"
    assert assess(case_a()).sponsored is False            # never inferred without a marker


def test_case_a_campaign_status_conflict_is_flagged() -> None:
    post = _brief(why_it_matters="The campaign is still active and targets every Workspace user.")
    codes = {i.code for i in _evidence_issues(post, item=case_a())}
    assert "campaign_status_conflict" in codes


# ----------------------------------------------------------- Case B: suspicious activity
def test_case_b_is_suspected_and_exposure_is_not_confirmed() -> None:
    ev = assess(case_b())
    assert ev.exploitation == "suspected" and ev.compromise == "not_confirmed"
    assert "exposure_unconfirmed" in ev.unknowns and "scope_undisclosed" in ev.unknowns


def test_case_b_urgency_never_becomes_exploitation_or_exposure() -> None:
    it = case_b()
    sig = extract_signals(it)
    assert sig.active_exploitation is False and sig.requires_immediate_action is True
    labels = potential_impact(sig, language="en") + potential_impact(sig, language="ua")
    assert not any("xploit" in x or "Експлуатац" in x or x in ("Data exposure", "Витік даних") for x in labels)
    assert who_should_care(it, sig, language="en") == ""  # no "Cybersecurity professionals" catch-all


def test_case_b_unsupported_theft_claim_forces_review() -> None:
    post = _brief(why_it_matters="All saved vault secrets were stolen, so every account is compromised.")
    card = score_post(post, language="en", item=case_b(), threshold=0)
    assert "unsupported_compromise" in {i.code for i in card.issues}
    assert card.needs_review and any(r.startswith("evidence:") for r in card.review_reasons)


def test_case_b_conditional_wording_is_what_we_want() -> None:
    post = _brief(why_it_matters="If the vault data was accessed, every stored password could be used "
                                 "to sign in to email and banking.")
    assert not {i.code for i in _evidence_issues(post, item=case_b())} & {"unsupported_compromise"}
    ua = _brief(language="ua", why_it_matters="Якщо до сховища отримали доступ, паролі могли викрасти.")
    assert not {i.code for i in _evidence_issues(ua, item=case_b())} & {"unsupported_compromise"}


def test_case_b_unsupported_exploitation_label_forces_review() -> None:
    post = _brief(short_summary="mSecure is actively exploited, The Hacker News reports, and users "
                                "must change every password now.")
    assert "unsupported_exploitation" in {i.code for i in _evidence_issues(post, item=case_b())}


# ----------------------------------------------------------- evidence rules
def test_a_statistic_is_not_a_confirmation() -> None:
    it = _item("The 4 Elements of Exposure Prioritization", "Research states that fewer than 10% of "
               "vulnerabilities are exploited, yet most are treated as urgent.", category="vulnerability")
    assert assess(it).exploitation == "not_reported"


def test_negated_exploitation_never_confirms() -> None:
    it = _item("Vendor patches flaw", "There is no evidence that the flaw has been exploited in the wild.",
               category="vulnerability")
    assert assess(it).exploitation != "confirmed"


def test_kev_and_in_the_wild_confirm() -> None:
    for body in ("CISA has added the flaw to its Known Exploited Vulnerabilities (KEV) catalog.",
                 "Attackers are actively exploiting the bug, the vendor said.",
                 "CISA warns of hackers now exploiting critical Node2Shell flaw."):
        assert assess(_item("Flaw", body, category="vulnerability")).exploitation == "confirmed", body


def test_unpatched_flaw_without_exploitation_lists_the_gap() -> None:
    ev = assess(_item("Critical flaw in router firmware", "A patch is available for the bug.",
                      category="vulnerability"))
    assert ev.exploitation == "not_reported" and "exploitation_unconfirmed" in ev.unknowns


def test_campaign_status_wording() -> None:
    declined = assess(_item("Phishing wave", "Activity from this group appears to have dispersed.",
                            category="phishing"))
    returned = assess(_item("Malware campaign returns", "The campaign returns after a takedown in March.",
                            category="malware"))
    assert declined.campaign == "declined" and returned.campaign == "active"


def test_confirmed_breach_and_traced_theft() -> None:
    assert assess(_item("Harvard data breach exposed info of 851,000 accounts", "", category="breach")).compromise == "confirmed"
    poly = _item("Polymarket halts trading after crypto-draining script breach, $2.5M traced",
                 "The company is investigating.", category="breach")
    assert assess(poly).compromise == "confirmed"


# ----------------------------------------------------------- public text hygiene
def test_ai_authorship_in_a_brief_is_flagged_but_news_about_ai_is_not() -> None:
    bad = _brief(short_summary="This brief was generated by an AI language model from the report.")
    assert "ai_authorship" in {i.code for i in _evidence_issues(bad, item=None)}
    news = _brief(short_summary="Researchers found 16 Windows flaws with the MDASH AI system.")
    assert "ai_authorship" not in {i.code for i in _evidence_issues(news, item=None)}
    ua = _brief(language="ua", short_summary="Матеріал підготувала редакційна система на основі ШІ.")
    assert "ai_authorship" in {i.code for i in _evidence_issues(ua, item=None)}


def test_duplicated_recommendation_is_flagged() -> None:
    post = _brief(what_to_do=["Change your email password first."],
                  if_already_affected=["Change your email password first!"])
    assert "duplicate_recommendation" in {i.code for i in _evidence_issues(post, item=None)}


# ----------------------------------------------------------- prompt contract and cost guard
def test_prompt_states_the_evidence_rules_in_both_languages() -> None:
    from cyberalertx.ai import templates as t
    assert "EVIDENCE BEFORE CONCLUSIONS" in t._SHARED_RULES_EN and "Sponsored by" in t._SHARED_RULES_EN
    assert "СПЕРШУ ДОКАЗИ" in t._SHARED_RULES_UK and "Sponsored" in t._SHARED_RULES_UK
    assert "Workplace accounts" in t._SHARED_RULES_EN and "Робочі облікові записи" in t._SHARED_RULES_UK


def test_prompt_rules_did_not_grow() -> None:
    """Cost guard: the upgrade must not raise per-call input tokens (baseline
    measured on 4fa7a63: EN 30,794 and UA 34,388 characters)."""
    from cyberalertx.ai import templates as t
    assert len(t._SHARED_RULES_EN) <= 30794 and len(t._SHARED_RULES_UK) <= 34388


def test_byline_reaches_the_prompt_only_when_present() -> None:
    from cyberalertx.ai.templates import default_template_registry, render_prompts
    reg = default_template_registry()
    it = case_a(byline="Sponsored by Material Security")
    tpl = reg.select("en", it.category, "general")
    _, user = render_prompts(tpl, it, target_language="en")
    assert "- byline: Sponsored by Material Security" in user
    _, plain = render_prompts(tpl, case_a(), target_language="en")
    assert "byline" not in plain


def test_rss_keeps_the_feed_author_as_byline() -> None:
    """Real feedparser on a real RSS document: dc:creator becomes the byline."""
    import cyberalertx.sources.rss as rss
    feed = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>BC</title>
<item><title>Google Calendar phishing campaign hijacks sessions</title>
<link>https://e.test/a</link><dc:creator><![CDATA[Sponsored by Material Security]]></dc:creator>
<pubDate>Wed, 04 Nov 2026 13:00:10 GMT</pubDate><description><![CDATA[<p>Excerpt</p>]]></description></item>
<item><title>Plain story</title><link>https://e.test/b</link>
<pubDate>Wed, 04 Nov 2026 12:00:00 GMT</pubDate><description>Body</description></item>
</channel></rss>"""
    src = rss.RssSource.__new__(rss.RssSource)
    src.name = "BleepingComputer"
    items = rss.RssSource._parse(src, feed)
    assert [i.byline for i in items] == ["Sponsored by Material Security", ""]
    assert assess(items[0]).sponsored and assess(items[0]).sponsor == "Material Security"


def test_exploit_story_reporting_attacks_is_attacks_observed() -> None:
    """An exploit/zero-day story where attacks happened says so; a plain
    vulnerability report needs explicit exploitation wording."""
    attacked = _item("Ivanti Connect Secure gateways attacked for at least two weeks", "", category="zero-day")
    assert assess(attacked).exploitation == "attacks_observed"
    plain = _item("Barracuda devices can be taken over without a password", "Patches are available.",
                  category="vulnerability")
    assert assess(plain).exploitation == "not_reported"
