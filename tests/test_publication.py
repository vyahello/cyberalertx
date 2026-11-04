"""Publication engine: job planning, idempotency, website and Telegram delivery,
retries, recovery, scheduling, operator actions and admin visibility.

Isolated job stores and ledgers (tmp_path), fake editions, a mocked Telegram
transport (httpx.MockTransport) and fake channel ids. No network, no live
channel, no production data.
"""
from __future__ import annotations

import base64
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from cyberalertx.models import NewsItem
from cyberalertx.publish.config import TelegramSettings
from cyberalertx.publish.destinations import TelegramDestination, WebsiteDestination
from cyberalertx.publish.jobs import JobStore, PublicationJob, RetryPolicy
from cyberalertx.publish.ledger import PublishLedger
from cyberalertx.publish.orchestrator import (
    ActionError, IntelView, PublishPolicy, cancel_job, plan, reconcile_job, retry_job, run,
)
from cyberalertx.publish.telegram import TelegramError, TelegramPublisher

NOW = datetime(2026, 11, 3, 10, 0, tzinfo=timezone.utc)
BASE = "https://cyberalertx.com"


# ---------------------------------------------------------------- fixtures

def item(n: int, *, language: str = "en", hours_ago: float = 2, tier: str = "trusted",
         relevance: str = "") -> NewsItem:
    it = NewsItem(title=f"Story {n}", source="BleepingComputer", url=f"https://e.test/{n}",
                  published_at=NOW - timedelta(hours=hours_ago), raw_content="body", language=language,
                  source_tier=tier, story_key=f"s:{n:04d}")
    if relevance:
        it.relevance_status = relevance
    return it


def payload(it: NewsItem, locales: tuple[str, ...] = ("en", "ua"), level: str = "Critical",
            title_suffix: str = "") -> dict[str, Any]:
    text = {
        "en": {"title": f"Widget flaw {it.title}{title_suffix}", "short_summary": "Attackers exploit Widget.",
               "plain_summary": "Attackers exploit Widget servers.", "what_to_do": ["Patch Widget now"]},
        "ua": {"title": f"Ваду у Widget {it.title}{title_suffix}", "short_summary": "Зловмисники атакують Widget.",
               "plain_summary": "Зловмисники атакують сервери Widget.", "what_to_do": ["Оновіть Widget"]},
    }
    return {"id": it.fingerprint, "source": it.source, "source_url": it.url, "threat_level": level,
            "actionability_level": "urgent_action", "category": "vulnerability",
            "published_at": it.published_at.isoformat(), "available_locales": list(locales),
            "translations": {loc: text[loc] for loc in locales}}


class FakeSource:
    def __init__(self, items: list[NewsItem], payloads: dict[tuple[str, str], dict[str, Any]],
                 review: dict[tuple[str, str], str] | None = None) -> None:
        self._items, self.payloads, self.review = items, payloads, review or {}

    def items(self) -> list[NewsItem]:
        return list(self._items)

    def payload(self, it: NewsItem, locale: str) -> dict[str, Any] | None:
        if self.review.get((it.fingerprint, locale)) in ("rejected", "held"):
            return None
        p = self.payloads.get((it.fingerprint, locale))
        return dict(p) if p else None

    def review_status(self, fp: str, locale: str) -> str:
        return self.review.get((fp, locale), "auto" if (fp, locale) in self.payloads else "missing")


def source_for(*items_: NewsItem, locales: tuple[str, ...] = ("en", "ua"), **kw: Any) -> FakeSource:
    pays: dict[tuple[str, str], dict[str, Any]] = {}
    for it in items_:
        p = payload(it, locales, **kw)
        for loc in locales:
            pays[(it.fingerprint, loc)] = p
    return FakeSource(list(items_), pays)


def view(*items_: NewsItem, breaking: dict[str, str] | None = None, top: dict[str, int] | None = None) -> IntelView:
    return IntelView(story_of={i.fingerprint: i.story_key for i in items_},
                     members={i.story_key: [i.fingerprint] for i in items_},
                     top_rank=top or {}, breaking=breaking or {},
                     relevance={i.story_key: getattr(i, "relevance_status", "") or "in_scope" for i in items_})


def settings(**kw: Any) -> TelegramSettings:
    base: dict[str, Any] = dict(bot_token="123:FAKE", channels={"en": "@fake_en", "ua": "@fake_ua"},
                                send_delay_seconds=0.0, public_base_url=BASE, limit=5)
    base.update(kw)
    return TelegramSettings(**base)


class Bot:
    """A mocked Bot API. `script` maps a method to a list of responses or exceptions."""

    def __init__(self, script: dict[str, list[Any]] | None = None) -> None:
        self.script = script or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.next_id = 500
        self.lock = threading.Lock()

    def handler(self, req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[-1]
        with self.lock:
            self.calls.append((method, json.loads(req.content)))
            queue = self.script.get(method) or []
            out = queue.pop(0) if queue else None
            if out is None:
                self.next_id += 1
                return httpx.Response(200, json={"ok": True, "result": {"message_id": self.next_id}})
        if isinstance(out, BaseException):
            raise out
        return out

    def factory(self) -> Callable[[], TelegramPublisher]:
        return lambda: TelegramPublisher("123:FAKE", api_base="https://fake.invalid",
                                         client=httpx.Client(transport=httpx.MockTransport(self.handler)),
                                         max_retry_after_seconds=0)

    def sent(self, method: str | None = None) -> list[dict[str, Any]]:
        return [b for m, b in self.calls if method is None or m == method]


def dests(tmp_path: Path, bot: Bot, s: TelegramSettings | None = None) -> dict[str, Any]:
    s = s or settings()
    return {"website": WebsiteDestination(BASE),
            "telegram": TelegramDestination(s, ledger_path=tmp_path / "ledger.jsonl",
                                            publisher_factory=bot.factory())}


def setup(tmp_path: Path, *items_: NewsItem, bot: Bot | None = None, s: TelegramSettings | None = None,
          v: IntelView | None = None, policy: PublishPolicy | None = None, src: FakeSource | None = None,
          now: datetime = NOW) -> tuple[JobStore, FakeSource, dict[str, Any], Bot]:
    bot = bot or Bot()
    s = s or settings()
    store = JobStore(tmp_path / "jobs.json")
    src = src or source_for(*items_)
    d = dests(tmp_path, bot, s)
    plan(src, store, now=now, settings=s, destinations=d, view=v or view(*items_),
         policy=policy or PublishPolicy(), ledger_has=PublishLedger(tmp_path / "ledger.jsonl").is_published)
    return store, src, d, bot


def statuses(store: JobStore) -> dict[str, str]:
    return {j.job_id: j.status for j in store.all()}


def go(store: JobStore, src: FakeSource, d: dict[str, Any], now: datetime = NOW, **kw: Any) -> Any:
    return run(src, store, d, now=now, clock=lambda: now, rng=lambda: 0.5, **kw)


# ---------------------------------------------------------------- job creation

def test_eligible_story_gets_one_job_per_destination_and_locale(tmp_path: Path) -> None:
    it = item(1)
    store, *_ = setup(tmp_path, it)
    assert sorted(statuses(store)) == sorted(f"s:0001:{loc}:{d}:initial" for d in ("telegram", "website")
                                             for loc in ("en", "ua"))
    assert set(statuses(store).values()) == {"scheduled"}
    j = store.get("s:0001:ua:telegram:initial")
    assert j and j.fingerprint == it.fingerprint and j.members == [it.fingerprint] and j.max_attempts == 5


def test_out_of_scope_story_gets_no_jobs(tmp_path: Path) -> None:
    store, *_ = setup(tmp_path, item(1, relevance="out_of_scope"))
    assert store.all() == []


def test_missing_locale_creates_no_job_for_it(tmp_path: Path) -> None:
    it = item(1)
    store, *_ = setup(tmp_path, it, src=source_for(it, locales=("en",)))
    assert all(":en:" in k for k in statuses(store))


def test_planning_twice_creates_nothing_new(tmp_path: Path) -> None:
    it = item(1)
    store, src, d, _ = setup(tmp_path, it)
    again = plan(src, store, now=NOW + timedelta(minutes=5), settings=settings(), destinations=d,
                 view=view(it), policy=PublishPolicy())
    assert again.created == [] and len(store.all()) == 4


def test_story_already_sent_by_the_legacy_publisher_is_imported_not_resent(tmp_path: Path) -> None:
    it = item(1)
    PublishLedger(tmp_path / "ledger.jsonl").record(fingerprint=it.fingerprint, locale="en",
                                                    channel="@fake_en", message_id=77)
    store, src, d, bot = setup(tmp_path, it)
    assert store.get("s:0001:en:telegram:initial").status == "published"   # type: ignore[union-attr]
    go(store, src, d)
    assert [b["chat_id"] for b in bot.sent()] == ["@fake_ua"]


def test_archive_and_policy_gates(tmp_path: Path) -> None:
    old, low, ua_src, bronze = item(1, hours_ago=100), item(2), item(3, language="ua"), item(4, tier="unverified")
    src = source_for(old, ua_src, bronze)
    src.payloads.update({(low.fingerprint, loc): payload(low, level="Low") for loc in ("en", "ua")})
    src.payloads[(low.fingerprint, "en")]["actionability_level"] = "informational"
    src.payloads[(low.fingerprint, "ua")]["actionability_level"] = "informational"
    src._items.append(low)
    store, *_ = setup(tmp_path, old, low, ua_src, bronze, src=src)
    keys = set(statuses(store))
    assert not any(k.startswith("s:0001") for k in keys)                       # outside the window
    assert {"s:0002:en:website:initial", "s:0002:ua:website:initial"} <= keys
    assert not any(k.startswith("s:0002") and "telegram" in k for k in keys)   # below the severity bar
    assert "s:0003:ua:telegram:initial" in keys and "s:0003:en:telegram:initial" not in keys  # language gate
    assert not any(k.startswith("s:0004") and "telegram" in k for k in keys)   # source tier


def test_held_edition_gets_no_job_until_it_is_visible(tmp_path: Path) -> None:
    it = item(1)
    src = source_for(it)
    src.review[(it.fingerprint, "ua")] = "held"
    store, *_ = setup(tmp_path, it, src=src)
    assert not any(":ua:" in k for k in statuses(store))
    del src.review[(it.fingerprint, "ua")]
    plan(src, store, now=NOW, settings=settings(), destinations=dests(tmp_path, Bot()), view=view(it))
    assert "s:0001:ua:website:initial" in statuses(store)


# ---------------------------------------------------------------- delivery & idempotency

def test_all_four_destinations_deliver_with_localized_content(tmp_path: Path) -> None:
    it = item(1)
    store, src, d, bot = setup(tmp_path, it)
    rep = go(store, src, d)
    assert len(rep.published) == 4 and set(statuses(store).values()) == {"published"}
    msgs = {b["chat_id"]: b["text"] for b in bot.sent("sendMessage")}
    assert "Widget flaw Story 1" in msgs["@fake_en"] and "Ваду у Widget Story 1" in msgs["@fake_ua"]
    assert f"{BASE}/ua/threat/{it.fingerprint}" in msgs["@fake_ua"]
    web = store.get("s:0001:ua:website:initial")
    assert web and web.published_url == f"{BASE}/ua/threat/{it.fingerprint}" and web.external_id == it.fingerprint
    assert web.media_url.startswith(f"{BASE}/ua/threat/{it.fingerprint}/card/og.png?v=") and web.content_hash
    tg = store.get("s:0001:en:telegram:initial")
    assert tg and tg.external_id.isdigit() and PublishLedger(tmp_path / "ledger.jsonl").is_published(it.fingerprint, "en")


def test_second_run_sends_nothing(tmp_path: Path) -> None:
    store, src, d, bot = setup(tmp_path, item(1))
    go(store, src, d)
    rep = go(store, src, d, now=NOW + timedelta(hours=1))
    assert rep.published == [] and len(bot.sent()) == 2


def test_two_concurrent_workers_never_send_the_same_job(tmp_path: Path) -> None:
    items_ = [item(n) for n in range(1, 7)]
    bot = Bot()
    store, src, _, _ = setup(tmp_path, *items_, bot=bot)
    barrier = threading.Barrier(4)

    def worker(n: int) -> None:
        barrier.wait()
        run(src, JobStore(tmp_path / "jobs.json"), dests(tmp_path, bot), now=NOW, clock=lambda: NOW,
            worker=f"w{n}", rng=lambda: 0.5)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    chats = [(b["chat_id"], b["text"].split("\n")[0]) for b in bot.sent()]
    assert len(chats) == len(set(chats)) == 12
    assert set(statuses(store).values()) == {"published"}


def test_crash_mid_run_recovers_without_resending(tmp_path: Path) -> None:
    store, src, d, bot = setup(tmp_path, item(1))
    claimed = store.claim(NOW, "dead-worker", lease_s=60)
    assert len(claimed) == 4
    for jid in ("s:0001:en:telegram:initial", "s:0001:en:website:initial"):
        store.update(jid, lambda j: setattr(j, "phase", "sending"), NOW)
    # Before the lease ends nobody else may touch them.
    assert go(store, src, d, now=NOW + timedelta(seconds=30)).published == []
    rep = go(store, src, d, now=NOW + timedelta(minutes=5))
    assert set(rep.recovered) == {j.job_id for j in claimed}
    st = statuses(store)
    assert st["s:0001:en:telegram:initial"] == "outcome_unknown"       # may have been sent: never resent
    assert st["s:0001:ua:telegram:initial"] == "published"             # died before sending: delivered once
    assert st["s:0001:en:website:initial"] == st["s:0001:ua:website:initial"] == "published"
    assert [b["chat_id"] for b in bot.sent()] == ["@fake_ua"]


def test_unknown_outcome_is_not_retried_and_reconciles(tmp_path: Path) -> None:
    it = item(1)
    bot = Bot({"sendMessage": [httpx.ReadTimeout("read timed out")]})
    store, src, d, _ = setup(tmp_path, it, bot=bot, s=settings(channels={"en": "@fake_en"}))
    rep = go(store, src, d)
    assert [u["job_id"] for u in rep.unknown] == ["s:0001:en:telegram:initial"]
    assert statuses(store)["s:0001:en:website:initial"] == "published"      # isolated
    for h in (1, 5, 30):
        go(store, src, d, now=NOW + timedelta(hours=h))
    assert len(bot.sent()) == 1                                              # never blindly resent
    with pytest.raises(ActionError):
        retry_job(store, "s:0001:en:telegram:initial", NOW)
    ledger_calls: list[str] = []
    j = reconcile_job(store, "s:0001:en:telegram:initial", NOW, sent_id="901",
                      ledger_record=lambda job, mid: ledger_calls.append(mid))
    assert j.status == "published" and j.external_id == "901" and ledger_calls == ["901"]


def test_reconcile_not_sent_requeues_it(tmp_path: Path) -> None:
    bot = Bot({"sendMessage": [httpx.RemoteProtocolError("connection dropped")]})
    store, src, d, _ = setup(tmp_path, item(1), bot=bot, s=settings(channels={"en": "@fake_en"}))
    go(store, src, d)
    reconcile_job(store, "s:0001:en:telegram:initial", NOW, not_sent=True)
    go(store, src, d, now=NOW + timedelta(minutes=1))
    assert statuses(store)["s:0001:en:telegram:initial"] == "published" and len(bot.sent()) == 2


# ---------------------------------------------------------------- telegram specifics

def test_photo_success_uses_the_localized_card(tmp_path: Path) -> None:
    it = item(1)
    store, src, d, bot = setup(tmp_path, it, s=settings(attach_images=True))
    go(store, src, d)
    photos = {b["chat_id"]: b for b in bot.sent("sendPhoto")}
    assert set(photos) == {"@fake_en", "@fake_ua"} and not bot.sent("sendMessage")
    assert photos["@fake_ua"]["photo"].startswith(f"{BASE}/ua/threat/{it.fingerprint}/card/telegram.png?v=")
    assert "Ваду у Widget" in photos["@fake_ua"]["caption"]
    assert store.get("s:0001:ua:telegram:initial").media_url == photos["@fake_ua"]["photo"]  # type: ignore[union-attr]


def test_refused_photo_falls_back_to_text(tmp_path: Path) -> None:
    bot = Bot({"sendPhoto": [httpx.Response(400, json={"ok": False, "description": "Bad Request: wrong file identifier/HTTP URL specified"})]})
    store, src, d, _ = setup(tmp_path, item(1), bot=bot, s=settings(attach_images=True, channels={"en": "@fake_en"}))
    go(store, src, d)
    assert [m for m, _ in bot.calls] == ["sendPhoto", "sendMessage"]
    j = store.get("s:0001:en:telegram:initial")
    assert j and j.status == "published" and j.media_url == ""


def test_uncertain_photo_never_falls_back_to_text(tmp_path: Path) -> None:
    bot = Bot({"sendPhoto": [httpx.ReadTimeout("timed out")]})
    store, src, d, _ = setup(tmp_path, item(1), bot=bot, s=settings(attach_images=True, channels={"en": "@fake_en"}))
    go(store, src, d)
    assert [m for m, _ in bot.calls] == ["sendPhoto"]
    assert statuses(store)["s:0001:en:telegram:initial"] == "outcome_unknown"


def test_rate_limit_respects_retry_after_and_pauses_the_channel(tmp_path: Path) -> None:
    a, b = item(1), item(2)
    bot = Bot({"sendMessage": [httpx.Response(429, json={"ok": False, "description": "Too Many Requests",
                                                         "parameters": {"retry_after": 900}})]})
    store, src, d, _ = setup(tmp_path, a, b, bot=bot, s=settings(channels={"en": "@fake_en"}))
    rep = go(store, src, d)
    assert len(bot.sent()) == 1 and rep.paused == ["telegram:en (rate_limit)"]
    limited = [j for j in store.all() if j.status == "retrying"]
    assert len(limited) == 1 and limited[0].error_category == "rate_limit"
    assert limited[0].next_attempt_at == (NOW + timedelta(seconds=900)).isoformat()
    other = [j for j in store.all() if j.destination == "telegram" and j.job_id != limited[0].job_id][0]
    assert other.status == "scheduled" and other.attempts == 0                 # released, not penalised
    assert all(j.status == "published" for j in store.all() if j.destination == "website")
    go(store, src, d, now=NOW + timedelta(minutes=10))
    assert statuses(store)[limited[0].job_id] == "retrying"                   # not before retry_after
    go(store, src, d, now=NOW + timedelta(minutes=16))
    assert all(j.status == "published" for j in store.all())


def test_auth_failure_alerts_and_does_not_loop(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    bot = Bot({"sendMessage": [httpx.Response(401, json={"ok": False, "description": "Unauthorized"})]})
    store, src, d, _ = setup(tmp_path, item(1), bot=bot)
    caplog.set_level("ERROR")
    rep = go(store, src, d)
    assert "OPERATOR ACTION NEEDED" in caplog.text
    failed = [j for j in store.all() if j.status == "failed"]
    assert len(failed) == 1 and failed[0].error_category == "auth"
    assert statuses(store)["s:0001:ua:telegram:initial"] == "published"        # other channel unaffected
    go(store, src, d, now=NOW + timedelta(days=1))
    assert len(bot.sent()) == 2 and rep.failed


def test_network_failure_backs_off_then_exhausts(tmp_path: Path) -> None:
    errors: list[Any] = [httpx.ConnectError("refused")] * 3
    bot = Bot({"sendMessage": list(errors)})
    s = settings(channels={"en": "@fake_en"})
    store, src, d, _ = setup(tmp_path, item(1), bot=bot, s=s, policy=PublishPolicy(max_attempts=3))
    t = NOW
    expected = [120, 240]
    for delay in expected:
        go(store, src, d, now=t)
        j = store.get("s:0001:en:telegram:initial")
        assert j and j.status == "retrying" and j.next_attempt_at == (t + timedelta(seconds=delay)).isoformat()
        t = t + timedelta(seconds=delay)
    go(store, src, d, now=t)
    j = store.get("s:0001:en:telegram:initial")
    assert j and j.status == "failed" and "retries exhausted (3)" in j.last_error
    retry_job(store, j.job_id, t)
    go(store, src, d, now=t)
    assert statuses(store)[j.job_id] == "published" and len(bot.sent()) == 4


def test_invalid_content_fails_permanently(tmp_path: Path) -> None:
    bot = Bot({"sendMessage": [httpx.Response(400, json={"ok": False, "description": "Bad Request: can't parse entities"})]})
    store, src, d, _ = setup(tmp_path, item(1), bot=bot, s=settings(channels={"en": "@fake_en"}))
    go(store, src, d)
    go(store, src, d, now=NOW + timedelta(days=1))
    assert statuses(store)["s:0001:en:telegram:initial"] == "failed" and len(bot.sent()) == 1


def test_error_categories() -> None:
    def cat(code: int, desc: str = "") -> str:
        return TelegramError("x", status_code=code, description=desc).category
    assert cat(429) == "rate_limit" and cat(401) == "auth" and cat(403) == "permission"
    assert cat(400, "Bad Request: chat not found") == "permission"
    assert cat(400, "Bad Request: failed to get HTTP URL content") == "missing_media"
    assert cat(400, "Bad Request: message is too long") == "invalid_content"
    assert cat(502) == "temporary" and cat(500) == "unknown_outcome"


def test_unreadable_200_is_unknown_not_failure(tmp_path: Path) -> None:
    bot = Bot({"sendMessage": [httpx.Response(200, text="<html>proxy</html>")]})
    store, src, d, _ = setup(tmp_path, item(1), bot=bot, s=settings(channels={"en": "@fake_en"}))
    go(store, src, d)
    assert statuses(store)["s:0001:en:telegram:initial"] == "outcome_unknown"


def test_legacy_publish_once_never_falls_back_after_an_uncertain_photo(tmp_path: Path) -> None:
    from cyberalertx.publish.service import publish_once

    it = item(1)
    bot = Bot({"sendPhoto": [httpx.ReadTimeout("timed out")]})

    class Svc:
        def list_items(self) -> list[NewsItem]:
            return [it]

        def render_if_cached(self, i: NewsItem, *, required_locale: str | None = None) -> Any:
            return payload(it)

    res = publish_once(settings=settings(attach_images=True, channels={"en": "@fake_en"}), service=Svc(),
                       ledger=PublishLedger(tmp_path / "l.jsonl"), publisher=bot.factory()())
    assert [m for m, _ in bot.calls] == ["sendPhoto"] and res.sent == 0 and res.errors == 1


# ---------------------------------------------------------------- website specifics

def test_website_update_only_when_the_edition_changes(tmp_path: Path) -> None:
    it = item(1)
    store, src, d, bot = setup(tmp_path, it, s=settings(channels={}))
    go(store, src, d)
    plan(src, store, now=NOW, settings=settings(channels={}), destinations=d, view=view(it))
    assert len(store.all()) == 2                                               # unchanged → nothing
    src.payloads[(it.fingerprint, "ua")] = payload(it, title_suffix=" (оновлено)")
    plan(src, store, now=NOW, settings=settings(channels={}), destinations=d, view=view(it))
    upd = [j for j in store.all() if j.publication_type == "update"]
    assert len(upd) == 1 and upd[0].locale == "ua" and upd[0].fingerprint == it.fingerprint
    go(store, src, d)
    assert statuses(store)[upd[0].job_id] == "published" and not bot.calls
    first, revised = store.get("s:0001:ua:website:initial"), store.get(upd[0].job_id)
    assert first and revised and first.published_url == revised.published_url          # same article URL
    assert revised.content_hash != first.content_hash and first.status == "published"  # history kept


def test_rejected_edition_is_cancelled_not_published(tmp_path: Path) -> None:
    it = item(1)
    store, src, d, bot = setup(tmp_path, it)
    src.review[(it.fingerprint, "ua")] = "rejected"
    rep = go(store, src, d)
    st = statuses(store)
    assert st["s:0001:ua:website:initial"] == st["s:0001:ua:telegram:initial"] == "cancelled"
    assert st["s:0001:en:website:initial"] == "published" and {r["reason"] for r in rep.cancelled} == {"rejected by the editor"}
    assert [b["chat_id"] for b in bot.sent()] == ["@fake_en"]


def test_edition_missing_fields_fails_as_invalid_content(tmp_path: Path) -> None:
    it = item(1)
    src = source_for(it, locales=("en",))
    src.payloads[(it.fingerprint, "en")]["translations"]["en"]["plain_summary"] = ""
    src.payloads[(it.fingerprint, "en")]["translations"]["en"]["short_summary"] = ""
    store, src, d, _ = setup(tmp_path, it, src=src, s=settings(channels={}))
    go(store, src, d)
    j = store.get("s:0001:en:website:initial")
    assert j and j.status == "failed" and j.error_category == "invalid_content"


# ---------------------------------------------------------------- scheduling & priority

def test_future_jobs_do_not_run_early(tmp_path: Path) -> None:
    store, src, d, bot = setup(tmp_path, item(1))
    for j in store.all():
        store.update(j.job_id, lambda x: setattr(x, "scheduled_at", (NOW + timedelta(hours=2)).isoformat()), NOW)
    assert go(store, src, d).published == [] and not bot.calls
    assert len(go(store, src, d, now=NOW + timedelta(hours=2)).published) == 4


def test_breaking_goes_first_and_top10_waits_for_the_kyiv_edition(tmp_path: Path) -> None:
    ordinary, top, brk = item(1, hours_ago=1), item(2, hours_ago=3), item(3, hours_ago=5)
    now = datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)                     # 07:00 Kyiv (EET, UTC+2)
    v = view(ordinary, top, brk, breaking={"s:0003": "ev1"}, top={"s:0002": 1})
    store, src, d, bot = setup(tmp_path, ordinary, top, brk, v=v, now=now,
                               s=settings(channels={"en": "@fake_en"}), policy=PublishPolicy(top10_at="09:00"))
    jobs = {j.job_id: j for j in store.all()}
    assert jobs["s:0003:en:telegram:initial"].priority == 100 and "breaking" in jobs["s:0003:en:telegram:initial"].reasons
    t = jobs["s:0002:en:telegram:initial"]
    assert t.priority == 60 and t.scheduled_at == "2026-11-03T07:00:00+00:00"   # 09:00 Kyiv
    go(store, src, d, now=now, limit=1)
    assert bot.sent()[0]["text"].startswith("🔴 <b>Widget flaw Story 3")        # breaking first, under a cap of 1
    go(store, src, d, now=now + timedelta(minutes=1), limit=5)
    assert statuses(store)["s:0002:en:telegram:initial"] == "scheduled"         # Top 10 not before 09:00 Kyiv
    go(store, src, d, now=datetime(2026, 11, 3, 7, 0, tzinfo=timezone.utc), limit=5)
    assert statuses(store)["s:0002:en:telegram:initial"] == "published"


def test_kyiv_slot_follows_summer_time(tmp_path: Path) -> None:
    from cyberalertx.publish.orchestrator import _kyiv_slot
    assert _kyiv_slot(datetime(2026, 7, 1, 3, 0, tzinfo=timezone.utc), "09:00", "Europe/Kyiv") == \
        datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)                         # EEST, UTC+3


def test_retry_policy_backoff_and_jitter() -> None:
    p = RetryPolicy(base_seconds=60, cap_seconds=600, jitter=0.2)
    assert p.delay(1, rng=lambda: 0.5) == 60 and p.delay(3, rng=lambda: 0.5) == 240
    assert p.delay(10, rng=lambda: 0.5) == 600                                  # capped
    assert p.delay(1, rng=lambda: 0.0) == pytest.approx(48) and p.delay(1, rng=lambda: 1.0) == pytest.approx(72)
    assert p.delay(1, retry_after=3600, rng=lambda: 0.5) == 3600


def test_breaking_update_only_on_material_change_and_only_when_enabled(tmp_path: Path) -> None:
    it = item(1)
    s = settings(channels={"en": "@fake_en"})
    store, src, d, bot = setup(tmp_path, it, s=s, v=view(it, breaking={"s:0001": "ev-a"}))
    go(store, src, d)
    on = PublishPolicy(breaking_updates=True)
    plan(src, store, now=NOW, settings=s, destinations=d, view=view(it, breaking={"s:0001": "ev-a"}), policy=on)
    plan(src, store, now=NOW, settings=s, destinations=d, view=view(it, breaking={"s:0001": "ev-b"}),
         policy=PublishPolicy())
    assert not [j for j in store.all() if j.publication_type == "breaking_update"]   # unchanged / disabled
    plan(src, store, now=NOW, settings=s, destinations=d, view=view(it, breaking={"s:0001": "ev-b"}), policy=on)
    plan(src, store, now=NOW, settings=s, destinations=d, view=view(it, breaking={"s:0001": "ev-b"}), policy=on)
    upd = [j for j in store.all() if j.publication_type == "breaking_update"]
    assert len(upd) == 1 and upd[0].priority == 100
    go(store, src, d)
    assert bot.sent()[-1]["text"].startswith("🔄 <b>Update</b>") and len(bot.sent()) == 2


def test_hold_deferral_does_not_spend_attempts(tmp_path: Path) -> None:
    it = item(1)
    store, src, d, _ = setup(tmp_path, it, s=settings(channels={}))
    src.review[(it.fingerprint, "en")] = "held"
    rep = go(store, src, d)
    j = store.get("s:0001:en:website:initial")
    assert j and j.status == "retrying" and j.attempts == 0 and rep.deferred


# ---------------------------------------------------------------- operator & admin

def test_cancel_and_dry_run_change_nothing(tmp_path: Path) -> None:
    store, src, d, bot = setup(tmp_path, item(1))
    before = json.loads((tmp_path / "jobs.json").read_text())
    rep = go(store, src, d, dry_run=True)
    assert len(rep.previews) == 4 and all(p["would"] == "deliver" for p in rep.previews)
    assert json.loads((tmp_path / "jobs.json").read_text()) == before and not bot.calls
    cancel_job(store, "s:0001:en:telegram:initial", NOW)
    with pytest.raises(ActionError):
        retry_job(store, "missing", NOW)
    go(store, src, d)
    assert statuses(store)["s:0001:en:telegram:initial"] == "cancelled"


def test_cli_run_without_send_is_a_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    import cyberalertx.tools.publish as cli

    it = item(1)
    bot = Bot()
    store, src, d, _ = setup(tmp_path, it, bot=bot)
    monkeypatch.setattr(cli, "_source", lambda: src)
    monkeypatch.setattr(cli, "_destinations", lambda s: d)
    before = (tmp_path / "jobs.json").read_text()
    assert cli.main(["--jobs", str(tmp_path / "jobs.json"), "run"]) == 0
    assert (tmp_path / "jobs.json").read_text() == before and not bot.calls
    assert "preview only" in capsys.readouterr().err
    assert cli.main(["--jobs", str(tmp_path / "jobs.json"), "status"]) == 0
    assert cli.main(["--jobs", str(tmp_path / "jobs.json"), "reconcile", "x", "--not-sent"]) == 1


def test_corrupt_job_store_stops_rather_than_replans(tmp_path: Path) -> None:
    (tmp_path / "jobs.json").write_text("{not json")
    with pytest.raises(RuntimeError, match="unreadable"):
        JobStore(tmp_path / "jobs.json").all()


def test_admin_publishing_is_token_locked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    import cyberalertx.api.app as app_mod
    from cyberalertx.api.admin import AdminGuard

    store, src, d, _ = setup(tmp_path, item(1), bot=Bot({"sendMessage": [httpx.ReadTimeout("t")]}),
                             s=settings(channels={"en": "@fake_en"}))
    go(store, src, d)
    token = "t" * 48
    monkeypatch.setenv("CYBERALERTX_ADMIN_TOKEN", token)
    monkeypatch.setattr(app_mod, "_publish_jobs_path", lambda: tmp_path / "jobs.json")
    client = TestClient(app_mod.build_app(feedback_path=tmp_path / "f.jsonl", admin_guard=AdminGuard()))
    for path in ("/admin/publishing", "/admin/publishing.json"):
        assert client.get(path).status_code == 401
    auth = {"Authorization": "Basic " + base64.b64encode(f"ed:{token}".encode()).decode(), "X-Real-IP": "203.0.113.9"}
    r = client.get("/admin/publishing", headers=auth)
    assert r.status_code == 200 and "default-src 'none'" in r.headers["content-security-policy"]
    assert "outcome unknown" in r.text and "Mark delivered" in r.text
    assert 'name="job" value="s:0001:en:telegram:initial"' in r.text and 'value="retry"' not in r.text
    assert "<script" not in r.text.lower()
    data = client.get("/admin/publishing.json", headers=auth).json()
    assert data["counts"]["telegram:en"] == {"outcome_unknown": 1}
    assert data["counts"]["website:en"] == {"published": 1}
    assert "publish_jobs" not in client.get("/posts?limit=1").text


def test_prune_archives_finished_jobs_and_they_are_not_replanned(tmp_path: Path) -> None:
    it = item(1)
    store, src, d, bot = setup(tmp_path, it)
    go(store, src, d)
    later = NOW + timedelta(days=100)
    assert store.prune(later, older_than_days=90) == 4 and store.all() == []
    lines = (tmp_path / "jobs.archive.jsonl").read_text().splitlines()
    assert len(lines) == 4
    plan(src, store, now=later, settings=settings(), destinations=d, view=view(it),
         ledger_has=PublishLedger(tmp_path / "ledger.jsonl").is_published)
    go(store, src, d, now=later)
    assert len(bot.sent()) == 2                                  # nothing resent after pruning


def test_bot_token_never_reaches_the_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """httpx logs full request URLs at INFO; the Bot API puts the token in the path."""
    caplog.set_level("DEBUG")
    caplog.set_level("DEBUG", logger="httpx")   # main.py lowers httpx to WARNING on import; don't depend on test order
    bot = Bot()
    store, src, d, _ = setup(tmp_path, item(1), bot=bot)
    go(store, src, d)
    assert "HTTP Request" in caplog.text and "/bot[redacted]/send" in caplog.text
    assert "123:FAKE" not in caplog.text


def test_backlog_goes_newest_first_like_the_legacy_publisher(tmp_path: Path) -> None:
    """Phase 7: more qualifying stories than slots must not post a stale backlog."""
    old, new = item(1, hours_ago=20), item(2, hours_ago=1)
    store, src, d, bot = setup(tmp_path, old, new, s=settings(channels={"en": "@fake_en"}))
    go(store, src, d, limit=1)
    assert [b["text"].split("\n")[0] for b in bot.sent()] == ["🔴 <b>Widget flaw Story 2</b>"]


def test_social_jobs_expire_outside_the_window(tmp_path: Path) -> None:
    it = item(1, hours_ago=30)
    store, src, d, bot = setup(tmp_path, it, s=settings(channels={"en": "@fake_en"}))
    later = NOW + timedelta(hours=30)                                    # article now 60 h old
    preview = go(store, src, d, now=later, dry_run=True)
    assert any(p["would"].startswith("expire") for p in preview.previews if "telegram" in p["job_id"])
    rep = go(store, src, d, now=later)
    j = store.get("s:0001:en:telegram:initial")
    assert j and j.status == "cancelled" and "expired" in j.last_error and not bot.calls
    assert store.get("s:0001:en:website:initial").status == "published"   # type: ignore[union-attr]
    assert any("expired" in c["reason"] for c in rep.cancelled)
