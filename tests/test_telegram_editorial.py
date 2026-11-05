"""Telegram editorial format (publish/format.py): accuracy, structure and limits.

Fixtures are sanitized from real CyberAlertX briefs (Nov 2026)."""
from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from cyberalertx.publish.config import TelegramSettings
from cyberalertx.publish.destinations import DeliveryError, TelegramDestination
from cyberalertx.publish.format import (CAPTION_LIMIT, CAPTION_TARGET, category_emoji, format_problem,
                                       render_buttons, render_caption, visible_length)
from cyberalertx.publish.telegram import TelegramPublisher

BASE = "https://cyberalertx.com"


def brief(locale: str = "en", *, category: str = "vulnerability", level: str = "High", **t: Any) -> dict[str, Any]:
    content = {"title": "Widget servers taken over through a login bypass",
               "plain_summary": "Attackers are taking over Widget servers that have not installed the latest fix.",
               "short_summary": "BleepingComputer reports that CVE-2026-1111 in Widget 4.2 is exploited against exposed servers.",
               "why_it_matters": "Widget runs the login page for many company portals. Patching closes it.",
               "what_to_do": ["Install Widget 4.3.", "Check Widget logs for unknown admin accounts."],
               "affected_users": ["Widget administrators"], "quick_facts": [], "detail_body": ""}
    content.update(t)
    return {"id": "0123456789abcdef", "source": "BleepingComputer",
            "source_url": "https://www.bleepingcomputer.com/news/security/widget/", "threat_level": level,
            "category": category, "actionability_level": "recommended_action", "affected_platforms": ["Linux"],
            "evidence": {"exploitation": "confirmed", "campaign": "", "compromise": "", "unknowns": []},
            "corroborating_sources": [], "translations": {locale: content}}


def blocks(caption: str) -> list[str]:
    return caption.split("\n\n")


# ------------------------------------------------------------- unsupported claims

FRIDGE_CLAIM_UA = dict(
    title="NoName057(16) і Z-Pentest Alliance заявили про атаки на холодильники європейських супермаркетів",
    plain_summary="Проросійські хакери NoName057(16) і Z-Pentest Alliance заявили, що через їхні атаки "
                  "холодильники в європейських супермаркетах нагрілися до +50°C.",
    short_summary="dev.ua повідомляє: проросійські NoName057(16) та Z-Pentest Alliance взяли відповідальність "
                  "за атаки на холодильне обладнання.",
    why_it_matters="Якщо холодильник нагрівся до +50°C, продукти в ньому псуються за години.",
    what_to_do=["Приберіть панелі керування холодильним обладнанням з прямого доступу з інтернету.",
                "Не купуйте охолоджені продукти з теплих вітрин супермаркету."],
    affected_users=["Мережі супермаркетів у Європі", "Оператори холодильного обладнання"],
    quick_facts=["Відповідальність взяли NoName057(16) і Z-Pentest Alliance"])


def test_an_attackers_claim_is_labelled_unconfirmed_in_ukrainian() -> None:
    p = brief("ua", category="other", level="High", **FRIDGE_CLAIM_UA)
    p["evidence"] = {"exploitation": "not_reported", "compromise": "", "unknowns": []}
    cap = render_caption(p, locale="ua", base_url=BASE)
    assert "⚠️ <b>Не підтверджено:</b> це заява самих зловмисників" in cap
    assert cap.startswith("🏭 ")                                   # refrigeration controllers: industrial


def test_a_claim_never_shows_as_a_confirmed_exposure() -> None:
    p = brief("en", category="breach", title="Gang claims it stole 2 TB from Acme",
              plain_summary="The Foo ransomware gang claims it stole 2 TB of files from Acme.")
    p["evidence"] = {"exploitation": "not_reported", "compromise": "confirmed", "unknowns": []}
    cap = render_caption(p, locale="en", base_url=BASE)
    assert "data exposure confirmed" not in cap
    assert "⚠️ <b>Unconfirmed:</b> this comes from the attackers' own claim" in cap


def test_a_vendor_or_agency_statement_is_not_a_claim() -> None:
    p = brief("en", plain_summary="CISA says attackers are exploiting the Widget flaw against agencies.")
    assert "Unconfirmed" not in render_caption(p, locale="en", base_url=BASE)


def test_suspected_exploitation_is_never_shown_as_confirmed() -> None:
    p = brief("en")
    p["evidence"] = {"exploitation": "suspected", "unknowns": []}
    cap = render_caption(p, locale="en", base_url=BASE)
    assert "exploitation confirmed" not in cap and "⚠️ <b>Unconfirmed:</b> exploitation is suspected" in cap


def test_off_topic_advice_is_dropped() -> None:
    p = brief("ua", category="other", level="High", **FRIDGE_CLAIM_UA)
    cap = render_caption(p, locale="ua", base_url=BASE)
    assert "Приберіть панелі керування" in cap and "Не купуйте" not in cap


# ------------------------------------------------------------- duplicated paragraphs

def test_a_paragraph_that_restates_the_tldr_is_dropped() -> None:
    p = brief("ua", category="breach",
              title="Російська APT29 зламувала смартфони відвідувачів сайтів через аналітику Plerdy",
              plain_summary="Російські хакери з APT29 зламували iPhone та Android-телефони людей, яким вистачало "
                            "просто відкрити заражений український чи західний сайт.",
              short_summary="APT29 заражала iPhone і Android-смартфони через українські та західні сайти, зокрема "
                            "через код вебаналітики Plerdy.")
    cap = render_caption(p, locale="ua", base_url=BASE)
    assert "зокрема через код вебаналітики" not in cap
    assert cap.startswith("🕵️ ")                                   # the headline is about the actor


def test_the_outlet_is_named_once_and_why_never_repeats_the_summary() -> None:
    p = brief("en", why_it_matters="Attackers are taking over Widget servers that have not installed the fix.")
    cap = render_caption(p, locale="en", base_url=BASE)
    assert cap.count("BleepingComputer") == 1 and "Why it matters" not in cap


def test_an_outlet_lead_in_is_kept_when_removing_it_would_leave_a_fragment() -> None:
    p = brief(short_summary="BleepingComputer reports attackers chaining three Widget bugs to reach root on 4.2.")
    cap = render_caption(p, locale="en", base_url=BASE)
    assert "BleepingComputer reports attackers chaining three Widget bugs" in cap   # not "Attackers chaining …"


@pytest.mark.parametrize("locale", ["en", "ua"])
def test_no_two_blocks_say_the_same_thing(locale: str) -> None:
    from cyberalertx.publish.format import _restates
    cap = render_caption(brief(locale), locale=locale, base_url=BASE)
    prose = [b for b in blocks(cap)[1:] if not b.startswith(("👥", "🛡️", "⚠️", "❔", "🔴", "🟠", "🟡", "🔵", "#"))]
    text = [re.sub(r"<[^>]+>", "", b) for b in prose]
    assert len(text) >= 3                                          # TL;DR, what happened, why
    for i, a in enumerate(text):
        for b in text[i + 1:]:
            assert not _restates(a, b)


# ------------------------------------------------------------- severity

@pytest.mark.parametrize("level, line", [("Critical", "🔴 <b>Severity: Critical</b>"), ("High", "🟠 <b>Severity: High</b>"),
                                         ("Medium", "🟡 <b>Severity: Medium</b>"), ("Low", "🔵 <b>Severity: Low</b>")])
def test_severity_is_the_stored_level(level: str, line: str) -> None:
    assert line in render_caption(brief(level=level), locale="en", base_url=BASE)


@pytest.mark.parametrize("bad", ["", "Severe", "high", None])
def test_an_invalid_severity_gets_no_label(bad: Any) -> None:
    p = brief()
    p["threat_level"] = bad
    cap = render_caption(p, locale="en", base_url=BASE)
    assert "Severity" not in cap and not re.search("[🔴🟠🟡🔵]", cap)


# ------------------------------------------------------------- links and markup

def test_links_are_the_source_and_the_article_button() -> None:
    p = brief("ua")
    cap = render_caption(p, locale="ua", base_url=BASE)
    hrefs = re.findall(r'href="([^"]+)"', cap)
    assert "https://www.bleepingcomputer.com/news/security/widget/" in hrefs
    assert all(h.startswith("https://") for h in hrefs) and "/threat/" not in cap
    assert render_buttons(p, locale="ua", base_url=BASE) == {"inline_keyboard": [[{
        "text": "📖 Читати повний розбір", "url": f"{BASE}/ua/threat/0123456789abcdef"}]]}
    assert render_buttons(brief(), locale="en", base_url=BASE)["inline_keyboard"][0][0]["text"] == \
        "📖 Read the full analysis"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://x.test/a", "", "not a url"])
def test_a_source_url_that_is_not_http_is_never_linked(url: str) -> None:
    p = brief()
    p["source_url"] = url
    cap = render_caption(p, locale="en", base_url=BASE)
    assert "🔗 <b>Source:</b> BleepingComputer" in cap and format_problem(cap) is None


def test_hostile_fields_render_as_valid_telegram_html() -> None:
    p = brief(title='<script>x</script> & "co" <b>', plain_summary="1 < 2 & 3 > 2 `rm -rf /` CVE-2026-1 <i>",
              what_to_do=["Run `grep CVE-2026-2222 /var/log` & check."])
    for locale in ("en",):
        cap = render_caption(p, locale=locale, base_url=BASE)
        assert format_problem(cap) is None
        assert "&lt;script&gt;" in cap and "<code>rm -rf /</code>" in cap


@pytest.mark.parametrize("bad, why", [
    ("<b>x", "unclosed"), ("x</b>", "unbalanced"), ("<u>x</u>", "unsupported"),
    ('<a href="javascript:x">y</a>', "href"), ("<a>y</a>", "href"), ("a < b", "unescaped"), ("a & b", "unescaped"),
    ("x" * (CAPTION_LIMIT + 1), "1024"),
])
def test_format_check_catches_malformed_captions(bad: str, why: str) -> None:
    problem = format_problem(bad)
    assert problem and why in problem


def test_prepare_refuses_a_malformed_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    import cyberalertx.publish.destinations as dest
    monkeypatch.setattr(dest, "render_caption", lambda *a, **k: "<b>broken")
    d = TelegramDestination(TelegramSettings(bot_token="t", channels={"en": "@c"}, require_illustration=False),
                            ledger_path=__import__("pathlib").Path("/nonexistent/ledger.jsonl"))
    job = SimpleNamespace(locale="en", publication_type="initial")
    with pytest.raises(DeliveryError, match="format check"):
        d.prepare(job, brief())


# ------------------------------------------------------------- length

def test_typical_captions_stay_near_the_target() -> None:
    for locale in ("en", "ua"):
        assert visible_length(render_caption(brief(locale), locale=locale, base_url=BASE)) <= CAPTION_TARGET


def test_a_huge_brief_fits_without_cutting_any_sentence() -> None:
    long = "Attackers exploit the Widget login bypass to plant web shells on exposed servers. " * 40
    p = brief(plain_summary=long, short_summary="Foo 4.2 " + long, why_it_matters=long,
              what_to_do=["A" * 400, "B" * 400], detail_body=long)
    cap = render_caption(p, locale="en", base_url=BASE, prefix="🔄 <b>Update</b>")
    assert visible_length(cap) <= CAPTION_LIMIT and "…" not in cap and format_problem(cap) is None
    assert cap.startswith("🔄 <b>Update</b>\n\n🧩 <b>")
    assert "Attackers exploit the Widget login bypass to plant web shells on exposed servers." in cap


def test_a_single_endless_sentence_is_dropped_not_cut() -> None:
    p = brief(plain_summary="word " * 400, short_summary="")
    cap = render_caption(p, locale="en", base_url=BASE)
    assert visible_length(cap) <= CAPTION_LIMIT and "word word" not in cap and "Source:" in cap


# ------------------------------------------------------------- language

def test_a_ukrainian_edition_with_an_english_body_is_refused() -> None:
    d = TelegramDestination(TelegramSettings(bot_token="t", channels={"ua": "@c"}, require_illustration=False),
                            ledger_path=__import__("pathlib").Path("/nonexistent/ledger.jsonl"))
    p = brief("ua", title="Хакери захоплюють сервери Widget",
              plain_summary="Attackers are taking over Widget servers that have not installed the latest fix.")
    with pytest.raises(DeliveryError, match="quality gate"):
        d.prepare(SimpleNamespace(locale="ua", publication_type="initial"), p)


def test_ukrainian_labels_are_natural_and_complete() -> None:
    p = brief("ua", title="Хакери захоплюють сервери Widget", plain_summary="Зловмисники захоплюють сервери Widget.",
              short_summary="Вразливість CVE-2026-1111 у Widget 4.2 вже використовують в атаках на сервери.",
              why_it_matters="Widget обслуговує сторінки входу багатьох компаній.",
              what_to_do=["Встановіть Widget 4.3."], affected_users=["Адміністратори Widget"])
    p["evidence"]["unknowns"] = ["scope_undisclosed"]
    cap = render_caption(p, locale="ua", base_url=BASE)
    for label in ("🎯 <b>Чому це важливо:</b>", "👥 <b>Кого стосується:</b>", "🛡️ <b>Що робити:</b>",
                  "❔ <b>Поки невідомо:</b> скільки постраждалих.", "🟠 <b>Рівень загрози: високий</b>",
                  "експлуатацію підтверджено", "🔗 <b>Джерело:</b>"):
        assert label in cap


# ------------------------------------------------------------- emoji vocabulary

@pytest.mark.parametrize("category, title, emoji", [
    ("vulnerability", "Widget flaw lets attackers in", "🧩"), ("malware", "Stealer hides in game launcher", "🦠"),
    ("phishing", "Fake invoices steal logins", "🎣"), ("breach", "Acme loses customer records", "🔓"),
    ("ransomware", "School network encrypted", "🔐"), ("other", "Iran-aligned spies breached a cloud", "🕵️"),
    ("vulnerability", "Siemens PLC flaw under attack", "🏭"), ("other", "Microsoft 365 sessions hijacked", "☁️"),
    ("other", "Cloudflare statistics for Q3 DDoS", "🔬"), ("other", "Ministry restructures IT office", ""),
])
def test_one_semantic_emoji(category: str, title: str, emoji: str) -> None:
    p = brief(category=category, level="Medium", title=title, plain_summary="A short summary.",
              affected_users=[], what_to_do=[])
    p["affected_platforms"] = []
    content = p["translations"]["en"]
    assert category_emoji(p, content) == emoji
    head = render_caption(p, locale="en", base_url=BASE).split("\n")[0]
    assert head == (f"{emoji} <b>{title}</b>" if emoji else f"<b>{title}</b>")


def test_emoji_are_navigation_not_decoration() -> None:
    cap = render_caption(brief(), locale="en", base_url=BASE)
    used = re.findall(r"[🧩🦠🎣🔓🔐🕵🏭☁🔬🎯⚙🛡👥⚠❔🔗🔴🟠🟡🔵]", cap)
    assert len(used) <= 8 and len(used) == len(set(used))         # each at most once


# ------------------------------------------------------------- delivery

def test_send_photo_carries_the_inline_button() -> None:
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})
    pub = TelegramPublisher("1:x", api_base="https://fake.invalid", client=httpx.Client(transport=httpx.MockTransport(handler)))
    buttons = render_buttons(brief(), locale="en", base_url=BASE)
    assert pub.send_photo("@c", f"{BASE}/media/abc/telegram.png", "caption", reply_markup=buttons) == 7
    assert seen[0]["reply_markup"] == buttons and seen[0]["photo"].endswith("/telegram.png")


# ------------------------------------------------------------- illustration matches the story

@pytest.mark.parametrize("text, expected", [
    ("APT29-Linked Hackers Hijack Web Analytics Script to Deliver iOS and Android Exploits", "script_injection"),
    ("Hackers hijack Convertr analytics script to steal payment card data", "script_injection"),
    ("Дослідники виявили, як розвідка рф зламувала смартфони через сайти з кодом Plerdy", "script_injection"),
    ("cPGuard Update Channel Hijacked to Backdoor Linux Servers via a malicious script", "exposed"),
])
def test_script_injection_stories_get_the_website_to_visitors_illustration(text: str, expected: str) -> None:
    from cyberalertx.media.illustrations import _event
    ev = SimpleNamespace(exploitation="not_reported", compromise="", campaign="")
    assert _event("vulnerability", ev, text) == expected
