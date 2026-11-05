"""Follow-ups after the 5 Nov 2026 cutover: unique story keys, test isolation
of the media store, and the Telegram activation cutoff."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cyberalertx.models import NewsItem
from cyberalertx.publish.config import activation_time
from cyberalertx.publish.destinations import INELIGIBLE, DeliveryError
from cyberalertx.publish.jobs import JobStore
from cyberalertx.publish.ledger import PublishLedger
from cyberalertx.publish.orchestrator import PublishPolicy, plan
from tests.test_publication import NOW, go, item, settings, setup, statuses, view

# ------------------------------------------------------------------ 1. story keys


def _member(fp: str, key: str, hours: float = 1) -> Any:
    return SimpleNamespace(fingerprint=fp, story_key=key, published_at=NOW - timedelta(hours=hours))


def test_a_taken_fallback_never_produces_a_duplicate_key() -> None:
    """The production case: story A owns stored key K; story B's own key is
    taken AND its cluster key is K too. B used to get K as well."""
    from cyberalertx.intel.story import stable_key
    k = "s:40543bd55ed092"
    used = {k}
    b = stable_key(k, [_member("de1cf247", k), _member("4432f1db", "")], used)
    assert b != k and b.startswith("s:") and len(b) == 16
    assert b == stable_key(k, [_member("4432f1db", ""), _member("de1cf247", k)], {k})   # deterministic
    used.add(b)
    c = stable_key(k, [_member("de1cf247", k), _member("4432f1db", "")], used)         # even again: unique
    assert c not in used


def test_stable_key_still_prefers_the_stored_key_then_the_cluster_key() -> None:
    from cyberalertx.intel.story import stable_key
    assert stable_key("s:cluster", [_member("a", "s:stored")], set()) == "s:stored"
    assert stable_key("s:cluster", [_member("a", "s:stored")], {"s:stored"}) == "s:cluster"
    assert stable_key("s:cluster", [_member("a", "")], set()) == "s:cluster"


def test_distinct_stories_never_share_a_canonical_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every story gets its own key, hence its own `illus:{key}` asset."""
    from cyberalertx.intel import story as story_mod
    k = "s:40543bd55ed092"
    a = NewsItem(title="NetamLoader hits custom Windows 10", source="Securelist", url="https://e.test/a",
                 published_at=NOW - timedelta(days=7), raw_content="x", story_key=k)
    b1 = NewsItem(title="VOLTA-AUTODOXER steals Windows data", source="dev.ua", url="https://e.test/b1",
                  published_at=NOW - timedelta(days=3), raw_content="x", story_key=k)
    b2 = NewsItem(title="VOLTA-AUTODOXER asks Claude to rate victims", source="ain.ua", url="https://e.test/b2",
                  published_at=NOW - timedelta(days=3), raw_content="x")

    def clusters(items: list[NewsItem]) -> list[Any]:
        by = {i.url: i for i in items}
        return [SimpleNamespace(key=k, anchor=by["https://e.test/a"], members=[by["https://e.test/a"]]),
                SimpleNamespace(key=k, anchor=by["https://e.test/b1"], members=[by["https://e.test/b1"],
                                                                            by["https://e.test/b2"]])]
    monkeypatch.setattr(story_mod.dedup, "cluster_items", clusters)
    stories = story_mod.build_stories([a, b1, b2])
    keys = [s.key for s in stories]
    assert len(keys) == len(set(keys)) == 2
    assert len({f"illus:{key}" for key in keys}) == 2


# ------------------------------------------------------------------ 2. test isolation

def test_tests_never_touch_the_real_media_store() -> None:
    from cyberalertx.config import DATA_DIR
    from cyberalertx.media import assets
    store = assets.MediaStore()
    assert Path(DATA_DIR).resolve() not in store.root.resolve().parents
    assert store.root.resolve() != (Path(DATA_DIR) / "media").resolve()


def test_tests_never_see_the_hosts_activation_marker() -> None:
    assert activation_time() is None


# ------------------------------------------------------------------ 3. activation cutoff

CUTOFF = NOW - timedelta(hours=1)


def test_activation_time_from_env_or_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "STAGE_D_AUTHORIZED"
    marker.write_text("")
    t = datetime(2026, 11, 5, 15, 33, 58, tzinfo=timezone.utc).timestamp()
    os.utime(marker, (t, t))
    monkeypatch.setenv("CYBERALERTX_TELEGRAM_MARKER", str(marker))
    assert activation_time() == datetime(2026, 11, 5, 15, 33, 58, tzinfo=timezone.utc)
    monkeypatch.setenv("CYBERALERTX_TELEGRAM_ACTIVATED_AT", "2026-11-05T16:00:00Z")
    assert activation_time() == datetime(2026, 11, 5, 16, 0, tzinfo=timezone.utc)


def test_a_story_from_before_activation_is_never_sent_even_if_rendered_later(tmp_path: Path) -> None:
    old, new = item(1, hours_ago=3), item(2, hours_ago=0.5)          # cutoff: 1 h ago
    s = settings(activated_at=CUTOFF)
    store, src, d, bot = setup(tmp_path, s=s)                         # nothing rendered yet
    src._items = [old, new]
    from tests.test_publication import source_for
    src.payloads = source_for(old, new).payloads                     # editions finish after activation
    plan(src, store, now=NOW, settings=s, destinations=d, view=view(old, new), policy=PublishPolicy(),
         ledger_has=PublishLedger(tmp_path / "ledger.jsonl").is_published)
    st = statuses(store)
    assert all(st[f"s:0001:{loc}:telegram:initial"] == "cancelled" for loc in ("en", "ua"))
    assert all(st[f"s:0002:{loc}:telegram:initial"] == "scheduled" for loc in ("en", "ua"))
    go(store, src, d)
    texts = [b.get("text", "") + b.get("caption", "") for b in bot.sent()]
    assert texts and all("Story 1" not in t for t in texts) and any("Story 2" in t for t in texts)
    assert statuses(store)["s:0001:en:website:initial"] == "published"   # the website is unaffected
    # Idempotent: planning again neither revives nor duplicates the cancelled job.
    plan(src, store, now=NOW, settings=s, destinations=d, view=view(old, new), policy=PublishPolicy())
    assert statuses(store)["s:0001:en:telegram:initial"] == "cancelled"


def test_queued_jobs_from_before_activation_are_cancelled_before_claiming(tmp_path: Path) -> None:
    old = item(1, hours_ago=3)
    store, src, d, bot = setup(tmp_path, old)                         # planned while no cutoff existed
    assert statuses(store)["s:0001:en:telegram:initial"] == "scheduled"
    d["telegram"].settings = settings(activated_at=CUTOFF)           # then Telegram is activated
    rep = go(store, src, d)
    assert statuses(store)["s:0001:en:telegram:initial"] == "cancelled"
    assert any("before Telegram activation" in c["reason"] for c in rep.cancelled)
    assert not [b for b in bot.sent() if "Story 1" in b.get("text", "") + b.get("caption", "")]


def test_prepare_refuses_as_the_last_guard() -> None:
    from cyberalertx.publish.destinations import TelegramDestination
    dest = TelegramDestination(settings(activated_at=CUTOFF), ledger_path=Path("/nonexistent/l.jsonl"))
    job = SimpleNamespace(locale="en", publication_type="initial",
                          article_published_at=(CUTOFF - timedelta(minutes=1)).isoformat())
    with pytest.raises(DeliveryError) as exc:
        dest.prepare(job, {"id": "x", "translations": {"en": {"title": "T"}}})
    assert exc.value.category == INELIGIBLE


def test_ledger_import_and_the_48h_window_are_unchanged(tmp_path: Path) -> None:
    sent_before, ancient = item(1, hours_ago=3), item(2, hours_ago=60)
    PublishLedger(tmp_path / "ledger.jsonl").record(fingerprint=sent_before.fingerprint, locale="en",
                                                   channel="@fake_en", message_id=1)
    store, src, d, bot = setup(tmp_path, sent_before, ancient, s=settings(activated_at=CUTOFF))
    st = statuses(store)
    assert st["s:0001:en:telegram:initial"] == "published"            # imported from the ledger, as before
    assert "s:0002:en:telegram:initial" not in st                     # outside the window: no job at all
    go(store, src, d)
    assert not bot.sent("sendPhoto") and not [b for b in bot.sent("sendMessage")]
