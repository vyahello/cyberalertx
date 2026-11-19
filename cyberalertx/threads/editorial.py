"""Threads editorial writer: bilingual EN/UA posts written from the source evidence.

The Threads post is not the website edition re-cut. One call per story writes
an English and a Ukrainian post *independently* from the source article
(outlet headline, source text, publication date), never from our own edition
text: the edition may carry generated advice or relative time words that the
source does not support (the first test posts showed both).

A draft is a structured object (hook, what happened, why it matters, optional
advice backed by a source quote, the incident status, every material fact
with the source sentence that supports it). It is then checked by
deterministic gates, with no model judging itself:

* **accuracy**: every number, CVE id and Latin-script name in either post
  occurs in the source;
* **evidence integrity**: every listed fact quotes the source verbatim; a
  claim or an investigation is written as one; no exploitation, confirmation
  or fix the source does not report; no generic advice (antivirus scans,
  password resets, "patch now"...) the source does not give;
* **time**: no relative time words ("today", "in the past day"), which go
  stale when a post is sent hours later;
* **EN/UA equivalence**: the same numbers, identifiers, organisations,
  status and advice in both languages;
* **form**: the hook does not repeat the headline, the paragraphs do not
  repeat each other, no hashtags or links in the text, within the limit
  (500, target 470) without cutting anything.

Scores (1-5) follow from those checks; a draft is publishable only when the
hard gates hold (accuracy, integrity and equivalence = 5; clarity,
readability, editorial value and overall >= 4). A failing draft is never
published (the job fails as `invalid_content`); nothing is truncated or
patched by code.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping, Protocol

from pydantic import BaseModel, Field

from .format import TEXT_LIMIT, TOPIC_TAG, ThreadsPost, threads_length

logger = logging.getLogger(__name__)

#: Above this the post is long for Threads; 500 stays the hard limit.
EDITORIAL_TARGET = 470
STATUSES = (
    "confirmed_incident", "reported_incident", "alleged_claim", "under_investigation", "vulnerability_disclosed",
    "exploited_in_the_wild", "proof_of_concept", "patch_available", "patching_urged", "fix_announced",
    "law_enforcement_action", "analysis_or_research", "other",
)
AUDIENCES = ("", "end_users", "it_admins", "security_engineers", "developers", "organizations",
             "incident_responders")
ATTRIBUTION = {"en": "Reporting", "ua": "Джерело"}
GATES = {"factual_accuracy": 5, "evidence_integrity": 5, "en_ua_equivalence": 5, "technical_clarity": 4,
         "readability": 4, "editorial_value": 4, "overall": 4, "image_relevance": 5}

#: Bump when the gates change: a stored draft that failed older checks is rewritten once.
CHECKS_VERSION = "2026-11-19.4"


# ------------------------------------------------------------------ response model

class Part(BaseModel):
    hook: str = Field(description="First line: a specific reason to stop scrolling. Not the headline.")
    what: str = Field(description="What happened: who, what, how, what is confirmed or alleged. 1-2 sentences.")
    why: str = Field(description="One editorial insight grounded in the facts: why it matters. 1-2 sentences.")
    advice: str = Field(default="", description="Practical step for a named audience, ONLY when the source gives "
                                                "it; otherwise empty.")


class Fact(BaseModel):
    claim_en: str
    claim_ua: str
    quote: str = Field(description="The exact sentence fragment from the SOURCE TEXT or SOURCE HEADLINE that "
                                   "supports the claim, copied verbatim.")


class Name(BaseModel):
    en: str
    ua: str = Field(description="How the Ukrainian post writes the same organisation/product (often identical).")


class Prompt(BaseModel):
    en: str = ""
    ua: str = ""


class DraftResponse(BaseModel):
    status: Literal[STATUSES] = "other"  # type: ignore[valid-type]
    en: Part
    ua: Part
    facts: list[Fact] = Field(default_factory=list)
    names: list[Name] = Field(default_factory=list)
    audience: Literal[AUDIENCES] = ""  # type: ignore[valid-type]
    advice_quote: str = ""
    discussion_prompt: Prompt = Field(default_factory=Prompt)
    omitted: str = ""


# ------------------------------------------------------------------ evidence

@dataclass(frozen=True)
class Evidence:
    article_id: str
    outlet: str
    headline: str                      # the source's own headline
    text: str                          # the source text we hold (feed text)
    url: str
    published_at: str                  # ISO
    edition_titles: tuple[str, ...]    # our EN/UA headlines: the hook must not repeat them
    image_alt: Mapping[str, str] = field(default_factory=dict)
    signals: Mapping[str, str] = field(default_factory=dict)

    @property
    def corpus(self) -> str:
        return f"{self.headline}\n{self.text}"

    def digest(self) -> str:
        raw = json.dumps([self.article_id, self.headline, self.text, self.outlet, self.published_at,
                          sorted(self.image_alt.items())], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def published_label(self) -> str:
        try:
            d = datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))
        except ValueError:
            return ""
        return d.astimezone(timezone.utc).strftime("%-d %B %Y")


def evidence_from(payload: Mapping[str, Any], item: Any) -> Evidence:
    """Evidence for a publication payload: the anchor article as stored
    (`item`, a NewsItem with title/source/url/raw_content/published_at)."""
    tr = payload.get("translations") or {}
    ill = ((payload.get("media") or {}).get("illustration") or {})
    ev = payload.get("evidence") or {}
    return Evidence(
        article_id=str(payload.get("id", "")),
        outlet=str(payload.get("source") or getattr(item, "source", "") or ""),
        headline=str(getattr(item, "title", "") or ""),
        text=str(getattr(item, "raw_content", "") or "")[:3000],
        url=str(getattr(item, "url", "") or payload.get("source_url") or ""),
        published_at=str(payload.get("published_at") or getattr(item, "published_at", "") or ""),
        edition_titles=tuple(str((tr.get(loc) or {}).get("title") or "") for loc in ("en", "ua")),
        image_alt={k: str(v) for k, v in (ill.get("alt") or {}).items()},
        signals={"exploitation": str(ev.get("exploitation", "")), "compromise": str(ev.get("compromise", ""))},
    )


# ------------------------------------------------------------------ prompt

SYSTEM = """You are the senior editor of CyberAlertX, a bilingual (English and Ukrainian) cybersecurity
publication. You write one short Threads post per language about one story, from the SOURCE evidence only.

VOICE: professional, technically informed, calm, evidence-led, specific, natural. Write like an experienced
security editor who has read the reporting, not like an RSS feed or a press release. No clickbait, no fear,
no hype words, no emojis, no hashtags, no exclamation marks, no rhetorical questions.

STRUCTURE (per language):
- hook: one line (at most 100 characters) that gives a reason to stop scrolling and makes complete sense
  as the very first thing a reader sees in the feed. It carries the story's most consequential specific:
  a number, a named organisation or product, an unexpected technical detail, or a clear security
  implication. It never refers back to something not yet said ("the list", "too", "also", "this", "it").
  Never repeat or paraphrase the headline. Do not force a number. Good shapes, for illustration only:
    "178 organizations. One third-party platform. Malicious JavaScript."
    "A vulnerable HTTP/2 implementation can turn an ordinary server into a remote code execution target."
    "Four suspects arrested in a ransomware investigation tied to more than $40.5 million in payments."
    "A compromised package can reach developers before they even realize the dependency has changed."
- what: what actually happened. Who, which products/systems/organisations, the reported mechanism, and
  what is confirmed versus alleged versus under investigation. Concrete details from the source.
- why: one genuine editorial insight that adds value beyond the headline, grounded in the facts or a
  clearly established technical implication (for example: why a third-party script reaches every site
  that loads it; why an investigation is not a confirmed breach). Do not restate "what".
- advice: ONLY if the source itself gives a concrete step; name the audience (e.g. "Site administrators:").
  Otherwise leave it empty. Never invent antivirus scans, password resets, device resets, "patch now",
  disabling systems or rotating credentials.

FACTUAL RULES (strict):
- Every number, name, product, CVE id and status must come from SOURCE HEADLINE or SOURCE TEXT. If the
  source does not say it, leave it out. Write figures as digits.
- Keep the source's distinctions exactly: confirmed / reported / alleged / under investigation / potentially
  affected / exploited in the wild / proof of concept / patched / patching urged / fix announced but not
  released. A claim by attackers or an investigation into claims is NOT a confirmed breach. A vulnerability
  is NOT exploited unless the source says so. A capability is not proof of use.
- No relative time words (today, yesterday, this morning, in the past day, last 24 hours, this week;
  сьогодні, вчора, за останню добу...). Posts are sent hours later. Use an absolute date only when it adds
  value, and only the date given as ARTICLE DATE.
- Keep the image consistent: the post must not contradict the IMAGE ALT TEXT.

LANGUAGES: write the Ukrainian post as natural, professional Ukrainian, not a word-for-word translation.
Both posts must contain exactly the same facts, numbers, organisations, CVE ids, status, caveats and advice.
In Ukrainian write decimals with a comma (40,5 млн; 6,4 млн), as Ukrainian readers expect.
Keep official product/organisation names and CVE ids as written in the source (Latin script), unless an
established Ukrainian name exists (e.g. ФБР for FBI) - then list the pair in `names`.

LENGTH: hook + what + why (+ advice) must be about 230-330 characters per language; a source line and
link (~90 characters) are added after it. Short paragraphs. Choose the strongest factual angle rather
than cramming everything in.

ALSO RETURN: `status` (one value), `facts` (each material claim with the exact supporting quote copied
from the source), `names` (organisations/products named, EN and UA forms), `audience` (only with advice),
`advice_quote` (the source sentence giving the advice, else empty), an optional `discussion_prompt` (a
meaningful, technical question for a follow-up; may be empty; it is never published automatically) and
`omitted` (important source details you left out)."""


def user_prompt(ev: Evidence, feedback: list[str] | None = None) -> str:
    body = {
        "SOURCE OUTLET": ev.outlet,
        "SOURCE HEADLINE": ev.headline,
        "SOURCE TEXT": ev.text,
        "ARTICLE DATE": ev.published_label(),
        "CYBERALERTX HEADLINES (do not repeat in the hook)": [t for t in ev.edition_titles if t],
        "IMAGE ALT TEXT": dict(ev.image_alt),
    }
    out = "Write the EN and UA Threads posts for this story.\n\n" + json.dumps(body, ensure_ascii=False, indent=1)
    if feedback:
        out += ("\n\nYour previous draft failed these checks; fix every one and keep all rules:\n- "
                + "\n- ".join(feedback))
    return out


# ------------------------------------------------------------------ checks

_NUM = re.compile(r"\d+(?:[.,   ]\d+)*")
_CVE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)
_LATIN = re.compile(r"(?<![\w-])[A-Z][A-Za-z0-9]*(?:[-./][A-Za-z0-9]+)*(?![\w-])|(?<![\w-])[A-Z]{2,}[0-9]*(?![\w-])")
#: Capitalised English words that are not names (sentence starts are skipped separately).
_PLAIN_EN = {"The", "A", "An", "This", "That", "These", "Those", "It", "Its", "In", "On", "At", "For", "With", "By",
             "From", "As", "If", "When", "Why", "What", "How", "One", "Two", "Three", "Four", "Five", "No", "Not",
             "Site", "Sites", "Administrators", "Developers", "Security", "Organizations", "Users", "Reporting",
             "Illustration", "Researchers", "Attackers", "Police", "Investigators", "Ukrainian", "English"}
#: Generic technical vocabulary that is not an organisation or product name.
_TECH = {"JavaScript", "HTTP", "HTTPS", "HTTP/2", "HTTP/3", "TLS", "SSL", "DNS", "API", "APIs", "SQL", "CSP", "VPN",
         "SSH", "RCE", "MFA", "2FA", "IT", "AI", "OT", "ICS", "URL", "URLs", "PDF", "SMS", "USB", "CPU", "GPU",
         "PoC", "CVE", "CVSS", "KEV", "IoT", "SaaS", "OAuth", "Wi-Fi", "Bluetooth", "Linux", "Android", "iOS"}
_RELATIVE = {
    "en": re.compile(r"\b(?:today|yesterday|tonight|tomorrow|this (?:morning|afternoon|evening|week|weekend)|"
                     r"last night|(?:past|last) (?:day|24 hours|hour|few hours|week)|earlier today|just now|"
                     r"right now|over the weekend|hours ago|days ago)\b", re.I),
    "ua": re.compile(r"сьогодні|вчора|учора|завтра|цього (?:ранку|тижня)|минулої (?:ночі|доби)|за останн\w* (?:добу|"
                     r"24 години|годин\w*|тиждень)|щойно|годин\w* тому|дн\w* тому", re.I),
}
_HEDGE = {
    "en": re.compile(r"claim|alleg|unconfirmed|not (?:yet )?(?:been )?confirmed|investigat|says it|say they|"
                     r"according to the (?:gang|group|attackers)", re.I),
    "ua": re.compile(r"заяв|нібито|не підтвердж|розслід|стверджу|за словами|перевіря", re.I),
}
_CONFIRMED_EN = re.compile(r"(?<!not )(?<!un)\bconfirm(?:ed|s)\b", re.I)
_CONFIRMED_UA = re.compile(r"(?<!не )\bпідтверди(?:в|ла|ли|ло)\b|(?<!не )\bпідтверджено\b", re.I)
_EXPLOIT_TEXT = {
    "en": re.compile(r"actively exploited|exploited in the wild|in the wild|under active attack|being exploited|"
                     r"(?<!not )(?<!no evidence it was )\bexploited\b", re.I),
    "ua": re.compile(r"активно експлуат|експлуатують|експлуатувал|(?<!не )використовують в атаках", re.I),
}
_EXPLOIT_SOURCE = re.compile(r"exploit|in the wild|under (?:active )?attack|attacks?\b|abus", re.I)
_ADVICE_FAMILIES = [
    (re.compile(r"antivirus|anti-virus|malware scan|антивірус", re.I), re.compile(r"antivirus|anti-virus|scan", re.I)),
    (re.compile(r"(?:reset|change) (?:your |all )?passwords?|password reset|змін\w* парол|скин\w* парол", re.I),
     re.compile(r"password", re.I)),
    (re.compile(r"factory reset|reset (?:your|the) device|скидан\w* до заводськ", re.I), re.compile(r"reset", re.I)),
    (re.compile(r"(?:patch|update|upgrade) (?:now|immediately|right away)|негайно (?:онов|встанов)", re.I),
     re.compile(r"patch|update|upgrade|fix", re.I)),
    (re.compile(r"(?:rotate|revoke|replace) (?:your |all )?(?:credentials|keys|tokens|secrets)|"
                r"(?:відклич|замін)\w* (?:ключ|токен|облікові дані)", re.I),
     re.compile(r"rotat|revok|credential|token|secret", re.I)),
    (re.compile(r"\bdisable\b|вимкн", re.I), re.compile(r"disabl", re.I)),
]
_DISABLE = len(_ADVICE_FAMILIES) - 1          # index of the "disable" family

#: Established Ukrainian forms of names that are not kept in Latin script (stems).
_UA_FORMS = {
    "Ukraine": "Україн", "Ukrainian": "україн", "Ireland": "Ірланд", "Irish": "ірланд", "Germany": "Німеч",
    "German": "німец", "France": "Франц", "French": "француз", "Japan": "Япон", "Japanese": "япон",
    "China": "Кита", "Chinese": "китайськ", "Russia": "Росі", "Russian": "російськ", "Britain": "Британ",
    "British": "британськ", "UK": "Британ", "US": "США", "USA": "США", "United States": "США",
    "America": "Америк", "American": "американськ", "Europe": "Європ", "European": "європейськ",
    "Netherlands": "Нідерланд", "Dutch": "нідерландськ", "Poland": "Польщ", "Canada": "Канад",
    "Australia": "Австралі", "Asia": "Азі", "Taiwan": "Тайван", "Taiwanese": "тайванськ", "Korea": "Коре", "North": "Північн", "South": "Півден", "DPRK": "КНДР",
    "North Korea": "Північн", "North Korean": "північнокорейськ", "Iran": "Іран", "Israel": "Ізраїл",
    "India": "Інді", "Singapore": "Сінгапур", "Spain": "Іспані", "Italy": "Італі",
    "FBI": "ФБР", "Europol": "Європол", "Interpol": "Інтерпол", "EU": "ЄС", "NATO": "НАТО",
    "Microsoft": "Microsoft", "Telegram": "Telegram", "January": "січ", "February": "лют", "March": "берез",
    "April": "квіт", "May": "трав", "June": "черв", "July": "лип", "August": "серп", "September": "верес",
    "October": "жовт", "November": "листопад", "December": "груд",
}

#: A first line that only makes sense after something else ("Equifax and Ledger were on the list too.").
_DANGLING = {
    "en": re.compile(r"\b(?:the list|too\b|also\b|as well\b|this one|the same)|^(?:it|they|this|these|that)\b", re.I),
    "ua": re.compile(r"\b(?:у переліку|у списку|також|теж|так само)\b|^(?:це|вони|воно|вона|він|ці)\b", re.I),
}
#: A claim, allegation or investigation *into the incident* ("Federal Bureau of
#: Investigation" or "hackers under investigation" is not one).
_CLAIM_SOURCE = re.compile(r"\bclaim(?:s|ed)?\b|alleg|leak site|"
                           r"\binvestigat\w* (?:a |the |an? |into (?:a |the )?)?(?:possible |potential |suspected |"
                           r"reported )?(?:breach|hack|cyberattack|attack|incident|security incident|"
                           r"data (?:breach|leak|theft)|intrusion|claims?|reports?)", re.I)
_CONFIRM_SOURCE = re.compile(r"\bconfirm(?:ed|s)\b|disclosed that|acknowledged|admitted", re.I)
_CLICKBAIT = re.compile(r"shocking|you won't believe|\bmassive\b|terrifying|breaking news|^breaking\b|alarming|"
                        r"\bhuge\b|nightmare|!|шокуюч|жахлив|терміново!", re.I)
_EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿]")


def _norm_num(s: str) -> str:
    s = re.sub(r"[   ]", "", s)
    if re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", s):
        return re.sub(r"[,.]", "", s)
    return s.replace(",", ".")


def _numbers(text: str) -> set[str]:
    return {_norm_num(n) for n in _NUM.findall(_CVE.sub(" ", text))}


def _cves(text: str) -> set[str]:
    return {c.upper() for c in _CVE.findall(text)}


def _norm_text(s: str) -> str:
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def _latin_names(text: str) -> set[str]:
    out: set[str] = set()
    for sent in re.split(r"(?<=[.!?:])\s+|\n+", text):
        for i, m in enumerate(_LATIN.finditer(sent)):
            w = m.group(0).rstrip(".")
            if (i == 0 and m.start() == 0 and not w.isupper() and not re.search(r"\d|[a-z][A-Z]", w)) \
                    or w in _PLAIN_EN or w in _TECH or re.sub(r"-[a-z]+$", "", w) in _TECH or len(w) < 2:
                continue
            out.add(w)
    return out


def _stems(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[^\W\d_]{3,}", text.lower())}


def _overlap(a: str, b: str) -> float:
    sa = _stems(a)
    return len(sa & _stems(b)) / len(sa) if sa else 0.0


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _parts(p: Part) -> list[str]:
    return [x.strip() for x in (p.hook, p.what, p.why, p.advice) if x and x.strip()]


def compose(draft: DraftResponse, locale: str, *, outlet: str, url: str) -> str:
    part = draft.en if locale == "en" else draft.ua
    body = "\n\n".join(_parts(part))
    return f"{body}\n\n{ATTRIBUTION[locale]}: {outlet}\n{url}"


@dataclass
class Review:
    problems: dict[str, list[str]]            # gate -> problems
    scores: dict[str, int]
    lengths: dict[str, int]

    @property
    def publishable(self) -> bool:
        return all(self.scores.get(g, 0) >= floor for g, floor in GATES.items()) and not any(self.problems.values())

    def flat(self) -> list[str]:
        return [f"{g}: {p}" for g, ps in self.problems.items() for p in ps]


#: Status labels drawn on V4 images ('EXPLOITED', 'PATCH AVAILABLE'): words, not names.
_LABEL_WORDS = {"SECURITY", "ADVISORY", "EXPLOITED", "PATCH", "PATCHED", "PATCHING", "AVAILABLE", "URGED", "OVER",
                "ACTIVELY", "CRITICAL", "UPDATE", "FIX", "BREACH", "NOTICE", "DATA", "RANSOMWARE", "ARRESTED",
                "CHARGED", "SEIZED", "WARNING", "ALERT", "MALWARE", "SCAM", "PHISHING", "AUTHORITIES", "POLICE",
                "UKRAINIAN", "DISCLOSED", "ZERO-DAY", "ZERO", "DAY", "KNOWN", "EXPLOITED", "VULNERABILITIES", "VULNERABILITY",
                "FLAWS", "FLAW", "AFFECTED", "LEAKED", "STOLEN", "RECORDS", "USERS", "ACCOUNTS"}


def image_problems(ev: Evidence) -> list[str]:
    """The canonical image travels with the post: its alt text (which describes
    what is drawn) must not state a number or a name that neither the source
    nor our own headline gives - the picture would tell another story."""
    ref = "\n".join([ev.corpus, *ev.edition_titles, ev.outlet])
    allowed, ref_l = _numbers(ref) | _numbers(ev.published_label()), _norm_text(ref)
    out: list[str] = []
    for loc, alt in sorted(ev.image_alt.items()):
        for n in sorted(_numbers(alt) - allowed):
            out.append(f"{loc} image alt text states '{n}', which the source does not")
        if loc != "en":
            continue                      # names are checked on the EN alt (UA keeps Latin names identical)
        for name in sorted(_latin_names(re.sub(r"^\S+:\s*", "", alt))):
            if name.upper() in _LABEL_WORDS or all(w in _LABEL_WORDS for w in name.upper().split()):
                continue
            if _norm_text(name) not in ref_l:
                out.append(f"{loc} image alt text names '{name}', which the source does not")
    return out


#: As long as a real deep link (https://cyberalertx.com/ua/threat/<16 hex>), so the
#: length gate measures the post as it will be sent.
SAMPLE_URL = "https://cyberalertx.com/ua/threat/0000000000000000"


def check(draft: DraftResponse, ev: Evidence, *, url: str = SAMPLE_URL) -> Review:
    """The deterministic gates and the scores that follow from them."""
    corpus = ev.corpus
    allowed_numbers = _numbers(corpus) | _numbers(ev.published_label()) | _numbers(ev.outlet)
    corpus_l = _norm_text(corpus) + " " + _norm_text(ev.outlet)
    p: dict[str, list[str]] = {k: [] for k in ("accuracy", "integrity", "time", "equivalence", "form", "image")}
    p["image"] = image_problems(ev)
    texts = {"en": " ".join(_parts(draft.en)), "ua": " ".join(_parts(draft.ua))}
    lengths = {loc: threads_length(compose(draft, loc, outlet=ev.outlet, url=url)) for loc in ("en", "ua")}

    for loc, t in texts.items():
        if not (draft.en if loc == "en" else draft.ua).hook.strip():
            p["form"].append(f"{loc}: no hook")
        for n in _numbers(t) - allowed_numbers:
            p["accuracy"].append(f"{loc}: number '{n}' is not in the source")
        for c in _cves(t) - _cves(corpus):
            p["accuracy"].append(f"{loc}: {c} is not in the source")
        if _RELATIVE[loc].search(t):
            p["time"].append(f"{loc}: relative time reference '{_RELATIVE[loc].search(t).group(0)}'")  # type: ignore[union-attr]
        if "#" in t or re.search(r"https?://|www\.", t, re.I):
            p["form"].append(f"{loc}: hashtag or link inside the text")
        if len(_EMOJI.findall(t)) > 1:
            p["form"].append(f"{loc}: emojis")
        if lengths[loc] > TEXT_LIMIT:
            p["form"].append(f"{loc}: {lengths[loc]} characters, over the {TEXT_LIMIT} limit")
        # advice the source does not give
        part = draft.en if loc == "en" else draft.ua
        for i, (family, source_kw) in enumerate(_ADVICE_FAMILIES):
            # "Police took the servers down" (вимкнула сервери) is narration, not
            # advice: the disable family is checked on the advice line only.
            scope = part.advice if i == _DISABLE else t
            if family.search(scope) and not source_kw.search(corpus):
                p["integrity"].append(f"{loc}: unsupported advice '{family.search(scope).group(0)}'")  # type: ignore[union-attr]
    # names: every Latin-script name in either post is in the source
    for loc, t in texts.items():
        for n in _latin_names(t):
            if _norm_text(n) not in corpus_l:
                p["accuracy"].append(f"{loc}: name '{n}' is not in the source")
    # facts: quoted verbatim from the source
    if not draft.facts:
        p["integrity"].append("no facts listed with source quotes")
    corpus_n = _norm_text(corpus)
    for f in draft.facts:
        # An elided quote ("Experts say the incident ... was exacerbated") is verbatim
        # piece by piece; every piece must be in the source.
        pieces = [x for x in re.split(r"\s*(?:\.\.\.|…)\s*", _norm_text(f.quote)) if x]
        if not pieces or any(x not in corpus_n for x in pieces):
            p["integrity"].append(f"fact not quoted from the source: '{f.quote[:60]}'")
    # status: claims stay claims, exploitation and confirmation only when reported
    claim_only = bool(_CLAIM_SOURCE.search(corpus)) and not _CONFIRM_SOURCE.search(corpus)
    if claim_only:
        if draft.status not in ("alleged_claim", "under_investigation"):
            p["integrity"].append(f"status '{draft.status}' for a story the source reports as a claim/investigation")
        for loc in ("en", "ua"):
            if not _HEDGE[loc].search(texts[loc]):
                p["integrity"].append(f"{loc}: the claim/investigation is not marked as such")
    if not _CONFIRM_SOURCE.search(corpus):
        if _CONFIRMED_EN.search(texts["en"]):
            p["integrity"].append("en: says 'confirmed' but the source reports no confirmation")
        if _CONFIRMED_UA.search(texts["ua"]):
            p["integrity"].append("ua: says 'confirmed' but the source reports no confirmation")
    if not _EXPLOIT_SOURCE.search(corpus):
        for loc in ("en", "ua"):
            if _EXPLOIT_TEXT[loc].search(texts[loc]):
                p["integrity"].append(f"{loc}: describes exploitation the source does not report")
        if draft.status == "exploited_in_the_wild":
            p["integrity"].append("status 'exploited_in_the_wild' without exploitation in the source")
    if bool(draft.en.advice.strip()) != bool(draft.ua.advice.strip()):
        p["equivalence"].append("advice present in one language only")
    if (draft.en.advice.strip() or draft.ua.advice.strip()) and \
            (not draft.advice_quote.strip() or _norm_text(draft.advice_quote) not in _norm_text(corpus)):
        p["integrity"].append("advice without a source quote")
    # EN/UA equivalence
    ne, nu = _numbers(texts["en"]), _numbers(texts["ua"])
    if ne != nu:
        p["equivalence"].append(f"numbers differ: EN {sorted(ne)} vs UA {sorted(nu)}")
    if _cves(texts["en"]) != _cves(texts["ua"]):
        p["equivalence"].append("CVE ids differ between EN and UA")
    pairs = [(n.en, n.ua) for n in draft.names]
    for name in _latin_names(texts["en"]):
        ua_forms = [u for e, u in pairs if _norm_text(name) in _norm_text(e)] + [name]
        ua_forms += [_UA_FORMS[name]] if name in _UA_FORMS else []
        if not any(_norm_text(u) in _norm_text(texts["ua"]) for u in ua_forms):
            p["equivalence"].append(f"'{name}' is in EN but not in UA (if UA writes it in Ukrainian, add the "
                                    f"pair to `names`)")
    for name in _latin_names(texts["ua"]):
        en_forms = [e for e, u in pairs if _norm_text(name) in _norm_text(u)] + [name]
        if not any(_norm_text(e) in _norm_text(texts["en"]) for e in en_forms):
            p["equivalence"].append(f"'{name}' is in UA but not in EN")
    # form: a hook that stands alone, no headline repetition, no paragraph repeating another
    for loc, part in (("en", draft.en), ("ua", draft.ua)):
        if _DANGLING[loc].search(part.hook):
            p["form"].append(f"{loc}: the hook refers back to something not yet said ('{part.hook[:50]}')")
        if len(part.hook) > 120:
            p["form"].append(f"{loc}: the hook is longer than 120 characters")
        for title in [ev.headline, *ev.edition_titles]:
            if title and _overlap(part.hook, title) >= 0.75:
                p["form"].append(f"{loc}: the hook repeats the headline")
                break
        if part.what and _overlap(part.what, part.hook) >= 0.75:
            p["form"].append(f"{loc}: 'what happened' repeats the hook")
        if part.why and _overlap(part.why, part.what) >= 0.7:
            p["form"].append(f"{loc}: 'why it matters' repeats 'what happened'")

    scores = _score(draft, p, texts, lengths)
    return Review(problems={k: v for k, v in p.items()}, scores=scores, lengths=lengths)


def _score(draft: DraftResponse, p: dict[str, list[str]], texts: dict[str, str], lengths: dict[str, int]) -> dict[str, int]:
    def words_per_sentence(t: str) -> float:
        ss = _sentences(t)
        return sum(len(s.split()) for s in ss) / len(ss) if ss else 99.0

    specific = re.compile(r"\d|CVE-|[A-Z][a-z]+[A-Z]|\b[A-Z]{2,}\b")
    hook_ok = not any("hook repeats" in x for x in p["form"])
    standalone = not any("hook refers back" in x for x in p["form"])
    hook = (5 if specific.search(draft.en.hook) and len(draft.en.hook) <= 100 else 4) if hook_ok and standalone \
        else 2
    clarity = 5 if specific.search(draft.en.what) and specific.search(draft.ua.what) else (
        4 if draft.en.what and draft.ua.what else 2)
    value = 2
    if draft.en.why and draft.ua.why:
        value = 5 if _overlap(draft.en.why, draft.en.what) < 0.4 else (4 if _overlap(draft.en.why, draft.en.what) < 0.6
                                                                       else 3)
    wps = max(words_per_sentence(texts["en"]), words_per_sentence(texts["ua"]))
    readability = 5 if wps <= 22 else (4 if wps <= 28 else 3)
    if any("repeats" in x for x in p["form"]) or max(lengths.values()) > EDITORIAL_TARGET:
        readability = min(readability, 3)
    tone = 3 if _CLICKBAIT.search(texts["en"]) or _CLICKBAIT.search(texts["ua"]) or any("emojis" in x or "hashtag" in x for x in p["form"]) else 5
    scores = {
        "hook_quality": hook,
        "factual_accuracy": 5 if not p["accuracy"] else 1,
        "evidence_integrity": 5 if not (p["integrity"] or p["time"]) else 1,
        "technical_clarity": clarity,
        "editorial_value": value,
        "readability": readability,
        "en_ua_equivalence": 5 if not p["equivalence"] else 1,
        "professional_tone": tone,
        "image_relevance": 5 if not p["image"] else 1,
    }
    soft = [scores[k] for k in ("hook_quality", "technical_clarity", "editorial_value", "readability",
                                "professional_tone")]
    scores["overall"] = min(min(scores.values()), round(sum(soft) / len(soft)))
    return scores


# ------------------------------------------------------------------ writer and store

_SCORE_HINTS = {
    "hook_quality": "the hook must carry a concrete specific (a number, a named product or organisation) in at "
                    "most 100 characters and must not echo the headline",
    "technical_clarity": "'what' must name the product/organisation and the mechanism concretely in both languages",
    "editorial_value": "'why' must add an insight beyond 'what', in both languages",
    "readability": "use shorter sentences (at most about 22 words) and keep each post near 400 characters",
    "professional_tone": "remove hype words (massive, huge, alarming, shocking), exclamation marks and emojis",
}


class JsonProvider(Protocol):
    def generate_json(self, system: str, user: str, *, schema: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass
class Draft:
    article_id: str
    evidence_digest: str
    response: DraftResponse
    review: Review
    model: str
    generated_at: str
    attempts: int
    history: list[list[str]] = field(default_factory=list)
    complete: bool = True               # False: stopped for time; the next run continues it

    def to_dict(self) -> dict[str, Any]:
        return {"article_id": self.article_id, "evidence_digest": self.evidence_digest,
                "response": self.response.model_dump(), "problems": self.review.problems,
                "scores": self.review.scores, "lengths": self.review.lengths, "publishable": self.review.publishable,
                "model": self.model, "generated_at": self.generated_at, "attempts": self.attempts,
                "history": self.history, "checks": CHECKS_VERSION, "complete": self.complete}


#: Seconds a writer attempt may take (the CLI provider's own timeout plus a margin).
WRITE_RESERVE_S = 130.0


class EditorialDeferred(RuntimeError):
    """No time left in this run for a writer attempt; the next run continues."""


def write(ev: Evidence, provider: JsonProvider, *, model: str = "", attempts: int = 2,
          clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
          remaining: Callable[[], float] | None = None, resume: Mapping[str, Any] | None = None) -> Draft:
    """One story, both languages; one retry with the failed checks as feedback.

    `remaining` (seconds left in this run) stops before an attempt that might
    not finish: the draft so far is returned with `complete=False` (or
    EditorialDeferred raised when nothing was written), and `resume` (that
    stored draft) continues it on the next run with the same feedback."""
    schema = DraftResponse.model_json_schema()
    feedback: list[str] | None = None
    best: tuple[DraftResponse, Review] | None = None
    history: list[list[str]] = []
    n = 0
    if resume:
        best_resp = DraftResponse.model_validate(resume["response"])
        best = (best_resp, check(best_resp, ev))
        history = [list(h) for h in resume.get("history") or []]
        n = int(resume.get("attempts") or len(history))
        feedback = _feedback(best[1])
    while n < attempts:
        if remaining is not None and remaining() < WRITE_RESERVE_S:
            if best is None:
                raise EditorialDeferred("no time left in this run for the editorial writer")
            break
        n += 1
        raw = provider.generate_json(SYSTEM, user_prompt(ev, feedback), schema=schema)
        resp = DraftResponse.model_validate(raw)
        review = check(resp, ev)
        history.append(review.flat())
        if best is None or review.publishable or _rank(review) >= _rank(best[1]):
            best = (resp, review)        # keep the better attempt, not merely the last
        if review.publishable:
            break
        feedback = _feedback(review)
    assert best is not None
    complete = best[1].publishable or n >= attempts
    return Draft(ev.article_id, ev.digest(), best[0], best[1], model, clock().isoformat(), n, history, complete)


def _rank(review: Review) -> tuple[int, int, int]:
    hard = sum(len(v) for v in review.problems.values())
    return (int(review.publishable), -hard, review.scores.get("overall", 0))


def _feedback(review: Review) -> list[str]:
    over = [f"the {loc.upper()} post is {n} characters with the source line and link; cut hook+what+why by at "
            f"least {n - 440} characters" for loc, n in review.lengths.items() if n > EDITORIAL_TARGET]
    return review.flat() + over or [_SCORE_HINTS.get(k, f"raise {k}") for k, v in review.scores.items()
                             if k != "overall" and v < 4] or ["make the post stronger overall"]


class DraftStore:
    """{article_id: draft} in one JSON file, written atomically. A draft is
    reused while the evidence is unchanged, so a retry or a reconciliation
    after an uncertain send always uses the same text."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, article_id: str, digest: str) -> dict[str, Any] | None:
        d = self._read().get(article_id)
        return d if isinstance(d, dict) and d.get("evidence_digest") == digest else None

    def put(self, draft: Draft) -> None:
        data = self._read()
        data[draft.article_id] = draft.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".threads_editorial.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)


class EditorialRejected(ValueError):
    """The story's draft failed a gate: it must not be published."""


class Editorial:
    """What the Threads destination calls: the post text for one locale."""

    def __init__(self, store: DraftStore, *, provider_factory: Callable[[], JsonProvider],
                 items: Callable[[str], Any], model: str = "") -> None:
        self.store, self._factory, self._items, self._model = store, provider_factory, items, model
        self._provider: JsonProvider | None = None

    def post(self, payload: Mapping[str, Any], locale: str, url: str, *,
             remaining: Callable[[], float] | None = None) -> ThreadsPost:
        item = self._items(str(payload.get("id", "")))
        if item is None:
            raise EditorialRejected("the source article is not in the store")
        ev = evidence_from(payload, item)
        resp, review = self.draft(ev, remaining=remaining)
        if not review.publishable:
            problems = review.flat()
            raise EditorialRejected("editorial gate: " + ("; ".join(problems[:4]) or str(review.scores)))
        text = compose(resp, locale, outlet=ev.outlet, url=url)
        if threads_length(text) > TEXT_LIMIT:
            raise EditorialRejected("over the Threads limit")
        return ThreadsPost(text=text, topic_tag=TOPIC_TAG.get(locale, TOPIC_TAG["en"]), dropped=[])


    def draft(self, ev: Evidence, *, remaining: Callable[[], float] | None = None) -> tuple[DraftResponse, Review]:
        """The story's draft: the stored one while the evidence is unchanged and it
        still passes the current gates (so a retry sends the same text), else a new one.
        Raises EditorialDeferred when the draft is unfinished and this run has no time."""
        cached = self.store.get(ev.article_id, ev.digest())
        resume: Mapping[str, Any] | None = None
        if cached is not None:
            resp = DraftResponse.model_validate(cached["response"])
            review = check(resp, ev)
            if review.publishable:
                return resp, review
            if cached.get("checks") == CHECKS_VERSION:
                if cached.get("complete", True):
                    return resp, review          # same checks: the verdict stands, no rewrite
                resume = cached                  # stopped for time last run: continue it
        if self._provider is None:
            self._provider = self._factory()                   # may raise: the caller retries later
        new = write(ev, self._provider, model=self._model, remaining=remaining, resume=resume)
        self.store.put(new)
        if not new.complete:
            raise EditorialDeferred("the draft needs another attempt; no time left in this run")
        return new.response, new.review


def default_provider() -> tuple[JsonProvider, str]:
    """The provider the site's editions use (CYBERALERTX_AI_PROVIDER)."""
    from ..ai.config import AI_SETTINGS as cfg
    if cfg.provider == "claude_cli":
        from ..ai.providers import ClaudeCliProvider
        p = ClaudeCliProvider(binary=cfg.claude_cli_bin, model=cfg.claude_cli_model,
                              timeout_seconds=cfg.claude_cli_timeout, oauth_env_file=cfg.claude_cli_env_file or None)
        return p, str(cfg.claude_cli_model or "claude-cli")
    if cfg.provider == "anthropic" and cfg.api_key:
        from ..ai.providers import AnthropicProvider
        a = AnthropicProvider(api_key=cfg.api_key, model=cfg.anthropic_model, max_output_tokens=2000,
                              max_retries=cfg.max_retries)
        return a, str(cfg.anthropic_model)
    raise RuntimeError(f"no LLM provider for the Threads editorial writer (provider={cfg.provider!r})")


__all__ = ["ATTRIBUTION", "DraftResponse", "DraftStore", "Editorial", "EditorialDeferred", "EditorialRejected", "Evidence", "GATES",
           "Review", "SAMPLE_URL", "SYSTEM", "check", "compose", "default_provider", "evidence_from", "write"]
