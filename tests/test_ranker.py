from datetime import datetime, timedelta, timezone

from cyberalertx.models import NewsItem
from cyberalertx.pipeline.ranker import score_items


NOW = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)


def _item(title: str, source: str, age_hours: float = 0.0, body: str = "") -> NewsItem:
    return NewsItem(
        title=title,
        source=source,
        url=f"https://{source}.test/{abs(hash((title, source)))}",
        published_at=NOW - timedelta(hours=age_hours),
        raw_content=body,
    )


def test_recent_critical_beats_old_mild():
    items = [
        _item("Generic phishing tips published", "blog", age_hours=2),
        _item("Critical zero-day actively exploited in Windows", "hn", age_hours=1,
              body="Microsoft confirms RCE, emergency patch issued"),
    ]
    score_items(items, now=NOW)
    assert items[0].title.startswith("Critical zero-day")
    assert items[0].threat_score > items[1].threat_score


def test_recency_decays_score():
    fresh = _item("Critical RCE exploited in wild", "a", age_hours=0)
    stale = _item("Critical RCE exploited in wild", "b", age_hours=72)
    score_items([fresh, stale], now=NOW, half_life_hours=12)
    assert fresh.threat_score > stale.threat_score


def test_cross_source_bonus_lifts_score():
    solo = [_item("New ransomware strain hits hospitals", "src1")]
    crowd = [
        _item("New ransomware strain hits hospitals", "src1"),
        _item("Ransomware strain devastates hospital network", "src2"),
        _item("Hospitals worldwide hit by new ransomware", "src3"),
    ]
    score_items(solo, now=NOW)
    score_items(crowd, now=NOW)
    # The src1 item in `crowd` should outscore the identical solo item.
    solo_score = solo[0].threat_score
    crowd_src1 = next(i for i in crowd if i.source == "src1").threat_score
    assert crowd_src1 > solo_score


def test_score_is_clamped_to_100():
    item = _item(
        "Critical zero-day actively exploited wormable RCE",
        "x",
        age_hours=0,
        body="critical critical zero-day rce actively exploited wormable emergency patch",
    )
    score_items([item], now=NOW)
    assert 0.0 <= item.threat_score <= 100.0
