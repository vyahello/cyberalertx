from datetime import datetime, timezone
from pathlib import Path

from cyberalertx.models import NewsItem
from cyberalertx.storage.json_store import JsonNewsStore


def _item(url: str, title: str = "title", score: float = 1.0) -> NewsItem:
    return NewsItem(
        title=title,
        source="s",
        url=url,
        published_at=datetime.now(timezone.utc),
        raw_content="",
        threat_score=score,
    )


def test_upsert_returns_only_new(tmp_path: Path) -> None:
    store = JsonNewsStore(tmp_path / "items.json")
    first = [_item("https://a.test/1"), _item("https://a.test/2")]
    assert {i.url for i in store.upsert_many(first)} == {"https://a.test/1", "https://a.test/2"}

    second = [_item("https://a.test/2"), _item("https://a.test/3")]
    new = store.upsert_many(second)
    assert {i.url for i in new} == {"https://a.test/3"}


def test_round_trip_through_disk(tmp_path: Path) -> None:
    path = tmp_path / "items.json"
    JsonNewsStore(path).upsert_many([_item("https://a.test/1", score=42.5)])
    reopened = JsonNewsStore(path)
    items = reopened.all()
    assert len(items) == 1
    assert items[0].threat_score == 42.5
    assert items[0].url == "https://a.test/1"


def test_max_items_trims_lowest_score(tmp_path: Path) -> None:
    store = JsonNewsStore(tmp_path / "items.json", max_items=2)
    store.upsert_many([
        _item("https://a.test/1", score=10),
        _item("https://a.test/2", score=20),
        _item("https://a.test/3", score=30),
    ])
    scores = sorted(i.threat_score for i in store.all())
    assert scores == [20.0, 30.0]
