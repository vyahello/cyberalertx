from datetime import datetime, timezone

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.actionability import analyze_actionability


def _item(title: str, body: str = "", *, category: str = "other") -> NewsItem:
    return NewsItem(
        title=title,
        source="t",
        url=f"https://e.test/{abs(hash((title, body)))}",
        published_at=datetime.now(timezone.utc),
        raw_content=body,
        category=category,
    )


# ---------- spec examples ----------

def test_enable_2fa_immediately_is_urgent():
    item = _item(
        "Massive breach — enable 2FA immediately",
        body="Following the breach disclosure, users should enable 2FA immediately.",
        category="breach",
    )
    level, score = analyze_actionability(item)
    assert level == "urgent_action"
    assert score >= 0.7


def test_patch_available_for_chrome_is_recommended():
    item = _item(
        "Patch available for Chrome to address critical bug",
        body="Google released a patch available now; users should update Chrome.",
        category="vulnerability",
    )
    level, score = analyze_actionability(item)
    assert level == "recommended_action"
    assert 0.4 <= score < 0.7


def test_theoretical_research_is_informational():
    item = _item(
        "Researchers discovered theoretical attack on RSA",
        body="A research paper presents a theoretical attack with proof of concept; no exploitation observed.",
        category="other",
    )
    level, _ = analyze_actionability(item)
    assert level == "informational"


# ---------- specific signal coverage ----------

def test_active_exploitation_pushes_urgent():
    item = _item(
        "Critical flaw actively exploited in the wild",
        body="The flaw is being exploited in ongoing campaigns against enterprise targets.",
        category="exploit",
    )
    level, _ = analyze_actionability(item)
    assert level == "urgent_action"


def test_credentials_stolen_pushes_urgent():
    item = _item(
        "Major site breach: credentials stolen, sessions hijacked",
        body="Attackers exfiltrated databases; credentials stolen and session tokens stolen.",
        category="breach",
    )
    level, _ = analyze_actionability(item)
    assert level == "urgent_action"


def test_mitigation_workaround_is_recommended():
    item = _item(
        "Apache flaw disclosed, workaround available",
        body="No patch yet, but a workaround available pending a fix; users at risk.",
        category="vulnerability",
    )
    level, _ = analyze_actionability(item)
    assert level == "recommended_action"


def test_generic_news_with_no_signals_is_informational():
    item = _item(
        "Annual security conference announces speaker lineup",
        body="The annual report covers industry trends.",
        category="other",
    )
    level, _ = analyze_actionability(item)
    assert level == "informational"


def test_zero_day_category_lifts_borderline_items():
    # No urgent/recommended phrases — but the zero-day category should push
    # this beyond pure informational territory.
    item_other = _item("Researchers found theoretical flaw", category="other")
    item_zero_day = _item("Researchers found theoretical flaw", category="zero-day")
    _, score_other = analyze_actionability(item_other)
    _, score_zd = analyze_actionability(item_zero_day)
    assert score_zd > score_other


# ---------- score invariants ----------

def test_score_is_within_unit_interval():
    item = _item(
        "Emergency patch released for actively exploited zero-day; enable 2FA immediately",
        body="Mass exploitation observed; rotate credentials and reset passwords now.",
        category="zero-day",
    )
    _, score = analyze_actionability(item)
    assert 0.0 <= score <= 1.0


def test_level_thresholds_consistent_with_score():
    """The string level must agree with the numeric score thresholds."""
    item = _item("Patch available, users should update", category="vulnerability")
    level, score = analyze_actionability(item)
    if score >= 0.7:
        assert level == "urgent_action"
    elif score >= 0.4:
        assert level == "recommended_action"
    else:
        assert level == "informational"
