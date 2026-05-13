"""Dual-write store contracts:

  DualWriteNewsStore (news_items):
    * reads → primary (JSON) only
    * writes → both
    * secondary exception → swallowed, primary result returned

  DualWriteThreatPostCache (AI cache):
    * reads → PG-preferred with JSON fallback (on PG miss or exception)
    * writes → both
    * secondary exception → swallowed; read_fallbacks counter tracked
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, List

from cyberalertx.models import NewsItem
from cyberalertx.storage.base import NewsRepository
from cyberalertx.storage.dual_write import DualWriteNewsStore


@dataclass
class _RecordingStore(NewsRepository):
    """Minimal in-memory store that records every method call."""
    items: dict[str, NewsItem] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    raise_on_upsert: bool = False

    def known_fingerprints(self) -> set[str]:
        self.calls.append("known_fingerprints")
        return set(self.items)

    def all(self) -> List[NewsItem]:
        self.calls.append("all")
        return list(self.items.values())

    def upsert_many(self, items: Iterable[NewsItem]) -> List[NewsItem]:
        self.calls.append("upsert_many")
        if self.raise_on_upsert:
            raise RuntimeError("simulated PG outage")
        new = []
        for it in items:
            if it.fingerprint not in self.items:
                new.append(it)
            self.items[it.fingerprint] = it
        return new


def _item(url: str = "https://example.test/a") -> NewsItem:
    return NewsItem(
        title="t",
        source="s",
        url=url,
        published_at=datetime.now(timezone.utc),
        raw_content="body",
    )


def test_reads_come_from_primary_only():
    primary = _RecordingStore()
    secondary = _RecordingStore()
    dual = DualWriteNewsStore(primary=primary, secondary=secondary)
    dual.known_fingerprints()
    dual.all()
    assert primary.calls == ["known_fingerprints", "all"]
    assert secondary.calls == []  # secondary never queried


def test_writes_fan_out_to_both():
    primary = _RecordingStore()
    secondary = _RecordingStore()
    dual = DualWriteNewsStore(primary=primary, secondary=secondary)
    item = _item()
    dual.upsert_many([item])
    assert primary.calls == ["upsert_many"]
    assert secondary.calls == ["upsert_many"]
    assert item.fingerprint in primary.items
    assert item.fingerprint in secondary.items


def test_secondary_exception_does_not_break_primary_write():
    primary = _RecordingStore()
    secondary = _RecordingStore(raise_on_upsert=True)
    dual = DualWriteNewsStore(primary=primary, secondary=secondary)
    item = _item()
    # MUST not raise.
    result = dual.upsert_many([item])
    assert primary.items, "primary write must have happened"
    assert result == [item], "primary's return value must be propagated"


def test_shadow_stats_track_success_and_failure():
    primary = _RecordingStore()
    secondary = _RecordingStore()
    dual = DualWriteNewsStore(primary=primary, secondary=secondary)
    dual.upsert_many([_item(url="https://a.test/1")])
    dual.upsert_many([_item(url="https://a.test/2")])
    assert dual.shadow_stats == {"successes": 2, "failures": 0}

    secondary.raise_on_upsert = True
    dual.upsert_many([_item(url="https://a.test/3")])
    assert dual.shadow_stats == {"successes": 2, "failures": 1}


def test_return_value_is_primary_not_secondary():
    """Primary's notion of 'new' is authoritative even if secondary disagrees."""
    primary = _RecordingStore()
    secondary = _RecordingStore()
    # Pre-populate secondary with the same fingerprint, so secondary would
    # return [] (not new), but primary should return [item] (new).
    item = _item()
    secondary.items[item.fingerprint] = item
    dual = DualWriteNewsStore(primary=primary, secondary=secondary)
    result = dual.upsert_many([item])
    assert result == [item]
    # Secondary still received the call.
    assert secondary.calls == ["upsert_many"]


def test_items_iterable_consumed_only_once():
    """Edge case: the orchestrator could pass a single-use iterator."""
    primary = _RecordingStore()
    secondary = _RecordingStore()
    dual = DualWriteNewsStore(primary=primary, secondary=secondary)
    item = _item()
    dual.upsert_many(iter([item]))  # single-use generator
    assert item.fingerprint in primary.items
    assert item.fingerprint in secondary.items


# ============================================================================
# DualWriteThreatPostCache
# ============================================================================

from cyberalertx.ai.models import ThreatPost
from cyberalertx.storage.dual_write import DualWriteThreatPostCache


@dataclass
class _RecordingThreatStore:
    """In-memory ThreatPostStore that records calls and can raise on demand."""
    posts: dict[tuple[str, str], ThreatPost] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    raise_on_get: bool = False
    raise_on_set: bool = False

    def get(self, fingerprint: str, locale: str = "en"):
        self.calls.append(f"get:{fingerprint}/{locale}")
        if self.raise_on_get:
            raise RuntimeError("simulated PG outage on read")
        return self.posts.get((fingerprint, locale))

    def set(self, fingerprint: str, locale: str, post: ThreatPost) -> None:
        self.calls.append(f"set:{fingerprint}/{locale}")
        if self.raise_on_set:
            raise RuntimeError("simulated PG outage on write")
        self.posts[(fingerprint, locale)] = post

    def all(self):
        return iter(self.posts.values())

    def __len__(self):
        return len(self.posts)


def _post(title: str = "t") -> ThreatPost:
    return ThreatPost(
        title=title, short_summary="s", threat_level="Low",
        why_it_matters="w", affected_users=["a"], what_to_do=["b"],
        generated_by="anthropic", language="en",
    )


def test_threat_get_prefers_json_for_speed():
    """JSON cache is in-memory and mirrored to PG; we read it first to
    avoid a Supabase round-trip per item on every feed render."""
    json_cache = _RecordingThreatStore(posts={("fp1", "en"): _post("from-JSON")})
    pg = _RecordingThreatStore(posts={("fp1", "en"): _post("from-PG")})
    dual = DualWriteThreatPostCache(primary=json_cache, secondary=pg)
    result = dual.get("fp1", "en")
    assert result.title == "from-JSON"
    # PG was not consulted — JSON hit short-circuits.
    assert "get:fp1/en" in json_cache.calls
    assert pg.calls == []


def test_threat_get_falls_back_to_pg_on_json_miss():
    """JSON returns None → PG consulted next. Covers the case where PG has
    an entry JSON doesn't (peer process wrote it, or a manual SQL import)."""
    json_cache = _RecordingThreatStore()  # JSON empty
    pg = _RecordingThreatStore(posts={("fp1", "en"): _post("from-PG")})
    dual = DualWriteThreatPostCache(primary=json_cache, secondary=pg)
    result = dual.get("fp1", "en")
    assert result.title == "from-PG"
    assert json_cache.calls == ["get:fp1/en"]
    assert pg.calls == ["get:fp1/en"]


def test_threat_get_pg_exception_swallowed_returns_miss():
    """PG fallback raising must NEVER kill the request — log and treat as miss."""
    json_cache = _RecordingThreatStore()  # JSON empty so PG fallback fires
    pg = _RecordingThreatStore(raise_on_get=True)
    dual = DualWriteThreatPostCache(primary=json_cache, secondary=pg)
    result = dual.get("fp1", "en")
    assert result is None
    assert dual.shadow_stats["read_fallbacks"] == 1


def test_threat_set_writes_to_both():
    json_cache = _RecordingThreatStore()
    pg = _RecordingThreatStore()
    dual = DualWriteThreatPostCache(primary=json_cache, secondary=pg)
    post = _post()
    dual.set("fp1", "en", post)
    assert ("fp1", "en") in json_cache.posts
    assert ("fp1", "en") in pg.posts


def test_threat_set_pg_exception_does_not_break_json_write():
    json_cache = _RecordingThreatStore()
    pg = _RecordingThreatStore(raise_on_set=True)
    dual = DualWriteThreatPostCache(primary=json_cache, secondary=pg)
    dual.set("fp1", "en", _post())  # must NOT raise
    assert ("fp1", "en") in json_cache.posts
    assert ("fp1", "en") not in pg.posts
    assert dual.shadow_stats["failures"] == 1


def test_threat_shadow_stats_tracking():
    json_cache = _RecordingThreatStore()
    pg = _RecordingThreatStore()
    dual = DualWriteThreatPostCache(primary=json_cache, secondary=pg)
    dual.set("fp1", "en", _post())
    dual.set("fp2", "en", _post())
    assert dual.shadow_stats == {"successes": 2, "failures": 0, "read_fallbacks": 0}
