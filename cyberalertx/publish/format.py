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


# ------------------------------------------------------------------ editorial layout
#
# One photo caption per edition, built from blocks:
#
#     🧩 <b>Headline</b>
#
#     TL;DR: one sentence (plain_summary).
#
#     What happened, only when it adds a name, product or number (short_summary).
#
#     🎯 <b>Why it matters:</b> …           ⚙️ <b>How it works:</b> …
#     👥 <b>Who is affected:</b> … · …      🛡️ <b>What to do:</b> • … • …
#     ⚠️ <b>Unconfirmed:</b> …              ❔ <b>Not yet known:</b> …
#
#     🟠 <b>Severity: High</b> · exploitation confirmed
#     🔗 <b>Source:</b> <a>BleepingComputer</a> · also CISA
#     #vulnerability #Windows
#     [📖 Read the full analysis]          ← inline keyboard button, not text
#
# Only fields of the reviewed brief, the stored severity and the evidence
# labels are used. Nothing is recalculated for presentation. Optional blocks
# are added by editorial priority while the caption stays near the target
# length; none is ever cut mid-sentence.

#: Telegram caps a photo caption at 1024 characters after entity parsing
#: (counted in UTF-16 code units, like entity offsets).
CAPTION_LIMIT = 1024
#: Optional sections are added while the caption stays within this length.
CAPTION_TARGET = 900
_TAG = re.compile(r"<[^>]+>")

# Hashtags make a post findable inside Telegram's own search. A small curated
# set: a wall of tags reads as spam.
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
_MAX_TAGS = 3

#: One semantic emoji per post, from the category. Topic emojis (industrial,
#: threat actor, cloud, research) are decided from the brief's own words.
_CATEGORY_EMOJI = {
    "vulnerability": "🧩", "exploit": "🧩", "zero-day": "🧩",
    "malware": "🦠", "spyware": "🦠", "botnet": "🦠",
    "phishing": "🎣", "scam": "🎣", "social engineering": "🎣",
    "breach": "🔓", "data leak": "🔓",
    "ransomware": "🔐",
}
_INDUSTRIAL = re.compile(
    r"\b(?:ICS|OT|SCADA|PLCs?|HMI|industrial|plant software|control systems?|refrigerat\w*|freezers?|fridges?|"
    r"building management)\b|промислов\w*|АСУ ТП|холодильн\w*|морозильн\w*|систем\w* керування будівл\w*",
    re.IGNORECASE)
_ACTOR = re.compile(
    r"\b(?:APT\s?\d+|state[- ](?:backed|sponsored)|nation[- ]state|spies|espionage|threat actors?|"
    r"(?:Russia|China|Iran|North Korea)[- ](?:linked|aligned|backed|nexus)|UAC-\d+|Volt Typhoon|Storm-\d+)\b|"
    r"угрупован\w*|кібершпигун\w*|шпигун\w*|UAC-\d+",
    re.IGNORECASE)
_MALWARE = re.compile(
    r"\b(?:malware|skimm\w*|backdoors?|stealers?|loaders?|trojans?|spyware|miners?)\b|шкідлив\w*|скимін\w*|бекдор\w*|"
    r"стилер\w*|троян\w*",
    re.IGNORECASE)
_CLOUD = re.compile(
    r"\b(?:cloud|SaaS|Microsoft 365|M365|Azure|AWS|Google Cloud|Kubernetes|tenants?|API keys?)\b|хмарн\w*",
    re.IGNORECASE)
_RESEARCH = re.compile(
    r"\b(?:research\w*|study|survey|analysis|ranks?|statistics|Q[1-4]|benchmark\w*|outscores?|test shows)\b|"
    r"дослідж\w*|звіт\w*|опитуван\w*|опитан\w*|аналітик\w*",
    re.IGNORECASE)

#: Severity, exactly the stored `threat_level`. An unknown value gets no line.
_LEVEL_DOT = {"Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🔵"}
_LEVEL_LABEL = {
    "en": {"Critical": "Critical", "High": "High", "Medium": "Medium", "Low": "Low"},
    "ua": {"Critical": "критичний", "High": "високий", "Medium": "середній", "Low": "низький"},
}
#: What the evidence labels CONFIRM, shown next to the severity. Doubts go to
#: the ⚠️ / ❔ lines instead, so the two are never blended.
_STATUS = {
    "en": {
        "exploitation:confirmed": "exploitation confirmed",
        "exploitation:attacks_observed": "attacks observed",
        "compromise:confirmed": "data exposure confirmed",
        "campaign:active": "campaign active",
        "campaign:disrupted": "campaign disrupted",
        "campaign:declined": "activity declined",
    },
    "ua": {
        "exploitation:confirmed": "експлуатацію підтверджено",
        "exploitation:attacks_observed": "зафіксовано атаки",
        "compromise:confirmed": "витік підтверджено",
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
    "en": {"why": "Why it matters:", "how": "How it works:", "do": "What to do:", "who": "Who is affected:",
           "unconfirmed": "Unconfirmed:", "unknown": "Not yet known:", "source": "Source:", "also": "also",
           "level": "Severity:", "button": "📖 Read the full analysis",
           "claim": "this comes from the attackers' own claim and has not been independently verified.",
           "suspected": "exploitation is suspected, not confirmed."},
    "ua": {"why": "Чому це важливо:", "how": "Як це працює:", "do": "Що робити:", "who": "Кого стосується:",
           "unconfirmed": "Не підтверджено:", "unknown": "Поки невідомо:", "source": "Джерело:", "also": "також",
           "level": "Рівень загрози:", "button": "📖 Читати повний розбір",
           "claim": "це заява самих зловмисників, незалежного підтвердження поки немає.",
           "suspected": "атаки підозрюють, але не підтвердили."},
}

_INCIDENT_CATEGORIES = frozenset({"breach", "data leak", "ransomware"})
#: Open questions the SOURCE states ("did not say whether data was taken").
#: `exploitation_unconfirmed` is inferred from the absence of wording, which
#: the brief may contradict, so it is never printed in the channel.
_PRINTABLE_UNKNOWNS = ("exposure_unconfirmed", "attribution_unconfirmed", "scope_undisclosed",
                       "timeline_undisclosed", "campaign_end_unconfirmed")

#: A statement by the attackers themselves ("NoName057(16) claimed…",
#: "хакери заявили…"). Presentation only: the evidence labels are untouched,
#: but a claim is never shown as an independently confirmed fact.
_CLAIM = re.compile(
    r"\b(?:hackers?|hacktivists?|group|gang|crew|actors?|attackers?|operators?)\b[^.;]{0,80}?"
    r"\b(?:claim(?:s|ed)?|took responsibility|say they|said they)\b"
    r"|\bclaim(?:s|ed)? (?:responsibility|to have)\b|\ballegedly\b|\baccording to the (?:hackers|group|attackers)\b"
    r"|(?:хакер\w*|угрупован\w*|груп[аиу]\b|хактивіст\w*|кіберпартизан\w*|зловмисник\w*)[^.;]{0,80}?"
    r"(?:заяви\w*|стверджу\w*|кажуть|взял\w* (?:на себе )?відповідальність)"
    r"|заяв\w* [^.;]{0,40}?(?:груп|угрупован|хакер|хактивіст)|відповідальність взял\w*|взял\w* (?:на себе )?відповідальність"
    r"|\bнібито\b|з (?:їхніх|його|її) слів|за (?:їхніми|його|її) словами|за заявою|заявник\w*",
    re.IGNORECASE)

#: Advice that is not about the affected systems at all ("don't buy chilled
#: products" under a refrigeration-controller attack). Never shown.
_OFF_TOPIC_ADVICE = re.compile(
    r"\b(?:don'?t|do not|avoid) (?:buy\w*|eat\w*|drink\w*|purchas\w*)\b|\b(?:chilled|frozen|food) (?:products?|goods|items)\b"
    r"|не (?:купуйте|їжте|беріть звідти)|(?:охолоджен|заморожен|харчов)\w* продукт\w*|теплих вітрин",
    re.IGNORECASE)

#: A sentence that explains the mechanism (used for ⚙️, from detail_body).
_MECHANISM = re.compile(
    r"\b(?:through|via|by (?:\w+ing)|using|uses|abus\w+|inject\w*|tamper\w*|disguis\w*|poison\w*|hijack\w*|"
    r"sideload\w*|trick\w*|lures?|redirect\w*|plants?|planted|came in)\b"
    r"|через |за допомогою|використову\w*|підміня\w*|вбудову\w*|маскує\w*|видає себе|підробля\w*|перенаправля\w*",
    re.IGNORECASE)
_SENTENCE_BREAK = re.compile(r'(?<=[.!?…])\s+(?=["«(A-ZА-ЯІЇЄҐ0-9])')


def _lab(locale: str) -> dict[str, str]:
    return _LABELS.get(locale, _LABELS["en"])


def _sentences(text: str) -> list[str]:
    text = " ".join((text or "").split())
    return [s for s in _SENTENCE_BREAK.split(text) if s] if text else []


def _first_sentence(text: str) -> str:
    """The first complete sentence. Never cut: a long sentence stays whole."""
    found = _sentences(text)
    return found[0] if found else ""


def category_emoji(payload: dict[str, Any], content: dict[str, Any]) -> str:
    """One semantic emoji for the headline, or '' when nothing fits."""
    category = str(payload.get("category") or "").lower()
    title = str(content.get("title") or "")
    words = " ".join([title, str(content.get("plain_summary") or ""), str(content.get("short_summary") or ""),
                      " ".join(str(x) for x in content.get("quick_facts") or []),
                      " ".join(str(x) for x in content.get("affected_users") or []),
                      " ".join(str(x) for x in payload.get("affected_platforms") or [])])
    if _INDUSTRIAL.search(words):
        return "🏭"
    if _ACTOR.search(title):                               # the headline is about the actor
        return "🕵️"
    if _RESEARCH.search(title) and payload.get("threat_level") in ("Low", "Medium"):
        return "🔬"                                        # findings, statistics, tests
    if category in _CATEGORY_EMOJI:
        return _CATEGORY_EMOJI[category]
    if _ACTOR.search(words) or _is_claim(content):
        return "🕵️"
    if _MALWARE.search(words):
        return "🦠"
    if _CLOUD.search(words):
        return "☁️"
    if _RESEARCH.search(words):
        return "🔬"
    return ""


def _is_claim(content: dict[str, Any]) -> bool:
    text = " ".join([str(content.get("title") or ""), str(content.get("plain_summary") or ""),
                     str(content.get("short_summary") or ""),
                     " ".join(str(x) for x in content.get("quick_facts") or [])])
    return bool(_CLAIM.search(text))


def status_line(payload: dict[str, Any], locale: str, *, claim: bool = False) -> str:
    """'🟠 Severity: High · exploitation confirmed' (plain text, no markup).

    The level is the stored `threat_level`, never recalculated; an unknown
    value yields '' rather than a guessed label. Only confirmed evidence is
    listed here; a claim never shows as a confirmed exposure."""
    lab = _lab(locale)
    level = str(payload.get("threat_level") or "")
    if level not in _LEVEL_DOT:
        return ""
    parts = [f"{_LEVEL_DOT[level]} {lab['level']} {_LEVEL_LABEL.get(locale, _LEVEL_LABEL['en'])[level]}"]
    ev = payload.get("evidence") or {}
    st = _STATUS.get(locale, _STATUS["en"])
    keys = ["exploitation", "campaign"]
    # Exposure is stated only where it is the story's subject; elsewhere a
    # capability ("malware that steals data") would read as a confirmed breach.
    if str(payload.get("category") or "").lower() in _INCIDENT_CATEGORIES and not claim:
        keys.insert(1, "compromise")
    for key in keys:
        phrase = st.get(f"{key}:{ev.get(key) or ''}")
        if phrase:
            parts.append(phrase)
    return " · ".join(parts)


def _unknowns(payload: dict[str, Any], locale: str) -> list[str]:
    names = _UNKNOWN.get(locale, _UNKNOWN["en"])
    have = set((payload.get("evidence") or {}).get("unknowns") or [])
    return [names[u] for u in _PRINTABLE_UNKNOWNS if u in have][:2]


def _actions(payload: dict[str, Any], content: dict[str, Any]) -> list[str]:
    """Up to two actions from `what_to_do`, when they are justified: High or
    Critical severity, confirmed exploitation or observed attacks, or a brief
    marked actionable. Off-topic advice is dropped, never rewritten.

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
        a = " ".join(str(a).split())
        if a and not _OFF_TOPIC_ADVICE.search(a) and not _is_near_duplicate(a, out):
            out.append(a)
        if len(out) == 2:
            break
    return out


def _mechanism(content: dict[str, Any], seen: Sequence[str]) -> str:
    """One sentence from the article analysis that says HOW it works, when it
    adds something the summary, detail and why lines do not."""
    for sentence in _sentences(str(content.get("detail_body") or ""))[:6]:
        if len(sentence) > 240 or not _MECHANISM.search(sentence):
            continue
        if not _is_near_duplicate(sentence, list(seen)):
            return sentence
    return ""


def _stems(text: str) -> set[str]:
    """5-letter stems of the content words: Ukrainian inflects, so 'сайти'
    and 'сайтах' must count as the same word."""
    return {w[:5] for w in _content_words(text)}


def _restates(candidate: str, seen: str, threshold: float = 0.45) -> bool:
    """True when `candidate` mostly repeats `seen` and adds at most one new
    name or number. Calibrated on the live corpus: at 45 % stem overlap the
    paragraphs that merely restate the TL;DR go, and the ones that add a CVE,
    a vendor or the mechanism stay."""
    cand = _stems(candidate)
    if not cand:
        return False
    overlap = len(cand & _stems(seen)) / len(cand)
    return overlap >= threshold and len(_anchor_tokens(candidate) - _anchor_tokens(seen)) <= 1


_LEAD_VERB = {
    # "reports THAT …" only: "reports attackers chaining …" would leave a fragment.
    "en": re.compile(r"^\s*(?:reports?|reported|says?|said|writes?|notes?) that\s+(?=\S)", re.IGNORECASE),
    "ua": re.compile(r"^\s*(?:повідомля\w+|пише|пишуть|зазнача\w+|розповіда\w+),\s*що\s+(?=\S)", re.IGNORECASE),
}


def _strip_outlet_lead(text: str, locale: str, outlets: Sequence[str]) -> str:
    """Drop "BleepingComputer reports (that)" / "dev.ua повідомляє, що" when the
    outlet is the story's own source, already named on the source line. Only
    a lead-in followed by a complete clause is removed; "повідомляє про …"
    carries content and stays."""
    for outlet in sorted((o.strip() for o in outlets if o and o.strip()), key=len, reverse=True):
        if text.lower().startswith(outlet.lower()):
            m = _LEAD_VERB.get(locale, _LEAD_VERB["en"]).match(text[len(outlet):])
            if m:
                rest = text[len(outlet) + m.end():].strip()
                if len(rest) >= 40:
                    return rest[0].upper() + rest[1:]
            break
    return text


def _tags(payload: dict[str, Any]) -> str:
    tags: list[str] = []
    category = str(payload.get("category", "")).lower()
    if category in _CATEGORY_TAG:
        tags.append(_CATEGORY_TAG[category])
    for platform in payload.get("affected_platforms") or []:
        slug = re.sub(r"[^0-9A-Za-z]+", "", str(platform))
        if slug and len(slug) <= 20 and slug.lower() not in (t.lower() for t in tags):
            tags.append(slug)
    return " ".join(f"#{t}" for t in tags[:_MAX_TAGS])


def render_buttons(payload: dict[str, Any], *, locale: str, base_url: str) -> dict[str, Any]:
    """The inline keyboard: one button to the full CyberAlertX article."""
    return {"inline_keyboard": [[{"text": _lab(locale)["button"],
                                  "url": deep_link(base_url, locale, str(payload.get("id", "")))}]]}


def _blocks(payload: dict[str, Any], *, locale: str) -> list[tuple[str, str, int]]:
    """(name, html, priority) in display order. Priority 0 = always shown;
    higher numbers are optional and added in ascending order."""
    content = (payload.get("translations") or {}).get(locale)
    if not content:
        raise ValueError(f"payload has no '{locale}' translation")
    title = (content.get("title") or "").strip()
    if not title:
        raise ValueError("payload translation has no title")
    lab = _lab(locale)
    claim = _is_claim(content)

    outlets = [str(payload.get("source") or "")] + [str(x) for x in payload.get("corroborating_sources") or []]
    plain = (content.get("plain_summary") or "").strip()
    short = _strip_outlet_lead(_strip_attribution((content.get("short_summary") or "").strip(), locale),
                               locale, outlets)
    tldr = _first_sentence(plain or short)
    what = ""
    if plain and short and not _restates(short, f"{title} {tldr}"):
        if _adds_anchor(short, tldr) and not _is_near_duplicate(short, [tldr]):
            what = short
    shown = f"{title} {tldr} {what}"
    why = _first_sentence(str(content.get("why_it_matters") or ""))
    if why and (_is_near_duplicate(why, [tldr, what]) or _restates(why, shown)):
        why = ""
    how = _mechanism(content, [tldr, what, why])
    if how and _restates(how, f"{shown} {why}"):
        how = ""
    who_list = [" ".join(str(x).split()) for x in content.get("affected_users") or [] if str(x).strip()][:3]
    who = " · ".join(who_list)
    # Short audience labels share the product name with the headline by
    # nature; only a list that is almost entirely repetition is dropped.
    if who and (_is_near_duplicate(who, [tldr, what]) or _restates(who, shown, threshold=0.6)):
        who = ""
    actions = _actions(payload, content)

    doubts = []
    if claim:
        doubts.append(lab["claim"])
    if (payload.get("evidence") or {}).get("exploitation") == "suspected":
        doubts.append(lab["suspected"])
    unknowns = _unknowns(payload, locale)

    emoji = category_emoji(payload, content)
    head = f"{emoji} <b>{_text(title)}</b>" if emoji else f"<b>{_text(title)}</b>"
    out: list[tuple[str, str, int]] = [("head", head, 0)]
    if tldr:
        out.append(("tldr", _text(tldr), 0))
    if what:
        out.append(("what", _text(what), 4))
    if why:
        out.append(("why", f"🎯 <b>{_text(lab['why'])}</b> {_text(why)}", 2))
    if how:
        out.append(("how", f"⚙️ <b>{_text(lab['how'])}</b> {_text(how)}", 6))
    if who:
        out.append(("who", f"👥 <b>{_text(lab['who'])}</b> {_text(who)}", 5))
    if len(actions) == 1:
        out.append(("do", f"🛡️ <b>{_text(lab['do'])}</b> {_text(actions[0])}", 1))
    elif actions:
        out.append(("do", "\n".join([f"🛡️ <b>{_text(lab['do'])}</b>", *(f"• {_text(a)}" for a in actions)]), 1))
    if doubts:                                   # accuracy: never optional
        out.append(("unconfirmed", f"⚠️ <b>{_text(lab['unconfirmed'])}</b> {_text(' '.join(doubts))}", 0))
    if unknowns:
        out.append(("unknown", f"❔ <b>{_text(lab['unknown'])}</b> {_text('; '.join(unknowns))}.", 3))

    footer: list[str] = []
    status = status_line(payload, locale, claim=claim)
    if status:
        dot, _, rest = status.partition(" ")
        label, _, tail = rest.partition(" · ")
        footer.append(f"{dot} <b>{_text(label)}</b>" + (f" · {_text(tail)}" if tail else ""))
    source = str(payload.get("source") or "").strip()
    source_url = str(payload.get("source_url") or "").strip()
    also = ", ".join(_bullets(payload.get("corroborating_sources"), 2))
    if source:
        src = (f'<a href="{_esc(source_url)}">{_text(source)}</a>'
               if source_url.startswith(("https://", "http://")) else _text(source))
        line = f"🔗 <b>{_text(lab['source'])}</b> {src}"
        if also:
            line += f" · {_text(lab['also'])} {_text(also)}"
        footer.append(line)
    if footer:
        out.append(("footer", "\n".join(footer), 0))
    tags = _tags(payload)
    if tags:
        out.append(("tags", tags, 7))
    return out


def _assemble(blocks: list[tuple[str, str, int]], keep: set[str], prefix: str) -> str:
    body: list[str] = []
    for name, html_block, _ in blocks:
        if name not in keep:
            continue
        if name == "tags" and body:              # tags sit under the footer, no gap
            body[-1] = f"{body[-1]}\n{html_block}"
        else:
            body.append(html_block)
    text = "\n\n".join(body)
    return f"{prefix}\n\n{text}" if prefix else text


def visible_length(html_text: str) -> int:
    """Length Telegram counts for an HTML-formatted text (tags removed)."""
    plain = html.unescape(_TAG.sub("", html_text))
    return len(plain.encode("utf-16-le")) // 2


def render_caption(payload: dict[str, Any], *, locale: str, base_url: str = "", prefix: str = "") -> str:
    """The post as a photo caption: at most CAPTION_LIMIT, about CAPTION_TARGET.

    Required blocks (headline, TL;DR, unconfirmed claims, severity and source)
    are always present. Optional sections are added in editorial priority
    order (action, why it matters, open questions, what happened, who is
    affected, how it works, tags) while the caption stays within the target;
    a section that does not fit is skipped whole. Nothing is cut
    mid-sentence. `prefix` (an update marker) counts towards the limit.

    Raises ValueError if the edition has no translation or no title.
    """
    blocks = _blocks(payload, locale=locale)
    keep = {name for name, _, prio in blocks if prio == 0}
    if visible_length(_assemble(blocks, keep, prefix)) > CAPTION_LIMIT:
        # Pathological brief: drop the TL;DR rather than cut it.
        keep.discard("tldr")
    for name, _, prio in sorted((b for b in blocks if b[2] > 0), key=lambda b: b[2]):
        trial = keep | {name}
        if visible_length(_assemble(blocks, trial, prefix)) <= CAPTION_TARGET:
            keep = trial
    return _assemble(blocks, keep, prefix)


def render_message(payload: dict[str, Any], *, locale: str, base_url: str = "") -> str:
    """The same post as a text message (fallback when no photo is sent)."""
    return render_caption(payload, locale=locale, base_url=base_url)


def format_problem(caption: str) -> str | None:
    """Structural check of a rendered caption, run before every send: only
    Telegram-supported tags, balanced, links to http(s) only, within limits."""
    if visible_length(caption) > CAPTION_LIMIT:
        return "caption over the 1024-character limit"
    stack: list[str] = []
    for m in re.finditer(r"<(/?)([a-z]+)([^>]*)>", caption):
        closing, tag, attrs = m.group(1), m.group(2), m.group(3)
        if tag not in ("b", "i", "a", "code"):
            return f"unsupported tag <{tag}>"
        if closing:
            if not stack or stack.pop() != tag:
                return f"unbalanced </{tag}>"
        else:
            if tag == "a" and not re.fullmatch(r' href="https?://[^"\s<>]+"', attrs):
                return "link without a valid http(s) href"
            stack.append(tag)
    if stack:
        return f"unclosed <{stack[-1]}>"
    if re.search(r"<(?![/a-z])|&(?!(?:amp|lt|gt|quot|#\d+);)", caption):
        return "unescaped markup character"
    return None


__all__ = ["CAPTION_LIMIT", "CAPTION_TARGET", "category_emoji", "deep_link", "format_problem", "notify",
           "quality_problem", "render_buttons", "render_caption", "render_message", "status_line",
           "visible_length"]
