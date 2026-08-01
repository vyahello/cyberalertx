"""Tests for the Telegram publishing layer.

Everything is injected — no real Telegram I/O, no disk beyond `tmp_path`.
Covers the selection bar, HTML formatting/escaping, the JSONL ledger's
dedup + persistence, and the end-to-end `publish_once` orchestration
(tier filter, language gate, dedup, uncached-skip, dry-run, live send).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from cyberalertx.models import NewsItem
from cyberalertx.publish.config import TelegramSettings
from cyberalertx.publish.format import deep_link, quality_problem, render_message
from cyberalertx.publish.ledger import PublishLedger
from cyberalertx.publish.service import publish_once, qualifies
from cyberalertx.publish.telegram import TelegramError


# --------------------- helpers --------------------------------------------

def _item(url_id: str, *, language: str = "en", tier: str = "trusted",
          published: datetime | None = None) -> NewsItem:
    return NewsItem(
        title=f"story {url_id}",
        source="BleepingComputer",
        url=f"https://e.test/{url_id}",
        published_at=published or datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        raw_content="",
        language=language,
        source_tier=tier,
    )


def _payload(item: NewsItem, locale: str, *, level: str = "High",
             actionability: str = "informational",
             title: str = "Title", summary: str = "A summary.",
             plain: str = "",
             actions: list[str] | None = None,
             facts: list[str] | None = None,
             source: str = "BleepingComputer") -> dict[str, Any]:
    return {
        "id": item.fingerprint,
        "source": source,
        "threat_level": level,
        "actionability_level": actionability,
        "translations": {
            locale: {
                "title": title,
                "short_summary": summary,
                "plain_summary": plain,
                "what_to_do": actions or [],
                "quick_facts": facts or [],
            }
        },
    }


def _settings(**overrides: Any) -> TelegramSettings:
    base: dict[str, Any] = dict(
        bot_token="test-token",
        channels={"en": "@cax_en", "ua": "@cax_ua"},
        min_level="High",
        limit=5,
        send_delay_seconds=0.0,  # no sleeping in tests
        public_base_url="https://cyberalertx.com",
    )
    base.update(overrides)
    return TelegramSettings(**base)


class _FakeService:
    """Stand-in for _PostService — fixed items + a (fingerprint,locale)→payload map."""

    def __init__(self, items: list[NewsItem],
                 rendered: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._items = items
        self._rendered = rendered

    def list_items(self) -> list[NewsItem]:
        return list(self._items)

    def render_if_cached(self, item: NewsItem, *, required_locale: str | None = None):
        return self._rendered.get((item.fingerprint, required_locale))


class _FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._next_id = 1000

    def send_message(self, chat_id: str, text: str, **_kw: Any) -> int:
        self._next_id += 1
        self.sent.append((chat_id, text))
        return self._next_id

    def close(self) -> None:
        pass


class _FailingPublisher:
    """Always raises a given TelegramError; counts how many sends were tried."""

    def __init__(self, error: TelegramError) -> None:
        self._error = error
        self.attempts = 0

    def send_message(self, chat_id: str, text: str, **_kw: Any) -> int:
        self.attempts += 1
        raise self._error

    def close(self) -> None:
        pass


# --------------------- qualifies (the selection bar) ----------------------

def test_qualifies_severity_bar() -> None:
    s = _settings(min_level="High")
    assert qualifies({"threat_level": "Critical"}, s) is True
    assert qualifies({"threat_level": "High"}, s) is True
    assert qualifies({"threat_level": "Medium"}, s) is False
    assert qualifies({"threat_level": "Low"}, s) is False


def test_qualifies_urgent_overrides_low_severity() -> None:
    s = _settings(min_level="High")
    # A Medium that's under active exploitation still qualifies on urgency.
    assert qualifies(
        {"threat_level": "Medium", "actionability_level": "urgent_action"}, s
    ) is True


# --------------------- formatting -----------------------------------------

def test_render_message_structure_and_link() -> None:
    item = _item("a")
    payload = _payload(item, "en", level="Critical",
                       title="RCE in Foo", summary="Patch now.",
                       actions=["Install the vendor patch and reboot.",
                                "Audit exposed hosts."])
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert "🔴" in msg
    assert "<b>RCE in Foo</b>" in msg
    assert "Patch now." in msg
    # Actions render as a labeled section with up to two bullets. Two, not
    # one: a single-action format kept dropping the step that made the first
    # one take effect ("install the patch" without "then reboot").
    assert "✅ <b>What to do</b>" in msg
    assert "• Install the vendor patch and reboot." in msg
    assert "• Audit exposed hosts." in msg
    # Quick facts still stay out of the message — they're a spec sheet, and
    # the channel's job is "what happened, what do I do".
    assert deep_link("https://cyberalertx.com", "en", item.fingerprint) in msg
    assert ">Read more</a>" in msg


def test_plain_summary_leads_then_the_specifics_follow() -> None:
    """Plain language leads, and the technical line follows when it adds facts.

    The message used to render `plain_summary` alone. But that field's
    contract forbids CVE ids, vendor acronyms and attribution, so it names no
    product and no number on the overwhelming majority of cached posts — a
    subscriber read "хакери зламують сервери через популярну програмну
    складову" while the cache already held the named library. Both lines ship
    now: the everyday sentence first, the specifics second.
    """
    item = _item("plain")
    payload = _payload(
        item, "en",
        title="Apple ships emergency iPhone fix",
        summary="Apple reports a zero-click CoreText flaw, CVE-2026-1, exploited in the wild.",
        plain="A booby-trapped text can take over your iPhone — update now.",
    )
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    plain_at = msg.index("A booby-trapped text can take over your iPhone")
    detail_at = msg.index("CoreText")
    assert plain_at < detail_at, "the everyday sentence must come first"
    assert "CVE-2026-1" in msg


def test_second_paragraph_is_dropped_when_it_adds_nothing() -> None:
    """A `short_summary` that names no product, actor or number the plain lead
    lacks is a restatement, and restating the lead in different words wastes
    the reader's attention."""
    item = _item("dup")
    payload = _payload(
        item, "en",
        title="Router bug",
        summary="Attackers can take over the device remotely.",
        plain="Attackers can take over the device remotely.",
    )
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert msg.count("take over the device remotely") == 1


def test_render_message_escapes_html() -> None:
    item = _item("b")
    payload = _payload(item, "en", title="A <script> & B",
                       summary="x < y & z > w")
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert "<script>" not in msg
    assert "&lt;script&gt;" in msg
    assert "&amp;" in msg


def test_render_message_linkifies_cve_ids() -> None:
    item = _item("cve")
    payload = _payload(
        item, "ua",
        title="ABB AC500 V3 RCE",
        summary="Критична вразливість CVE-2025-15467 та CVE-2025-2595 дозволяють RCE.",
        actions=["Оновіть прошивку, що усуває cve-2025-41691."],
    )
    msg = render_message(payload, locale="ua", base_url="https://cyberalertx.com")
    # CVE ids are linkified wherever they appear in the rendered body — the
    # lead summary AND the action line. The visible label keeps its casing.
    assert '<a href="https://nvd.nist.gov/vuln/detail/CVE-2025-15467">CVE-2025-15467</a>' in msg
    assert '<a href="https://nvd.nist.gov/vuln/detail/CVE-2025-2595">CVE-2025-2595</a>' in msg
    # Lowercase input (in the action line) → uppercased URL, original-case label.
    assert '<a href="https://nvd.nist.gov/vuln/detail/CVE-2025-41691">cve-2025-41691</a>' in msg


def test_render_message_ua_uses_localized_cta() -> None:
    item = _item("c", language="ua")
    payload = _payload(item, "ua", title="Заголовок", summary="Опис.")
    msg = render_message(payload, locale="ua", base_url="https://cyberalertx.com")
    assert "Читати більше" in msg
    assert f"/ua/threat/{item.fingerprint}" in msg


def test_render_message_missing_translation_raises() -> None:
    item = _item("d")
    payload = _payload(item, "en")
    with pytest.raises(ValueError):
        render_message(payload, locale="ua", base_url="https://cyberalertx.com")


def test_source_is_named_once() -> None:
    """The outlet is named, because nothing else in the message names it.

    This used to be omitted on the reasoning that the AI summary already
    carried the outlet. That holds for `short_summary`, but the message leads
    with `plain_summary`, whose contract forbids an attribution clause, and
    the link preview is pinned to our own deep link — so an unattributed
    claim was reaching subscribers.
    """
    item = _item("s")
    payload = _payload(item, "en", source="Krebs on Security")
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert "Source: Krebs on Security" in msg


def test_source_is_not_repeated_when_the_body_already_names_it() -> None:
    item = _item("s2")
    payload = _payload(
        item, "en",
        source="Krebs on Security",
        summary="Krebs on Security reports a wave of SIM-swap fraud at three carriers.",
        plain="Scammers are moving phone numbers to their own SIMs to steal login codes.",
    )
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert msg.count("Krebs on Security") == 1
    assert "Source: Krebs on Security" not in msg


# --------------------- pre-send quality gate ------------------------------

def test_quality_problem_passes_good_post() -> None:
    item = _item("g")
    payload = _payload(item, "ua", title="Критична вразливість у ABB",
                       summary="CISA повідомляє про серйозну проблему.")
    assert quality_problem(payload, locale="ua") is None


def test_quality_problem_flags_missing_translation() -> None:
    item = _item("g")
    payload = _payload(item, "en")
    assert quality_problem(payload, locale="ua") is not None


def test_quality_problem_flags_wrong_script_summary() -> None:
    item = _item("g")
    # UA title but an English summary body — the half-translated case render()
    # doesn't catch (it only script-checks the title).
    payload = _payload(
        item, "ua",
        title="Критична вразливість у системі керування ABB AC500",
        summary="CISA reports a critical remote code execution vulnerability "
                "affecting industrial controllers worldwide right now.",
    )
    assert quality_problem(payload, locale="ua") is not None


def test_publish_once_skips_invalid_post(tmp_path: Path) -> None:
    item = _item("u", language="ua")
    # Wrong-script summary → should be gated out, not sent.
    payload = _payload(
        item, "ua", level="Critical",
        title="Критична вразливість у промисловому контролері ABB AC500 V3",
        summary="A long English sentence that clearly is not Ukrainian text "
                "at all and should trip the wrong-script summary guard here.",
    )
    svc = _FakeService([item], {(item.fingerprint, "ua"): payload})
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"ua": "@cax_ua"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert result.sent == 0
    assert result.skipped_invalid == 1
    assert pub.sent == []


# --------------------- ledger ---------------------------------------------

def test_ledger_records_and_dedups(tmp_path: Path) -> None:
    led = PublishLedger(tmp_path / "pub.jsonl")
    assert led.is_published("fp1", "en") is False
    led.record(fingerprint="fp1", locale="en", channel="@c", message_id=7)
    assert led.is_published("fp1", "en") is True
    # Different locale of the same item is independent.
    assert led.is_published("fp1", "ua") is False


def test_ledger_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "pub.jsonl"
    led = PublishLedger(path)
    led.record(fingerprint="fp1", locale="en", channel="@c", message_id=7)
    led.record(fingerprint="fp2", locale="ua", channel="@d", message_id=8)
    reloaded = PublishLedger(path)
    assert reloaded.is_published("fp1", "en") is True
    assert reloaded.is_published("fp2", "ua") is True
    assert len(reloaded) == 2


def test_ledger_tolerates_corrupt_line(tmp_path: Path) -> None:
    path = tmp_path / "pub.jsonl"
    path.write_text('{"fingerprint":"ok","locale":"en"}\nnot json\n', encoding="utf-8")
    led = PublishLedger(path)
    assert led.is_published("ok", "en") is True
    assert len(led) == 1


# --------------------- publish_once (orchestration) -----------------------

def test_publish_once_dry_run_sends_nothing(tmp_path: Path) -> None:
    item = _item("a")
    svc = _FakeService([item], {(item.fingerprint, "en"): _payload(item, "en")})
    led = PublishLedger(tmp_path / "pub.jsonl")
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, dry_run=True,
    )
    assert result.sent == 1
    assert result.dry_run is True
    # Dry-run must not touch the ledger.
    assert len(led) == 0


def test_publish_once_sends_and_records(tmp_path: Path) -> None:
    item = _item("a")
    svc = _FakeService(
        [item],
        {(item.fingerprint, "en"): _payload(item, "en", level="Critical")},
    )
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert result.sent == 1
    assert len(pub.sent) == 1
    assert pub.sent[0][0] == "@cax_en"
    assert led.is_published(item.fingerprint, "en") is True


def test_publish_once_skips_already_published(tmp_path: Path) -> None:
    item = _item("a")
    svc = _FakeService([item], {(item.fingerprint, "en"): _payload(item, "en")})
    led = PublishLedger(tmp_path / "pub.jsonl")
    led.record(fingerprint=item.fingerprint, locale="en", channel="@cax_en", message_id=1)
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert result.sent == 0
    assert result.skipped_already == 1
    assert pub.sent == []


def test_publish_once_skips_uncached(tmp_path: Path) -> None:
    item = _item("a")
    svc = _FakeService([item], {})  # nothing rendered
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert result.sent == 0
    assert result.skipped_uncached == 1


def test_publish_once_filters_low_severity(tmp_path: Path) -> None:
    item = _item("a")
    svc = _FakeService(
        [item], {(item.fingerprint, "en"): _payload(item, "en", level="Low")},
    )
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert result.sent == 0
    assert result.skipped_filtered == 1


def test_publish_once_excludes_unverified_tier(tmp_path: Path) -> None:
    item = _item("a", tier="unverified")
    svc = _FakeService(
        [item], {(item.fingerprint, "en"): _payload(item, "en", level="Critical")},
    )
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    # Tier-filtered before render — it never reaches the send path.
    assert result.sent == 0
    assert pub.sent == []


def test_publish_once_language_gate_ua_item_not_on_en_channel(tmp_path: Path) -> None:
    ua_item = _item("u", language="ua")
    en_item = _item("e", language="en")
    # UA payloads need real Ukrainian text or the pre-send quality gate
    # (wrong-script guard) would correctly drop them — this test is about
    # channel routing, not content quality.
    ua_text = dict(title="Критична вразливість у системі ABB AC500",
                   summary="CISA повідомляє про серйозну загрозу безпеці.")
    svc = _FakeService(
        [ua_item, en_item],
        {
            (ua_item.fingerprint, "ua"): _payload(ua_item, "ua", level="High", **ua_text),
            (en_item.fingerprint, "en"): _payload(en_item, "en", level="High"),
            (en_item.fingerprint, "ua"): _payload(en_item, "ua", level="High", **ua_text),
        },
    )
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en", "ua": "@cax_ua"}),
        service=svc, ledger=led, publisher=pub,
    )
    # EN channel: only the EN-source item. UA channel: both (EN-source renders
    # in UA too). So 1 (en) + 2 (ua) = 3 sends.
    assert result.by_channel.get("en") == 1
    assert result.by_channel.get("ua") == 2
    assert result.sent == 3


def test_publish_once_respects_limit(tmp_path: Path) -> None:
    items = [_item(f"i{n}", published=datetime(2026, 5, n + 1, tzinfo=timezone.utc))
             for n in range(5)]
    rendered = {
        (it.fingerprint, "en"): _payload(it, "en", level="Critical") for it in items
    }
    svc = _FakeService(items, rendered)
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub, limit=2,
    )
    assert result.sent == 2
    assert len(pub.sent) == 2


def test_publish_once_no_channels_is_noop(tmp_path: Path) -> None:
    svc = _FakeService([], {})
    led = PublishLedger(tmp_path / "pub.jsonl")
    result = publish_once(settings=_settings(channels={}), service=svc, ledger=led)
    assert result.sent == 0


# --------------------- error classification + early-abort -----------------

def test_telegram_error_channel_fatal_classification() -> None:
    assert TelegramError("x", status_code=403,
                         description="bot is not a member").is_channel_fatal
    assert TelegramError("x", status_code=401,
                         description="Unauthorized").is_channel_fatal
    assert TelegramError("x", status_code=400,
                         description="Bad Request: chat not found").is_channel_fatal
    # A generic 400 (e.g. a bad message body) is NOT channel-fatal — it's
    # item-specific, so the run should move on to the next post.
    assert not TelegramError("x", status_code=400,
                             description="message text is empty").is_channel_fatal
    assert not TelegramError("x", status_code=429,
                             description="Too Many Requests").is_channel_fatal


def test_publish_once_aborts_channel_on_chat_not_found(tmp_path: Path) -> None:
    """A 'chat not found' must stop after ONE attempt, not retry every item —
    this is the retry-storm guard."""
    items = [_item(f"i{n}", published=datetime(2026, 5, n + 1, tzinfo=timezone.utc))
             for n in range(20)]
    rendered = {
        (it.fingerprint, "en"): _payload(it, "en", level="Critical") for it in items
    }
    svc = _FakeService(items, rendered)
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FailingPublisher(
        TelegramError("nope", status_code=400, description="chat not found")
    )
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert pub.attempts == 1          # aborted immediately, did NOT hammer all 20
    assert result.errors == 1
    assert result.sent == 0


def test_publish_once_continues_past_item_level_error(tmp_path: Path) -> None:
    """A non-fatal (item-specific) error skips that post but keeps going."""
    items = [_item(f"i{n}", published=datetime(2026, 5, n + 1, tzinfo=timezone.utc))
             for n in range(3)]
    rendered = {
        (it.fingerprint, "en"): _payload(it, "en", level="Critical") for it in items
    }
    svc = _FakeService(items, rendered)
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FailingPublisher(
        TelegramError("nope", status_code=429, description="Too Many Requests")
    )
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub, limit=5,
    )
    # Not channel-fatal → it tries every candidate (3), all fail, none abort.
    assert pub.attempts == 3
    assert result.errors == 3
    assert result.sent == 0


# ------------------- message design (v0.5) --------------------------------

def test_notification_is_reserved_for_critical_and_urgent() -> None:
    """A channel that buzzes for every routine advisory gets muted, and a
    muted channel can't deliver the alert that mattered."""
    from cyberalertx.publish.format import notify

    item = _item("n")
    assert notify(_payload(item, "en", level="Critical")) is True
    # `urgent_action` on its own is NOT enough. That flag is a keyword score
    # over the English source article, and a single "in the wild" clears the
    # threshold — it pushed a Medium post whose first action read "Звичайним
    # абонентам робити нічого не треба". A push that opens with "nothing to
    # do" is how a channel gets muted. The severity has to agree.
    assert notify(_payload(item, "en", level="Medium",
                           actionability="urgent_action")) is False
    assert notify(_payload(item, "en", level="High",
                           actionability="urgent_action")) is True
    assert notify(_payload(item, "en", level="High")) is False
    assert notify(_payload(item, "en", level="Low")) is False


def test_urgent_hashtag_never_disagrees_with_the_push() -> None:
    """`#urgent` and the notification are driven by one decision.

    Previously the tag came straight off `actionability_level` while the push
    came off a different expression, so a silent Medium post could still carry
    a tag telling readers to drop everything.
    """
    from cyberalertx.publish.format import _hashtags, notify

    item = _item("u")
    medium = _payload(item, "en", level="Medium", actionability="urgent_action")
    assert notify(medium) is False
    assert "#urgent" not in _hashtags(medium)

    high = _payload(item, "en", level="High", actionability="urgent_action")
    assert notify(high) is True
    assert "#urgent" in _hashtags(high)


def test_message_leads_with_self_check_then_actions() -> None:
    item = _item("sc")
    payload = _payload(item, "en", title="Chrome bug", summary="Update Chrome.",
                       actions=["Update Chrome from the menu."])
    payload["translations"]["en"]["am_i_affected"] = [
        "Open Chrome menu > Help > About. Below 126 is affected.",
    ]
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert "🔎 <b>Check if this affects you</b>" in msg
    # "does this affect me" must come before "what to do" — a reader whose
    # answer is "no" should stop reading there.
    assert msg.index("🔎") < msg.index("✅")


def test_message_names_the_other_outlets_that_reported_it() -> None:
    """The visible payoff of collapsing duplicates: instead of three posts
    the subscriber gets one that says three outlets confirmed it."""
    item = _item("corr")
    payload = _payload(item, "en", title="SharePoint RCE", summary="Patch now.")
    payload["corroborating_sources"] = ["The Hacker News", "CISA Alerts"]
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert "Also reported by The Hacker News, CISA Alerts" in msg


def test_hashtags_are_curated_not_sprayed() -> None:
    item = _item("tags")
    payload = _payload(item, "en", actionability="urgent_action")
    payload["category"] = "ransomware"
    payload["affected_platforms"] = ["Windows", "Active Directory"]
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert "#ransomware" in msg
    assert "#Windows" in msg
    assert "#ActiveDirectory" in msg
    assert msg.count("#") <= 4


def test_ukrainian_message_uses_ukrainian_furniture() -> None:
    item = _item("ua1", language="ua")
    payload = _payload(item, "ua", title="Загроза", summary="Оновіть систему.",
                       actions=["Встановіть оновлення."])
    msg = render_message(payload, locale="ua", base_url="https://cyberalertx.com")
    assert "Що робити" in msg
    assert "Читати більше" in msg


def test_quality_gate_checks_the_field_the_message_actually_leads_with() -> None:
    """render_message leads with plain_summary; the gate used to inspect
    short_summary only, so an English plain-language line shipped to the
    Ukrainian channel."""
    item = _item("q", language="ua")
    payload = _payload(
        item, "ua",
        title="Критична вразливість у Chrome",
        summary="Оновіть браузер якнайшвидше.",
        plain="Update your browser right now, this is being exploited.",
    )
    assert quality_problem(payload, locale="ua") is not None


def test_quality_gate_rejects_stray_foreign_script() -> None:
    # A real cached post carried "攻擊穿過автентифікацію" — the Cyrillic-vs-
    # Latin ratio check scores CJK as neither, so it slipped through.
    item = _item("cjk", language="ua")
    payload = _payload(
        item, "ua",
        title="Обхід автентифікації",
        summary="攻擊穿過автентифікацію дозволяє обійти вхід.",
    )
    assert quality_problem(payload, locale="ua") is not None


def test_quality_gate_passes_a_clean_ukrainian_payload() -> None:
    item = _item("ok", language="ua")
    payload = _payload(
        item, "ua",
        title="Критична вразливість у Chrome",
        summary="Оновіть браузер якнайшвидше.",
        plain="Оновіть браузер зараз — цю дірку вже використовують.",
        actions=["Оновіть Chrome через меню довідки."],
    )
    assert quality_problem(payload, locale="ua") is None


def test_send_pins_the_preview_to_our_own_page() -> None:
    """The body linkifies CVE ids before our read-more link, so without an
    explicit preview url Telegram builds the card from nvd.nist.gov."""
    item = _item("prev")
    payload = _payload(item, "en", level="Critical", title="CVE-2026-1 in Foo",
                       summary="Patch now.")
    captured: dict[str, Any] = {}

    class _CapturingPublisher:
        def send_message(self, chat_id: str, text: str, **kw: Any) -> int:
            captured.update(kw)
            captured["chat_id"] = chat_id
            return 1

        def close(self) -> None:
            pass

    ledger = PublishLedger(Path("/tmp") / "cax-test-preview.jsonl")
    ledger._path.unlink(missing_ok=True)  # noqa: SLF001
    ledger = PublishLedger(ledger._path)  # noqa: SLF001

    publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=_FakeService([item], {(item.fingerprint, "en"): payload}),
        ledger=ledger,
        publisher=_CapturingPublisher(),
    )

    assert captured["preview_url"] == deep_link(
        "https://cyberalertx.com", "en", item.fingerprint,
    )
    # Critical → the phone should buzz.
    assert captured["disable_notification"] is False


def test_message_renders_what_not_to_do() -> None:
    """Anti-patterns reach subscribers.

    `what_not_to_do` was populated on every cached post and rendered on none
    of them, so the channel never carried the single most protective sentence
    a breach post has ("Don't click links in emails about this leak").
    """
    item = _item("avoid")
    payload = _payload(item, "en", title="Payroll breach", summary="Records taken.")
    payload["translations"]["en"]["what_not_to_do"] = [
        "Don't click links in emails about this breach.",
    ]
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert "What not to do" in msg
    assert "Don't click links in emails about this breach." in msg


def test_audience_replaces_the_check_heading_when_there_is_no_check() -> None:
    """Three outcomes, never a fourth.

    When `am_i_affected` is empty — which it is on the overwhelming majority
    of cached posts — the message shows who the story is about instead of
    printing a heading that promises a check and then withholds one.
    """
    item = _item("aud")
    payload = _payload(item, "en", title="Router bug", summary="Patch shipped.")
    payload["translations"]["en"]["am_i_affected"] = []
    payload["translations"]["en"]["affected_users"] = [
        "TP-Link Archer owners", "Home broadband users",
    ]
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert "Who this affects" in msg
    assert "TP-Link Archer owners" in msg
    assert "Check if this affects you" not in msg


def test_no_audience_and_no_check_prints_neither_heading() -> None:
    item = _item("none")
    payload = _payload(item, "en", title="Router bug", summary="Patch shipped.")
    payload["translations"]["en"]["am_i_affected"] = []
    payload["translations"]["en"]["affected_users"] = []
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert "Who this affects" not in msg
    assert "Check if this affects you" not in msg


def test_three_actions_are_rendered_not_two() -> None:
    """The third action used to be cut from every message ever sent, while the
    message used ~9% of Telegram's 4096-char budget. On the 4G/5G post that
    discarded the only step an ordinary subscriber could take."""
    item = _item("three")
    payload = _payload(
        item, "en", title="Carrier flaws", summary="Core network bugs.",
        actions=[
            "Ask your 4G/5G core vendor whether these apply.",
            "Turn on Wi-Fi Calling as a fallback during outages.",
            "Enable carrier account PIN protection.",
        ],
    )
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    for action in payload["translations"]["en"]["what_to_do"]:
        assert action in msg
