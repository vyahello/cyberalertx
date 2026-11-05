"""Editorial scorecard — a deterministic, INTERNAL quality indicator.

READ THIS FIRST. The number this module produces is not an objective measure
of quality, accuracy or truth. It is a weighted count of things a reviewer at
this newsroom has learned to look for: banned phrases, Russian-pattern and
bureaucratic Ukrainian, identifiers the source does not contain, an analysis
that restates the summary, a missing attribution clause. A post can score 95
and still be wrong (the checks cannot read meaning); a post can score 50 and
be fine (the source was a two-line teaser). Its only job is to decide which
posts a human should look at first, and it should be tuned against what the
editor actually rejects, not trusted on its own.

Dimensions and weights (sum 100):

    language     25  natural language & readability
    accuracy     25  technical accuracy — from `fact_check`
    structure    20  structure & clarity (field contracts)
    originality  15  original editorial value
    attribution  10  source attribution
    seo           5  title and description length

Each dimension starts at 1.0 and loses a fixed amount per issue (aggregated
per issue code and capped, so one noisy check cannot zero a dimension on its
own); points = weight x what is left. When the source article is no longer
in the store, `accuracy` cannot be assessed: it is left out and the total is
rescaled from the other 75 points (`source_checked` is False).

`needs_review` is True when the score is below the threshold, OR the fact
check found a hard issue (an identifier not in the source), OR the EN and UA
editions of the story disagree on a CVE, CVSS score or date — regardless of
score.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from .editorial import (
    GENERIC_ADVICE_PATTERNS_EN,
    GENERIC_ADVICE_PATTERNS_UA,
    contains_fluff,
    paragraph_overlap_ratio,
)
from .fact_check import FactCheckReport, Finding, check_item, post_fields
from .uk_glossary import find_calques, find_term_deviations, has_russism
from .validation import (
    _AI_CLICHES_EN,
    _AI_CLICHES_UK,
    _UA_UNTRANSLATED_TERMS,
    near_copy_ratio,
)

if TYPE_CHECKING:
    from .fact_sheet import FactSheet

SCORECARD_VERSION = 1

WEIGHTS: dict[str, int] = {
    "language": 25,
    "accuracy": 25,
    "structure": 20,
    "originality": 15,
    "attribution": 10,
    "seo": 5,
}
DIMENSION_LABELS: dict[str, str] = {
    "language": "Natural language & readability",
    "accuracy": "Technical accuracy",
    "structure": "Structure & clarity",
    "originality": "Original editorial value",
    "attribution": "Source attribution",
    "seo": "SEO",
}

#: Below this the post is queued. Override with CYBERALERTX_REVIEW_THRESHOLD.
#:
#: Why so high: with these weights a post whose other five dimensions are
#: clean can lose at most 25 points to the worst accuracy problem, so scores
#: cluster in the 90s and a "natural" 55 would never fire. 85 means "one
#: dimension lost well over half its points, or several lost some". Measured
#: with `review score-archive` on the 2026-11 snapshot (4,453 posts, 285 of
#: them with the source still stored): 85 flags 3.3% of fact-checked EN posts
#: and 1.2% of UA, and hold mode keeps 117/121 EN and 162/164 UA feed-pool
#: posts visible. Hard fact-check issues and EN/UA conflicts flag regardless.
DEFAULT_REVIEW_THRESHOLD = 85
THRESHOLD_ENV = "CYBERALERTX_REVIEW_THRESHOLD"

# Deduction per occurrence, and the cap for one issue code, by severity.
_UNIT = {"info": 0.0, "minor": 0.15, "major": 0.4, "hard": 1.0}
_CAP = {"info": 0.0, "minor": 0.45, "major": 0.8, "hard": 1.0}
# Codes whose single occurrence is weaker evidence than a generic "minor".
_LIGHT_CODES = {
    "unsupported_entity": (0.05, 0.2),
    "unsupported_private_ip": (0.05, 0.1),
    "cross_locale_omission": (0.05, 0.15),
    "long_sentence": (0.05, 0.15),
}


def review_threshold() -> int:
    raw = os.getenv(THRESHOLD_ENV, "").strip()
    try:
        return max(0, min(100, int(raw))) if raw else DEFAULT_REVIEW_THRESHOLD
    except ValueError:
        return DEFAULT_REVIEW_THRESHOLD


@dataclass(frozen=True)
class Issue:
    code: str
    dimension: str
    severity: str        # "info" | "minor" | "major" | "hard"
    message: str
    field: str = ""

    def to_dict(self) -> dict[str, str]:
        out = {"code": self.code, "dimension": self.dimension,
               "severity": self.severity, "message": self.message}
        if self.field:
            out["field"] = self.field
        return out


@dataclass
class Scorecard:
    score: int
    dimensions: dict[str, float]
    issues: list[Issue]
    needs_review: bool
    review_reasons: list[str]
    threshold: int
    source_checked: bool
    version: int = SCORECARD_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "score": self.score,
            "threshold": self.threshold,
            "needs_review": self.needs_review,
            "review_reasons": list(self.review_reasons),
            "source_checked": self.source_checked,
            "dimensions": {k: round(v, 1) for k, v in self.dimensions.items()},
            "issues": [i.to_dict() for i in self.issues],
        }


# ===========================================================================
# Helpers
# ===========================================================================

def _get(post: Any, name: str) -> Any:
    return post.get(name) if isinstance(post, dict) else getattr(post, name, None)


def _str(post: Any, name: str) -> str:
    value = _get(post, name)
    return value.strip() if isinstance(value, str) else ""


def _list(post: Any, name: str) -> list[str]:
    value = _get(post, name)
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()]


def _words(text: str) -> int:
    return len(re.findall(r"[^\W_]+(?:[-'’ʼ][^\W_]+)*", text or ""))


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


_PROSE_FIELDS = ("plain_summary", "short_summary", "why_it_matters", "detail_body",
                 "severity_reason")
_ACTION_FIELDS = ("what_to_do", "what_not_to_do", "if_already_affected")


# ===========================================================================
# Dimensions
# ===========================================================================

_INLINE_GLOSS_EN = re.compile(
    r"(?:,|\s—)\s+(?:an?\s+|the\s+)?(?:[\w-]+\s+){0,3}?"
    r"(?:software|program|app|application|tool|service|platform|system|device|library|"
    r"package|plugin|extension|browser|router|firewall|server|framework|product|file)s?\s+"
    r"(?:that|which|used|for)\b",
    re.I,
)
_LEVEL_OPENING = re.compile(
    r"^(?:critical|high|medium|low|критичн\w*|висок\w*|середн\w*|низьк\w*)\b", re.I,
)


def _language_issues(post: Any, language: str) -> list[Issue]:
    issues: list[Issue] = []
    texts = post_fields(post)
    blob = " ".join(t for _, t in texts)
    low = blob.lower()

    for phrase in (_AI_CLICHES_UK if language == "ua" else _AI_CLICHES_EN):
        if phrase in low:
            issues.append(Issue("ai_cliche", "language", "major", f"banned phrase “{phrase}”"))
    other = _AI_CLICHES_EN if language == "ua" else _AI_CLICHES_UK
    for phrase in other:
        if phrase in low:
            issues.append(Issue("ai_cliche", "language", "major", f"banned phrase “{phrase}”"))

    for name in _PROSE_FIELDS:
        text = _str(post, name)
        if not text:
            continue
        stuck = contains_fluff(text, language)
        if stuck:
            issues.append(Issue("fluff_phrase", "language", "minor", f"filler “{stuck}”", name))
        for sentence in _sentences(text):
            if sentence.count("—") > 1:
                issues.append(Issue("em_dash_overuse", "language", "minor",
                                    "more than one em dash in a sentence", name))
                break
        for sentence in _sentences(text):
            if _words(sentence) > 35:
                issues.append(Issue("long_sentence", "language", "minor",
                                    f"{_words(sentence)}-word sentence", name))
        if "!" in text:
            issues.append(Issue("exclamation", "language", "minor", "exclamation mark", name))
        if re.search(r"\?\s|\?$", text):
            issues.append(Issue("rhetorical_question", "language", "minor",
                                "question in a prose field", name))

    patterns = GENERIC_ADVICE_PATTERNS_UA if language == "ua" else GENERIC_ADVICE_PATTERNS_EN
    for name in _ACTION_FIELDS:
        for bullet in _list(post, name):
            if any(p.search(bullet) for p in patterns):
                issues.append(Issue("generic_advice", "language", "minor",
                                    f"generic advice “{bullet[:60]}”", name))

    if language == "ua":
        stem = has_russism(blob)
        if stem:
            issues.append(Issue("russism", "language", "major", f"russism “{stem}”"))
        for _cid, found, preferred in find_calques(blob):
            issues.append(Issue("calque", "language", "minor",
                                f"«{found}» → {preferred}"))
        for _cid, found, preferred in find_term_deviations(blob):
            issues.append(Issue("terminology", "language", "minor",
                                f"«{found}» → {preferred}"))
        plain = _str(post, "plain_summary").lower()
        for term in _UA_UNTRANSLATED_TERMS:
            if term in plain:
                issues.append(Issue("untranslated_term", "language", "minor",
                                    f"untranslated “{term}” in the plain lead", "plain_summary"))
    else:
        plain = _str(post, "plain_summary")
        if plain and _INLINE_GLOSS_EN.search(plain):
            issues.append(Issue("inline_gloss_formula", "language", "minor",
                                "plain lead uses the “X, software that does Y,” formula",
                                "plain_summary"))
    return issues


def _accuracy_issues(report: FactCheckReport | None,
                     cross: Sequence[Finding]) -> list[Issue]:
    issues: list[Issue] = []
    if report is not None:
        for f in report.hard:
            issues.append(Issue(f"unsupported_{f.kind}", "accuracy", "hard",
                                f"{f.value}: {f.message}", f.field))
        for f in report.soft:
            issues.append(Issue(f"unsupported_{f.kind}", "accuracy", "minor",
                                f"{f.value}: {f.message}", f.field))
    for f in cross:
        if f.severity == "major":
            issues.append(Issue("cross_locale_conflict", "accuracy", "major",
                                f"{f.message}: {f.value}", "cross_locale"))
        else:
            issues.append(Issue("cross_locale_omission", "accuracy", "minor",
                                f"{f.kind} {f.value}: {f.message}", "cross_locale"))
    return issues


# --- evidence: the brief may not say more than the source does ----------------------
# Claims are matched in the brief; support is judged from the SOURCE alone
# (pipeline/evidence.py), so a confident sentence in the brief never counts as
# its own evidence. Hard issues: they put the post in the editor's queue
# whatever the score (no AI retry, so no added cost).
_CLAIM_EXPLOITED = re.compile(
    r"actively exploited|exploited in the wild|in the wild|under active (?:attack|exploitation)|"
    r"(?:is|are) being exploited|attackers are exploiting|"
    r"активно експлуат|експлуатують в атаках|уже використовують в атаках|вже використовують в атаках",
    re.I)
_CLAIM_STOLEN = re.compile(
    r"\b(?:data|records|information|details|passwords?|credentials?|secrets?|files|emails|"
    r"vault(?: data| contents)?) (?:were|was|have been|has been) (?:stolen|exfiltrated|leaked|exposed|accessed)\b|"
    r"\b(?:attackers|hackers|the (?:gang|group|attacker|hacker)) stole\b|"
    r"\b(?:all|every) (?:saved |stored )?(?:passwords?|secrets?|credentials?|vault)\b[^.]{0,40}"
    r"\b(?:stolen|exposed|compromised|leaked)\b|"
    r"\b(?:вкрали|викрали|злили|витекли|викрадено|розкрито всі)\b",
    re.I)
_CLAIM_CAMPAIGN_ACTIVE = re.compile(
    r"\b(?:is|remains|still) (?:ongoing|active)\b|\bcontinues to (?:target|spread|send)\b|"
    r"\bкампанія (?:триває|досі активна)\b",
    re.I)
# Self-referential authorship only; news ABOUT AI tools is fine.
_AI_AUTHORSHIP = re.compile(
    r"\b(?:this|the) (?:brief|article|summary|post) (?:was |is )?(?:written|generated|produced|prepared) by\b|"
    r"\b(?:written|generated) by (?:an? |the )?(?:AI|artificial intelligence|language model|CyberAlertX)\b|"
    r"\bCyberAlertX AI\b|\bAI[- ]generated (?:brief|summary|article)\b|"
    r"\b(?:матеріал|огляд|довідк\w*) (?:підготувал\w*|згенерувал\w*|написал\w*|створен\w*)[^.]{0,40}\bШІ\b|"
    r"\bредакційн\w* систем\w*[^.]{0,30}\bШІ\b|\bзгенерован\w* (?:ШІ|штучним інтелектом)\b",
    re.I)
_EVIDENCE_CODES = frozenset({"unsupported_exploitation", "unsupported_compromise",
                            "campaign_status_conflict", "ai_authorship"})
_SHOUT_FIELDS = ("title", "short_summary", "plain_summary", "why_it_matters", "severity_reason",
                 "detail_body")


def _claim_text(post: Any) -> str:
    parts = [_str(post, f) for f in _SHOUT_FIELDS]
    parts += [x for f in ("quick_facts", "affected_users") for x in _list(post, f)]
    return "\n".join(p for p in parts if p)


# A claim under a condition or a question is the hedged wording we ask for,
# not an assertion: "if the vault was accessed", "чи не викрали", "plan as if".
_CONDITIONAL = re.compile(
    r"(?:\bif\b|\bwhether\b|\bas if\b|\bin case\b|\bcould\b|\bmay\b|\bmight\b|\bunless\b|"
    # An attributed claim is reported as a claim: "the gang says it stole".
    r"\bclaim(?:s|ed|ing)?\b|\balleg\w*|\breportedly\b|\bsays? (?:it|they)\b|"
    r"\bякщо\b|\bчи\b|\bможливо\b|\bнібито\b|\bначебто\b|\bначе\b|\bзаяв\w*|\bстверджу\w*)[^.;:]{0,60}$",
    re.I)


# A denial is not a claim either: "no observed abuse in the wild", "exploitation
# not yet confirmed in the wild", "Даних не викрадено". Negation counts in the
# same clause before the claim, or right after it up to the next comma.
_CLAIM_TAIL_END = re.compile(r"[,.;:!?\n]")


def _asserts(pattern: re.Pattern[str], text: str) -> bool:
    """True when at least one match is stated outright (not hedged, not denied)."""
    from ..pipeline.evidence import _CLAUSE_BREAK, _NEGATION
    for m in pattern.finditer(text):
        before = text[max(0, m.start() - 80):m.start()]
        if _CONDITIONAL.search(before):
            continue
        cuts = list(_CLAUSE_BREAK.finditer(before))
        lead = before[cuts[-1].end():] if cuts else before
        tail = text[m.end():m.end() + 60]
        stop = _CLAIM_TAIL_END.search(tail)
        tail = tail[:stop.start()] if stop else tail
        if _NEGATION.search(lead + m.group(0) + tail):
            continue
        return True
    return False


def _norm_action(text: str) -> str:
    return re.sub(r"[^\w]+", " ", text.lower()).strip()


def _evidence_issues(post: Any, *, item: Any) -> list[Issue]:
    issues: list[Issue] = []
    text = _claim_text(post)
    if _AI_AUTHORSHIP.search(text + "\n" + "\n".join(
            x for f in _ACTION_FIELDS for x in _list(post, f))):
        issues.append(Issue("ai_authorship", "accuracy", "hard",
                            "public text mentions AI authorship"))
    actions = [_norm_action(a) for f in _ACTION_FIELDS + ("am_i_affected",) for a in _list(post, f)]
    if len(actions) != len(set(actions)):
        issues.append(Issue("duplicate_recommendation", "structure", "minor",
                            "the same recommendation appears twice"))
    if item is None:
        return issues
    from ..pipeline.evidence import assess
    ev = assess(item)
    if _asserts(_CLAIM_EXPLOITED, text) and ev.exploitation != "confirmed":
        issues.append(Issue("unsupported_exploitation", "accuracy", "hard",
                            f"brief says exploitation is happening; source: {ev.exploitation}"))
    if _asserts(_CLAIM_STOLEN, text) and ev.compromise != "confirmed":
        issues.append(Issue("unsupported_compromise", "accuracy", "hard",
                            "brief says data was stolen/exposed; the source does not confirm it"))
    if _asserts(_CLAIM_CAMPAIGN_ACTIVE, text) and ev.campaign in ("declined", "disrupted"):
        issues.append(Issue("campaign_status_conflict", "accuracy", "hard",
                            f"brief says the campaign is active; source: {ev.campaign}"))
    return issues


def _structure_issues(post: Any) -> list[Issue]:
    issues: list[Issue] = []

    def add(code: str, sev: str, msg: str, fld: str) -> None:
        issues.append(Issue(code, "structure", sev, msg, fld))

    title_words = _words(_str(post, "title"))
    if not 5 <= title_words <= 16:
        add("title_length", "minor", f"title has {title_words} words (6-14 asked)", "title")
    summary = _str(post, "short_summary")
    if not 90 <= len(summary) <= 260:
        add("summary_length", "minor", f"feed line is {len(summary)} chars (120-220 asked)",
            "short_summary")
    plain = _str(post, "plain_summary")
    if not plain:
        add("no_plain_summary", "minor", "no plain-language lead", "plain_summary")
    elif not 10 <= _words(plain) <= 30:
        add("plain_summary_length", "minor", f"plain lead has {_words(plain)} words (14-24 asked)",
            "plain_summary")
    why = _str(post, "why_it_matters")
    if _words(why) > 45:
        add("why_length", "minor", f"why-it-matters has {_words(why)} words (≤40)",
            "why_it_matters")
    actions = _list(post, "what_to_do")
    if not actions:
        add("no_actions", "major", "no action items", "what_to_do")
    if len(actions) > 3:
        add("too_many_actions", "minor", f"{len(actions)} actions (≤3)", "what_to_do")
    if any(_words(a) > 22 for a in actions):
        add("long_action", "minor", "an action bullet runs over 22 words", "what_to_do")
    facts = _list(post, "quick_facts")
    if len(facts) < 2:
        add("few_quick_facts", "minor", f"{len(facts)} quick facts (2-5 asked)", "quick_facts")
    if any(_words(f) > 15 for f in facts):
        add("long_quick_fact", "minor", "a quick fact runs over 15 words", "quick_facts")
    if not _list(post, "affected_users"):
        add("no_affected_users", "minor", "no affected-user labels", "affected_users")
    detail = _str(post, "detail_body")
    if detail:
        n = _words(detail)
        if not 50 <= n <= 200:
            add("analysis_length", "minor", f"analysis is {n} words (80-160 asked)",
                "detail_body")
        if len([p for p in re.split(r"\n{2,}", detail) if p.strip()]) > 4:
            add("analysis_paragraphs", "minor", "analysis has more than 4 paragraphs",
                "detail_body")
    if any(_words(c) > 20 for c in _list(post, "am_i_affected")):
        add("long_self_check", "minor", "a self-check runs over 20 words", "am_i_affected")
    reason = _str(post, "severity_reason")
    if reason and _LEVEL_OPENING.match(reason):
        add("severity_restates_level", "info", "severity reason opens with the level word",
            "severity_reason")
    return issues


def _originality_issues(post: Any, *, language: str, source_title: str,
                        source_body: str, source_known: bool) -> list[Issue]:
    issues: list[Issue] = []
    detail = _str(post, "detail_body")
    if not detail:
        thin = len(source_body or "") < 600
        issues.append(Issue("no_analysis", "originality", "info" if thin else "minor",
                            "no analysis paragraph" + (" (thin source)" if thin else ""),
                            "detail_body"))
    else:
        refs = [_str(post, "title"), _str(post, "short_summary"), _str(post, "plain_summary")]
        for para in [p for p in re.split(r"\n{2,}", detail) if p.strip()]:
            if any(r and paragraph_overlap_ratio(para, r, language=language) >= 0.5 for r in refs):
                issues.append(Issue("analysis_restates_summary", "originality", "major",
                                    "an analysis paragraph restates the title/summary",
                                    "detail_body"))
                break
    if source_known and source_body:
        for name in ("plain_summary", "short_summary", "why_it_matters", "detail_body"):
            text = _str(post, name)
            if not text:
                continue
            ratio = near_copy_ratio(text, source_body)
            if ratio >= 0.25:
                issues.append(Issue("near_copy", "originality", "major",
                                    f"{ratio:.0%} 5-gram overlap with the source", name))
            elif ratio >= 0.12:
                issues.append(Issue("near_copy", "originality", "minor",
                                    f"{ratio:.0%} 5-gram overlap with the source", name))
    title = _str(post, "title")
    if source_known and title and source_title:
        if paragraph_overlap_ratio(title, source_title, language=language) >= 0.7:
            issues.append(Issue("title_mirrors_source", "originality", "minor",
                                "headline is close to the source headline", "title"))
    return issues


_ATTR_VERBS_EN = re.compile(
    r"\b(?:reports?|reported|warns?|warned|says?|said|according\s+to|disclos(?:es|ed)|"
    r"notes?|noted|confirm(?:s|ed)|reveal(?:s|ed)|publish(?:es|ed)|announc(?:es|ed)|"
    r"found|discovered|observed|detail(?:s|ed)|flag(?:s|ged)|added|tracks?|attribut\w*|"
    r"describ(?:es|ed)|document(?:s|ed)|spott(?:ed)|uncover(?:s|ed)|analy[sz](?:es|ed)|"
    r"via|per|cit(?:es|ing))\b",
    re.I,
)
_ATTR_VERBS_UA = re.compile(
    r"повідомля\w*|повідоми\w*|попереджа\w*|попереди\w*|за\s+даними|пише|пишуть|зазнача\w*|"
    r"заяви\w*|заявля\w*|підтверди\w*|розповіл\w*|виявил\w*|опублікува\w*|оприлюдни\w*|"
    r"додал\w*|за\s+словами|стверджу\w*|звітує|звітують|описал\w*|описує|відстежу\w*|"
    r"розкри\w*|розібра\w*|зафіксува\w*|фіксу\w*|посилаючись|з\s+посиланням|проаналізува\w*|"
    r"знайшл\w*|помітил\w*",
    re.I,
)
# "The Hacker News: …", "BleepingComputer — …": the outlet as the lead, colon style.
_COLON_LEAD = re.compile(r"^\s*[A-Z0-9][\w.&'’ -]{1,40}?\s*[:—–]\s")
# "Kaspersky researchers", "дослідники Kaspersky", "researchers at ESET".
_NAMED_RESEARCHERS = re.compile(
    r"\b(?:[A-Z][\w-]+\s+researchers|researchers\s+(?:at|from)\s+[A-Z]|"
    r"(?:дослідники|фахівці|експерти|аналітики)\s+(?:з\s+|компанії\s+)?[A-Z])",
)


def _known_outlets() -> list[str]:
    """Outlet names from the configured sources — the fallback when a post's
    own source item has aged out of the store."""
    try:
        from ..config import SETTINGS
    except Exception:  # pragma: no cover
        return []
    names: list[str] = []
    for src in SETTINGS.sources:
        names.extend(source_name_candidates(src.name))
    return names
_WEASEL = re.compile(
    r"\b(?:experts\s+(?:say|believe|warn)|reports\s+suggest|observers\s+note|"
    r"it\s+is\s+widely\s+believed|studies\s+show)\b|"
    r"експерти\s+(?:кажуть|вважають|попереджають)|повідомлення\s+свідчать|"
    r"спостерігачі\s+зазначають|прийнято\s+вважати|дослідження\s+показують",
    re.I,
)
_HEDGE = re.compile(
    r"\b(?:claims?|claimed|says?|said|according\s+to|alleged\w*|reportedly|assert\w*)\b|"
    r"заявля\w*|заяви\w*|стверджу\w*|за\s+словами|нібито|за\s+даними|каже|кажуть",
    re.I,
)


def source_name_candidates(source: str) -> list[str]:
    """Ways a short_summary may name the outlet: "Securelist (Kaspersky)" →
    Securelist, Kaspersky; "CISA Alerts" → CISA; "dou.ua" → dou."""
    source = (source or "").strip()
    if not source:
        return []
    out = {source}
    inner = re.findall(r"\(([^)]+)\)", source)
    out.update(i.strip() for i in inner)
    base = re.sub(r"\s*\([^)]*\)", "", source).strip()
    out.add(base)
    out.add(re.sub(r"^the\s+", "", base, flags=re.I))
    out.add(re.sub(r"\s+(?:alerts?|blog|news)$", "", base, flags=re.I))
    if "." in base and " " not in base:
        out.add(base.split(".")[0])
    first = base.split()[0] if base.split() else ""
    if len(first) >= 4 and first.lower() not in ("the", "news"):
        out.add(first)
    return sorted({c for c in out if len(c) >= 3}, key=len, reverse=True)


def _attribution_issues(post: Any, *, language: str, item: Any,
                        sheet: "FactSheet | None") -> list[Issue]:
    issues: list[Issue] = []
    summary = _str(post, "short_summary")
    verbs = _ATTR_VERBS_UA if language == "ua" else _ATTR_VERBS_EN
    has_verb = bool(verbs.search(summary)) or bool(_COLON_LEAD.match(summary)) \
        or bool(_NAMED_RESEARCHERS.search(summary))
    names = (source_name_candidates(str(getattr(item, "source", "") or "")) if item
             else _known_outlets())
    has_name = any(n.lower() in summary.lower() for n in names)
    if not has_verb and not has_name:
        issues.append(Issue("no_attribution", "attribution", "major",
                            "feed line names no source", "short_summary"))
    elif item is not None and not has_name:
        issues.append(Issue("attribution_unnamed", "attribution", "minor",
                            "feed line attributes, but not to the outlet", "short_summary"))
    if item is None:
        issues.append(Issue("source_not_in_store", "attribution", "info",
                            "source article is no longer stored; link not verifiable"))
    elif not str(getattr(item, "url", "") or "").startswith(("http://", "https://")):
        issues.append(Issue("no_source_url", "attribution", "major", "no source link"))
    blob = " ".join(t for _, t in post_fields(post))
    if _WEASEL.search(blob):
        issues.append(Issue("weasel_words", "attribution", "minor", "unnamed “experts say” claim"))
    if sheet is not None and any(c.status != "confirmed" for c in sheet.claims):
        if not _HEDGE.search(blob):
            issues.append(Issue("claims_unattributed", "attribution", "minor",
                                "fact sheet has unconfirmed claims; the brief attributes none"))
    return issues


def _seo_issues(post: Any, *, language: str) -> list[Issue]:
    issues: list[Issue] = []
    title = _str(post, "title")
    lo, hi = (30, 90) if language == "ua" else (30, 75)
    if not lo <= len(title) <= hi:
        sev = "minor" if 20 <= len(title) <= 110 else "major"
        issues.append(Issue("seo_title_length", "seo", sev,
                            f"title is {len(title)} chars ({lo}-{hi})", "title"))
    description = _str(post, "plain_summary") or _str(post, "short_summary")
    if not 70 <= len(description) <= 170:
        sev = "minor" if 40 <= len(description) <= 230 else "major"
        issues.append(Issue("seo_description_length", "seo", sev,
                            f"meta description is {len(description)} chars (70-170)",
                            "plain_summary"))
    return issues


# ===========================================================================
# Scoring
# ===========================================================================

def _dimension_fraction(issues: Iterable[Issue]) -> float:
    per_code: dict[str, tuple[int, str]] = {}
    for issue in issues:
        count, sev = per_code.get(issue.code, (0, issue.severity))
        # Keep the harshest severity seen for the code.
        if _UNIT[issue.severity] > _UNIT[sev]:
            sev = issue.severity
        per_code[issue.code] = (count + 1, sev)
    lost = 0.0
    for code, (count, sev) in per_code.items():
        if sev == "hard":
            return 0.0
        unit, cap = _LIGHT_CODES.get(code, (_UNIT[sev], _CAP[sev]))
        lost += min(count * unit, cap)
    return max(0.0, 1.0 - lost)


def score_post(
    post: Any,
    *,
    language: str,
    item: Any = None,
    sheet: "FactSheet | None" = None,
    fact_report: FactCheckReport | None = None,
    cross_locale: Sequence[Finding] = (),
    threshold: int | None = None,
) -> Scorecard:
    """Score one rendered post. Pure — never writes anything.

    `item` is the source NewsItem (None when it has aged out of the store).
    `fact_report` is computed here from `item` + `sheet` when not supplied.
    """
    threshold = review_threshold() if threshold is None else threshold
    source_known = item is not None
    if fact_report is None and source_known:
        fact_report = check_item(post, item, sheet)
    source_title = str(getattr(item, "title", "") or "") if item else ""
    source_body = str(getattr(item, "raw_content", "") or "") if item else ""

    by_dim: dict[str, list[Issue]] = {
        "language": _language_issues(post, language),
        "accuracy": _accuracy_issues(fact_report if source_known else None, cross_locale)
        + [i for i in _evidence_issues(post, item=item) if i.dimension == "accuracy"],
        "structure": _structure_issues(post)
        + [i for i in _evidence_issues(post, item=item) if i.dimension == "structure"],
        "originality": _originality_issues(
            post, language=language, source_title=source_title,
            source_body=source_body, source_known=source_known),
        "attribution": _attribution_issues(post, language=language, item=item, sheet=sheet),
        "seo": _seo_issues(post, language=language),
    }

    dimensions: dict[str, float] = {}
    for dim, weight in WEIGHTS.items():
        if dim == "accuracy" and not source_known and not cross_locale:
            continue  # cannot be assessed; rescaled below
        dimensions[dim] = weight * _dimension_fraction(by_dim[dim])
    possible = sum(WEIGHTS[d] for d in dimensions)
    score = round(100 * sum(dimensions.values()) / possible) if possible else 0

    issues = [i for dim in WEIGHTS for i in by_dim[dim]]
    reasons: list[str] = []
    if score < threshold:
        reasons.append(f"score {score} is below {threshold}")
    for i in issues:
        if i.severity == "hard":
            reasons.append(f"evidence: {i.message}" if i.code in _EVIDENCE_CODES
                           else f"not in source: {i.message}")
        elif i.code == "cross_locale_conflict":
            reasons.append(f"editions disagree: {i.message}")
    return Scorecard(
        score=score,
        dimensions=dimensions,
        issues=issues,
        needs_review=bool(reasons),
        review_reasons=reasons,
        threshold=threshold,
        source_checked=source_known,
    )


def quality_record(
    card: Scorecard,
    *,
    fact_report: FactCheckReport | None = None,
    cross_locale: Sequence[Finding] = (),
    fact_sheet_used: bool = False,
) -> dict[str, Any]:
    """The `ThreatPost.quality` payload: scorecard + fact-check findings."""
    record = card.to_dict()
    record["fact_check"] = fact_report.to_dict() if fact_report is not None else None
    record["cross_locale"] = [f.to_dict() for f in cross_locale]
    record["fact_sheet"] = fact_sheet_used
    record["scored_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return record


__all__ = [
    "DEFAULT_REVIEW_THRESHOLD",
    "DIMENSION_LABELS",
    "Issue",
    "SCORECARD_VERSION",
    "Scorecard",
    "THRESHOLD_ENV",
    "WEIGHTS",
    "quality_record",
    "review_threshold",
    "score_post",
    "source_name_candidates",
]
