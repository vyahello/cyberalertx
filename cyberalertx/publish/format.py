"""Render a published ThreatPost payload into a Telegram HTML message.

We use Telegram's **HTML** parse mode rather than MarkdownV2: HTML needs only
three characters escaped (`&`, `<`, `>`) instead of MarkdownV2's ~18, so it's
far harder to produce a malformed message that Telegram rejects.

Input is the merged dict produced by `_PostService.render()` (see
api/app.py:render) — top-level shared metadata plus a `translations` sub-object
keyed by locale. We pull the requested locale's text content from there.
"""
from __future__ import annotations

import html
import re
from typing import Any, Sequence

# Bare CVE identifiers (e.g. "CVE-2026-45247") that the AI writes into the
# summary / quick facts are plain text — Telegram doesn't auto-link them. We
# turn each into a link to its canonical NVD page (the URL is deterministic
# from the id, so this needs no lookup against the references array).
_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)


# Telegram hard-caps a message at 4096 chars. We aim well below and trim the
# summary if a render is unusually long.
_MAX_SUMMARY_CHARS = 600


# `short_summary` opens with a source-attribution clause by contract
# (templates.py). The message already names the outlet on its own line, so
# pasting the clause into the body says it twice and buries the fact three
# words deep. Deliberately conservative — it strips only a leading
# "<outlet> повідомляє:" up to a COLON. A summary like "The Hacker News
# повідомляє про хвилю атак … Афганістану," is left alone on purpose: there
# the "про …" clause carries real content, and a greedy variant amputated it.
_ATTR_LEAD: dict[str, re.Pattern[str]] = {
    "ua": re.compile(
        r"^[^:»]{2,45}?\s*\b(?:повідомля\w+|попереджа\w+|пише|пишуть"
        r"|зазнача\w+|переказу\w+|розповіда\w+|наводить)"
        r"\s*(?:про\s+|що\s+)?:\s+",
        re.IGNORECASE,
    ),
    "en": re.compile(
        r"^[^:]{2,45}?\s*\b(?:reports?|reported|warns?|warned|says?|writes?)"
        r"\s*(?:that\s+|on\s+|about\s+)?:\s+",
        re.IGNORECASE,
    ),
}

_LATIN_RUN = re.compile(r"[A-Za-z][A-Za-z0-9.+_-]*[A-Za-z0-9]")
_DIGIT_RE = re.compile(r"[0-9]")
_OUTLET_TOKENS: frozenset[str] = frozenset({
    "bleepingcomputer", "cisa", "securelist", "kaspersky", "the", "hacker",
    "news", "krebs", "dev.ua", "itc.ua", "ain.ua", "cert-ua", "certua",
})


def _bullets(values: Any, limit: int) -> list[str]:
    return [str(v).strip() for v in (values or []) if str(v).strip()][:limit]


#: Function words, so the duplicate check compares what a bullet is ABOUT.
#: Both languages are listed because either can appear in either locale's
#: payload — a UA render routinely carries English product names, and the
#: comparison must not call two bullets alike on "the" and "your".
_DUP_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "your",
    "you", "that", "any", "is", "are", "it", "this", "with", "from", "at",
    "by", "be", "not", "no", "do", "don", "if", "all", "after", "every",
    "і", "й", "та", "у", "в", "на", "з", "із", "до", "що", "це", "як",
    "для", "якщо", "не", "а", "о", "вже", "усі", "всі", "свої", "своїх",
})
_DUP_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

#: Two bullets saying the same thing in different words. Measured against the
#: live corpus: the model routinely writes one instruction into two lists —
#: on the Cisco SD-WAN post `what_to_do[1]` is "Remove SD-WAN Manager admin
#: accounts that nobody on your team created" while `if_already_affected[0]`
#: is "Disable any SD-WAN Manager admin account that nobody on your team
#: created". Merging the lists without this check reads WORSE than the four
#: separate headings did.
_DUP_JACCARD = 0.6
#: Containment catches the other shape: one bullet restating another in fewer
#: words, where Jaccard is dragged down by the longer bullet's extra clause.
_DUP_CONTAINMENT = 0.8


def _content_words(text: str) -> frozenset[str]:
    return frozenset(
        w for w in (t.lower() for t in _DUP_WORD_RE.findall(text or ""))
        if len(w) > 2 and w not in _DUP_STOPWORDS
    )


def _is_near_duplicate(candidate: str, chosen: Sequence[str]) -> bool:
    """True when `candidate` repeats something already selected."""
    cand = _content_words(candidate)
    if not cand:
        return False
    for other in chosen:
        seen = _content_words(other)
        if not seen:
            continue
        if len(cand & seen) / len(cand | seen) >= _DUP_JACCARD:
            return True
        if len(cand & seen) / min(len(cand), len(seen)) >= _DUP_CONTAINMENT:
            return True
    return False


def _strip_attribution(text: str, locale: str) -> str:
    """Drop a leading "<outlet> повідомляє:" clause, restoring sentence case.

    Returns `text` unchanged when stripping would leave too little to be a
    sentence — a summary that is *only* an attribution clause is better shown
    whole than shown empty.
    """
    pattern = _ATTR_LEAD.get(locale, _ATTR_LEAD["en"])
    match = pattern.match(text)
    if match is None:
        return text
    out = text[match.end():].strip()
    if len(out) < 40:
        return text
    return out[0].upper() + out[1:] if out[:1].islower() else out


def _anchor_tokens(text: str) -> set[str]:
    """Product / actor names in a string. Outlet names are attribution, not a
    fact about the threat, so they never justify a second paragraph."""
    return {
        m.group(0).lower() for m in _LATIN_RUN.finditer(text or "")
        if len(m.group(0)) >= 2 and m.group(0).lower() not in _OUTLET_TOKENS
    }


def _adds_anchor(candidate: str, baseline: str) -> bool:
    """True when `candidate` names a product, an actor or a number that
    `baseline` does not — the test for whether a second paragraph carries
    information rather than repeating the first."""
    if _anchor_tokens(candidate) - _anchor_tokens(baseline):
        return True
    return bool(_DIGIT_RE.search(candidate)) and not _DIGIT_RE.search(baseline)


def _esc(text: str) -> str:
    """Escape the three characters that are special in Telegram HTML mode."""
    return html.escape(text or "", quote=False)


def _linkify_cves(escaped_text: str) -> str:
    """Wrap CVE identifiers in a link to their NVD detail page.

    Runs on already-escaped text. CVE ids contain only `[A-Z0-9-]`, so they're
    untouched by HTML-escaping and safe to match/wrap here without re-escaping.
    """
    def _repl(m: re.Match[str]) -> str:
        cve = m.group(0).upper()
        return f'<a href="https://nvd.nist.gov/vuln/detail/{cve}">{m.group(0)}</a>'

    return _CVE_RE.sub(_repl, escaped_text)


# A `backticked` span — the prompt asks the model to wrap commands, paths,
# hashes, IPs and domains this way. Single line, non-empty, no nested ticks.
_CODE_SPAN_RE = re.compile(r"`([^`\n]{1,200})`")


def _text(raw: str) -> str:
    """Escape, render `code` spans, linkify CVEs — the body-text treatment.

    Code spans become `<code>` and are kept out of the CVE linkifier:
    Telegram does not allow an entity nested inside `<code>`. An unpaired
    backtick is left as a literal character.
    """
    out: list[str] = []
    last = 0
    for m in _CODE_SPAN_RE.finditer(raw or ""):
        out.append(_linkify_cves(_esc(raw[last:m.start()])))
        out.append(f"<code>{_esc(m.group(1))}</code>")
        last = m.end()
    out.append(_linkify_cves(_esc((raw or "")[last:])))
    return "".join(out)


def deep_link(base_url: str, locale: str, fingerprint: str) -> str:
    """Public detail-page URL: {base}/{locale}/threat/{fingerprint}."""
    return f"{base_url.rstrip('/')}/{locale}/threat/{fingerprint}"


# Scripts that should never appear in either of our locales. The existing
# language validator compares Cyrillic against Latin counts, so a stray CJK
# or Arabic run scores as neither and slips through — a real cached post
# carries "攻擊穿過автентифікацію" in its quick facts. Nothing we publish is
# ever legitimately in these blocks.
_FOREIGN_SCRIPT_RE = re.compile(
    "["
    "一-鿿"   # CJK unified ideographs
    "぀-ヿ"   # Hiragana + Katakana
    "가-힯"   # Hangul
    "؀-ۿ"   # Arabic
    "֐-׿"   # Hebrew
    "ऀ-ॿ"   # Devanagari
    "]"
)


def quality_problem(payload: dict[str, Any], *, locale: str) -> str | None:
    """Return a reason string if this post shouldn't be published, else None.

    A pre-send gate that runs BEFORE formatting. The render path already drops
    wrong-script *titles* per locale, but not summaries — and a stale cache
    entry can still carry an English body on a UA-target render. We re-check
    both here so a half-translated card never reaches the channel.

    Every field the MESSAGE actually renders is checked, not a sample. That
    distinction caused a real defect: `render_message` leads with
    `plain_summary`, while this gate used to inspect `short_summary` only, so
    a payload with a Ukrainian summary and an English plain-language line
    shipped English text to the Ukrainian channel.
    """
    content = (payload.get("translations") or {}).get(locale)
    if not content:
        return f"no '{locale}' translation"

    title = (content.get("title") or "").strip()
    if not title:
        return "empty title"

    # Local import keeps the ai → publish dependency one-way and off the hot path.
    from ..ai.validation import _wrong_script_for_language

    # Exactly the fields `render_message` puts on screen, in the order it
    # uses them.
    checked: list[tuple[str, str]] = [
        ("title", title),
        ("plain_summary", (content.get("plain_summary") or "").strip()),
        ("short_summary", (content.get("short_summary") or "").strip()),
    ]
    checked += [
        (f"what_to_do[{n}]", str(a).strip())
        for n, a in enumerate(content.get("what_to_do") or [])
        if str(a).strip()
    ]
    # Not sliced to what the renderer happens to show: the action line picks
    # across all three lists and the selection shifts with the post's
    # content, so the gate inspects every bullet that could reach the card.
    checked += [
        (f"what_not_to_do[{n}]", str(a).strip())
        for n, a in enumerate(content.get("what_not_to_do") or [])
        if str(a).strip()
    ]
    checked += [
        (f"if_already_affected[{n}]", str(a).strip())
        for n, a in enumerate(content.get("if_already_affected") or [])
        if str(a).strip()
    ]
    checked += [
        (f"am_i_affected[{n}]", str(a).strip())
        for n, a in enumerate(content.get("am_i_affected") or [])
        if str(a).strip()
    ]
    # `affected_users` is DELIBERATELY not checked. Its entries are 3-6-word
    # labels like "Адміни TeamCity On-Premises", where the Latin product name
    # pushes the script ratio past `_TARGET_LANGUAGE_MIN_RATIO`. A large share
    # of cached UA posts would be blocked from the channel by a gate that is
    # meant to catch untranslated bodies, not product names.

    for field_name, text in checked:
        if not text:
            continue
        if _wrong_script_for_language(text, locale):
            return f"{field_name} in wrong script for {locale!r}"
        stray = _FOREIGN_SCRIPT_RE.search(text)
        if stray:
            return f"{field_name} contains foreign-script character {stray.group(0)!r}"

    return None


# Hashtags make a post findable inside Telegram's own search and let readers
# follow one theme across the channel. Only a small curated set — a wall of
# tags reads as spam and dilutes the ones that matter.
_CATEGORY_TAG = {
    "phishing": "phishing",
    "ransomware": "ransomware",
    "vulnerability": "vulnerability",
    "breach": "breach",
    "data leak": "dataleak",
    "exploit": "exploit",
    "zero-day": "zeroday",
    "malware": "malware",
    "spyware": "spyware",
    "scam": "scam",
    "botnet": "botnet",
    "social engineering": "socialengineering",
}


def notify(payload: dict[str, Any]) -> bool:
    """Should this post buzz subscribers' phones?

    Critical always. `urgent_action` only when the severity agrees — that flag
    is a keyword score over the ENGLISH source article
    (pipeline/actionability.py) and a single "in the wild" clears the
    threshold, so it pushed a Medium post whose first action read "Звичайним
    абонентам робити нічого не треба". A push that opens with "nothing to do"
    teaches people to mute the channel, and a muted channel cannot deliver the
    one alert that needed to interrupt someone's day.
    """
    level = payload.get("threat_level")
    return level == "Critical" or (
        payload.get("actionability_level") == "urgent_action"
        and level == "High"
    )


# Evidence status and severity, localized. Severity is potential impact; the
# status line says what the source establishes. They are never merged.
_LEVEL_LABEL = {
    "en": {"Critical": "Critical", "High": "High", "Medium": "Medium", "Low": "Low"},
    "ua": {"Critical": "Критичний", "High": "Високий", "Medium": "Середній", "Low": "Низький"},
}
_STATUS = {
    "en": {
        "exploitation:confirmed": "exploitation confirmed",
        "exploitation:attacks_observed": "attacks observed",
        "exploitation:suspected": "suspected, not confirmed",
        "compromise:confirmed": "data exposure confirmed",
        "compromise:not_confirmed": "exposure not confirmed",
        "campaign:active": "campaign active",
        "campaign:disrupted": "campaign disrupted",
        "campaign:declined": "activity declined",
    },
    "ua": {
        "exploitation:confirmed": "експлуатацію підтверджено",
        "exploitation:attacks_observed": "зафіксовано атаки",
        "exploitation:suspected": "підозра, не підтверджено",
        "compromise:confirmed": "витік підтверджено",
        "compromise:not_confirmed": "витік не підтверджено",
        "campaign:active": "кампанія триває",
        "campaign:disrupted": "кампанію припинено",
        "campaign:declined": "активність спала",
    },
}
_UNKNOWN = {
    "en": {"exposure_unconfirmed": "whether data was taken", "exploitation_unconfirmed": "whether it is being exploited",
           "scope_undisclosed": "how many are affected", "timeline_undisclosed": "when it started",
           "attribution_unconfirmed": "who is behind it", "campaign_end_unconfirmed": "whether it has really stopped"},
    "ua": {"exposure_unconfirmed": "чи було викрадено дані", "exploitation_unconfirmed": "чи вразливість уже використовують",
           "scope_undisclosed": "скільки постраждалих", "timeline_undisclosed": "коли це почалося",
           "attribution_unconfirmed": "хто за цим стоїть", "campaign_end_unconfirmed": "чи справді це припинилося"},
}
_LABELS = {
    "en": {"why": "Why it matters:", "do": "What to do:", "unknown": "Not yet known:", "source": "Source:",
           "read": "Read more:", "brief": "the full brief on CyberAlertX", "level": "Severity",
           "also": "Also reported by"},
    "ua": {"why": "Чому це важливо:", "do": "Що робити:", "unknown": "Поки невідомо:", "source": "Джерело:",
           "read": "Детальніше:", "brief": "повний розбір на CyberAlertX", "level": "Рівень",
           "also": "Також повідомили"},
}
_MAX_TAGS = 2


def _first_sentence(text: str, limit: int = 260) -> str:
    text = " ".join(text.split())
    m = re.match(r"(.+?[.!?…])(\s|$)", text)
    out = m.group(1) if m else text
    return out if len(out) <= limit else out[: limit - 1].rsplit(" ", 1)[0] + "…"


def status_line(payload: dict[str, Any], locale: str) -> str:
    """'Severity: High · exploitation confirmed' — severity and evidence side by side."""
    lab = _LABELS.get(locale, _LABELS["en"])
    level = str(payload.get("threat_level") or "")
    parts = []
    if level:
        parts.append(f"{lab['level']}: {_LEVEL_LABEL.get(locale, _LEVEL_LABEL['en']).get(level, level)}")
    ev = payload.get("evidence") or {}
    st = _STATUS.get(locale, _STATUS["en"])
    keys = ["exploitation", "campaign"]
    # Exposure is stated only where it is the story's subject; elsewhere a
    # capability ("malware that steals data") would read as a confirmed breach.
    if str(payload.get("category") or "").lower() in _INCIDENT_CATEGORIES:
        keys.insert(1, "compromise")
    for key in keys:
        phrase = st.get(f"{key}:{ev.get(key) or ''}")
        if phrase:
            parts.append(phrase)
    return " · ".join(parts)


_INCIDENT_CATEGORIES = frozenset({"breach", "data leak", "ransomware"})
#: Open questions the SOURCE states ("did not say whether data was taken").
#: `exploitation_unconfirmed` is inferred from the absence of wording, which
#: the brief may contradict, so it is never printed in the channel.
_PRINTABLE_UNKNOWNS = frozenset({"exposure_unconfirmed", "scope_undisclosed", "timeline_undisclosed",
                                 "attribution_unconfirmed", "campaign_end_unconfirmed"})


def _unknown_line(payload: dict[str, Any], locale: str) -> str:
    unknowns = [u for u in ((payload.get("evidence") or {}).get("unknowns") or [])
                if u in _PRINTABLE_UNKNOWNS and u in _UNKNOWN.get(locale, _UNKNOWN["en"])]
    if not unknowns:
        return ""
    lab = _LABELS.get(locale, _LABELS["en"])
    return f"{lab['unknown']} {_UNKNOWN.get(locale, _UNKNOWN['en'])[unknowns[0]]}."


def _actions(payload: dict[str, Any], content: dict[str, Any]) -> list[str]:
    """Up to two actions, when they are justified: High/Critical severity,
    confirmed exploitation or observed attacks, or a brief marked actionable.

    Two, not one: a single step kept dropping the one that makes the first
    take effect ("install the patch" without "then reboot"). The full
    checklist stays on the article page."""
    ev = payload.get("evidence") or {}
    justified = (str(payload.get("actionability_level") or "informational") != "informational"
                 or str(payload.get("threat_level") or "") in ("High", "Critical")
                 or ev.get("exploitation") in ("confirmed", "attacks_observed"))
    if not justified:
        return []
    out: list[str] = []
    for a in content.get("what_to_do") or []:
        a = str(a).strip()
        if a and not _is_near_duplicate(a, out):
            out.append(a)
        if len(out) == 2:
            break
    return out


def _tags(payload: dict[str, Any]) -> str:
    tags: list[str] = []
    category = str(payload.get("category", "")).lower()
    if category in _CATEGORY_TAG:
        tags.append(_CATEGORY_TAG[category])
    for platform in payload.get("affected_platforms") or []:
        slug = re.sub(r"[^0-9A-Za-z]+", "", str(platform))
        if slug and slug.lower() not in tags:
            tags.append(slug)
    return " ".join(f"#{t}" for t in tags[:_MAX_TAGS])


def render_message(payload: dict[str, Any], *, locale: str, base_url: str) -> str:
    """Build the HTML post for one edition.

        <b>Headline</b>

        What happened and what is affected (plain_summary).

        The specifics, only when they add a name, number or product (short_summary).

        <b>Why it matters:</b> one grounded sentence (why_it_matters).

        Severity: High · exploitation confirmed
        Not yet known: whether data was taken.          (first open question, if any)

        <b>What to do:</b> one or two actions           (only when actionable)

        Also reported by CISA, The Hacker News          (story clustering, if any)
        Source: <a>BleepingComputer</a>
        Read more: <a>the full brief on CyberAlertX</a>
        #vulnerability #Windows

    Only fields of the reviewed brief and the evidence labels are used: the
    post adds nothing the brief and its source do not state. Severity and
    evidence stay separate. Sections without content are omitted.

    Raises ValueError if the edition has no translation or no title.
    """
    content = (payload.get("translations") or {}).get(locale)
    if not content:
        raise ValueError(f"payload has no '{locale}' translation")
    title = (content.get("title") or "").strip()
    if not title:
        raise ValueError("payload translation has no title")
    lab = _LABELS.get(locale, _LABELS["en"])

    plain = (content.get("plain_summary") or "").strip()
    short = (content.get("short_summary") or "").strip()
    summary = plain or short
    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[: _MAX_SUMMARY_CHARS - 1].rstrip() + "…"
    detail = ""
    if plain and short and _adds_anchor(short, plain):
        detail = _strip_attribution(short, locale)
        if len(detail) > _MAX_SUMMARY_CHARS:
            detail = ""
    why = _first_sentence(str(content.get("why_it_matters") or ""))
    if why and (_is_near_duplicate(why, [summary, detail])):
        why = ""

    lines: list[str] = [f"<b>{_text(title)}</b>"]
    for para in (summary, detail):
        if para:
            lines += ["", _text(para)]
    if why:
        lines += ["", f"<b>{_text(lab['why'])}</b> {_text(why)}"]
    status = status_line(payload, locale)
    unknown = _unknown_line(payload, locale)
    if status or unknown:
        lines.append("")
        if status:
            lines.append(_text(status))
        if unknown:
            lines.append(_text(unknown))
    actions = _actions(payload, content)
    if len(actions) == 1:
        lines += ["", f"<b>{_text(lab['do'])}</b> {_text(actions[0])}"]
    elif actions:
        lines += ["", f"<b>{_text(lab['do'])}</b>", *(f"• {_text(a)}" for a in actions)]

    lines.append("")
    corroborating = _bullets(payload.get("corroborating_sources"), 3)
    if corroborating:
        lines.append(f"{_text(lab['also'])} {_text(', '.join(corroborating))}")
    source = str(payload.get("source") or "").strip()
    source_url = str(payload.get("source_url") or "").strip()
    if source and source_url.startswith(("https://", "http://")):
        lines.append(f'{_text(lab["source"])} <a href="{_esc(source_url)}">{_text(source)}</a>')
    elif source:
        lines.append(f"{_text(lab['source'])} {_text(source)}")
    link = deep_link(base_url, locale, payload.get("id", ""))
    lines.append(f'{_text(lab["read"])} <a href="{_esc(link)}">{_text(lab["brief"])}</a>')
    tags = _tags(payload)
    if tags:
        lines.append(tags)
    return "\n".join(lines)


__all__ = ["render_message", "deep_link", "quality_problem", "notify", "status_line"]


# Telegram caps a photo caption at 1024 characters after entity parsing
# (counted in UTF-16 code units, like entity offsets).
CAPTION_LIMIT = 1024
_TAG = re.compile(r"<[^>]+>")


def visible_length(html_text: str) -> int:
    """Length Telegram counts for an HTML-formatted text (tags removed)."""
    plain = html.unescape(_TAG.sub("", html_text))
    return len(plain.encode("utf-16-le")) // 2


def render_caption(payload: dict[str, Any], *, locale: str, base_url: str) -> str:
    """The post as a photo caption, within CAPTION_LIMIT.

    The full post when it fits (nearly all do). Otherwise blocks are dropped
    from the least to the most essential: the detail paragraph, the action,
    the status lines, "why it matters"; as a last resort the summary is
    trimmed. Headline, source and read-more link are always kept.
    """
    full = render_message(payload, locale=locale, base_url=base_url)
    if visible_length(full) <= CAPTION_LIMIT:
        return full
    blocks = full.split("\n\n")
    head, links = blocks[0], blocks[-1]
    middle = blocks[1:-1]
    lab = _LABELS.get(locale, _LABELS["en"])
    summary = middle[0] if middle and not middle[0].startswith("<b>") else ""
    rest = [b for b in middle if b is not summary]

    def kind(b: str) -> int:   # higher = dropped earlier
        if b.startswith(f"<b>{_text(lab['why'])}"):
            return 1
        if b.startswith(f"<b>{_text(lab['do'])}"):
            return 3
        if b.startswith(_text(lab["level"])) or b.startswith(_text(lab["unknown"])):
            return 2
        return 4               # the detail paragraph
    keep = sorted(rest, key=kind)
    while keep:
        text = "\n\n".join([head, summary, *[b for b in middle if b in keep], links])
        if visible_length(text) <= CAPTION_LIMIT:
            return text
        keep.pop()
    budget = CAPTION_LIMIT - visible_length(f"{head}\n\n\n\n{links}") - 1
    plain = html.unescape(_TAG.sub("", summary))
    if budget < 40 or not plain:
        return f"{head}\n\n{links}"
    trimmed = plain[:budget].rsplit(" ", 1)[0].rstrip(",;:—–- ") + "…"
    return f"{head}\n\n{_esc(trimmed)}\n\n{links}"
