from datetime import datetime, timezone

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.filter import filter_relevant, is_relevant


def _item(title: str, body: str = "") -> NewsItem:
    return NewsItem(
        title=title,
        source="t",
        url=f"https://example.test/{abs(hash(title))}",
        published_at=datetime.now(timezone.utc),
        raw_content=body,
    )


def test_breach_passes():
    assert is_relevant(_item("Massive data breach hits health provider"))


def test_cve_phrase_passes():
    assert is_relevant(_item("Critical CVE-2024-9999 actively exploited in the wild"))


def test_zero_day_phrase_passes():
    assert is_relevant(_item("New zero-day in Chrome being exploited"))


def test_pure_corporate_drops():
    assert not is_relevant(_item("Acme Inc raises $50M Series B funding round"))


def test_listicle_drops():
    assert not is_relevant(_item("Top 10 best antivirus tools for 2026"))


def test_corporate_with_strong_security_signal_passes():
    assert is_relevant(_item(
        "After ransomware breach, Acme Inc raises $50M to rebuild security",
    ))


def test_filter_pipeline_returns_only_relevant():
    items = [
        _item("Critical RCE exploit released for Apache"),
        _item("Acme launches new HR product line"),
        _item("Phishing campaign targets Microsoft 365 users"),
    ]
    out = filter_relevant(items)
    assert {i.title for i in out} == {
        "Critical RCE exploit released for Apache",
        "Phishing campaign targets Microsoft 365 users",
    }
