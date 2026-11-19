"""Event identity for Threads: one initial post per cybersecurity event and account.

Different articles about one event can sit in different intel stories (other
outlet, other headline, clustered apart), so the story key alone lets Threads
post the same event twice. This module gives each Threads job a small, verified
event signature and decides two things:

* `same_event(earlier, later)`: is `later` about an event `earlier` already covers?
* `update_reason(earlier, later)`: if so, does `later` carry a substantive
  development that justifies a new post anyway?

Signatures are built only from the source headline, our edition headline and the
article's own evidence assessment; nothing is inferred. Website stories, story
keys and other destinations are untouched.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

#: How far apart two articles about one event can be. Longer than the 48 h
#: publication window, so a late article about an already-posted event is caught.
EVENT_WINDOW = timedelta(hours=72)

_CVE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)

#: Kinds of event, in families; a substantive update is a move up a ladder.
_KINDS: list[tuple[str, re.Pattern[str]]] = [
    ("enforcement", re.compile(r"\b(?:arrest\w*|charged|indicted|sentenced|extradit\w*|convicted|seiz\w*|"
                               r"takedown|take down|takes down|took down|dismantl\w*|disrupt\w* (?:botnet|"
                               r"infrastructure|operation)|police|europol|operation endgame)|"
                               r"затрима\w*|арешт\w*|вирок|засуд\w*|кіберполіц\w*|поліці\w*", re.I)),
    ("roundup", re.compile(r"weekly recap|week in review|threatsday|roundup|digest|\+\s*\d+ more stories", re.I)),
    ("breach", re.compile(r"\bbreach\w*|data (?:leak|theft|exposure)|exposes? \S+ (?:users|customers|records)|"
                          r"stole|stolen|leak site|ransomware (?:attack|gang|group|claims)|cyberattack|"
                          r"hack(?:ed|ers? (?:breach|hit))|offline after|витік|злам\w*|кібератак\w*", re.I)),
    ("vulnerability", re.compile(r"\bflaws?\b|vulnerabilit\w*|\bbugs?\b|zero-day|0-day|\bRCE\b|\bCVE-|patch\w*|"
                                 r"hotfix\w*|security update|exploit\w*|вразлив\w*|вад\w*|уразлив\w*", re.I)),
    ("campaign", re.compile(r"malware|campaign|phishing|botnet|backdoor|infostealer|stealer|trojan|\bRAT\b|worm|"
                            r"loader|spyware|scam|lures?|шкідлив\w*|фішинг\w*", re.I)),
]
_PATCHED = re.compile(r"\bpatch(?:es|ed)\b|\bfix(?:es|ed)\b|hotfix\w*|releases? (?:a |an )?(?:security )?"
                      r"(?:update|fix|patch)|updates? (?:released|fix)|виправ\w*|оновлен\w* (?:усуває|виправляє)",
                      re.I)
_EXPLOITED = re.compile(r"\bexploited\b|under (?:active )?(?:attack|exploitation)|in the wild|actively exploit|"
                        r"exploitation|attacks? (?:target|hit|use)|hackers (?:exploit|target|use)|"
                        r"експлуат\w*", re.I)
_UNPATCHED = re.compile(r"unpatched|no (?:patch|fix)|not (?:yet )?(?:patched|fixed)|without (?:a )?(?:patch|fix)|"
                        r"fixes? (?:are |is )?coming|невиправлен\w*", re.I)
#: Words the headline entity extractor can return that do not identify an event.
_NOT_NAMES = {"exploited", "known", "catalog", "system", "systems", "year old", "flaw", "flaws", "zero day",
              "patch", "tuesday", "monday", "wednesday", "thursday", "friday", "update", "updates", "critical",
              "hackers", "attackers", "researchers", "users", "servers", "version", "versions", "remote", "root"}
_MONTHS = re.compile(r"^(?:january|february|march|april|may|june|july|august|september|october|november|december)$")
_PENDING = re.compile(r"\bcoming\b|\bwill (?:fix|patch|release)|scheduled|upcoming|до виходу|незабаром", re.I)
def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _kind(text: str) -> str:
    for name, pat in _KINDS:
        if pat.search(text):
            return name
    return "other"


def _count(v: str) -> int:
    m = re.match(r"([\d.]+)\s*([KMB]?)", v.replace(",", "").replace(" ", ""))
    if not m:
        return 0
    try:
        return int(float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)])
    except ValueError:
        return 0


def _number(facts: Mapping[str, Any]) -> int:
    """The largest victim/affected count the headline states ("265K", "6.4M", "40")."""
    best = 0
    for k in ("people", "orgs", "accounts", "records", "sites"):
        m = re.match(r"([\d.]+)\s*([KMB]?)", str(facts.get(k) or "").replace(",", "").replace(" ", ""))
        if m:
            try:
                n = float(m.group(1)) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)]
            except ValueError:
                continue
            best = max(best, int(n))
    return best


def signature(payload: Mapping[str, Any], item: Any) -> dict[str, Any]:
    """The verified event facts of one article, as stored on its Threads job."""
    from ..media.v4.brief import claimed_only, extract_entities, extract_facts
    from ..pipeline.evidence import assess

    from ..media.v4.brief import is_generic

    head = str(getattr(item, "title", "") or "")
    lead = str(getattr(item, "raw_content", "") or "")[:600]      # the article's lead: what it reports
    tr = payload.get("translations") or {}
    ours = " ".join(str((tr.get(loc) or {}).get("title") or "") for loc in ("en", "ua"))
    ev = assess(item)
    entities = {_norm(e) for e in extract_entities(head, lead[:400])[:5] if not is_generic(e)}
    entities = {e for e in entities if e and e not in _NOT_NAMES and not _MONTHS.match(e)
                and not e.startswith("cve ")}
    facts = extract_facts(head, "", "")
    kind = _kind(head) if _kind(head) != "other" else _kind(ours)
    both = f"{head} {lead}"
    return {
        "v": 1,
        "at": _iso(getattr(item, "published_at", None) or payload.get("published_at")),
        # The vulnerability identity: CVEs in the headlines or the article's lead.
        "cves": sorted({c.upper() for c in _CVE.findall(f"{head} {ours} {lead}")}),
        "entities": sorted(entities),
        "kind": kind,
                # What the article itself reports (headline or lead), never inferred.
        "exploited": ev.exploitation in ("confirmed", "attacks_observed") or bool(_EXPLOITED.search(head)),
        "patched": bool(_PATCHED.search(both)) and not _PENDING.search(head) and not _UNPATCHED.search(both),
        "confirmed": ev.compromise == "confirmed" and not claimed_only(head),
        "alleged": claimed_only(head),
        "enforcement": kind == "enforcement",
        "affected": _number(facts),
        "flaws": _count(str(facts.get("flaws") or "")),
        "another": bool(_ANOTHER.search(head)),
    }


def _iso(v: Any) -> str:
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v or "")


def _when(sig: Mapping[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(sig.get("at", "")).replace("Z", "+00:00"))
    except ValueError:
        return None


_FAMILY = {"vulnerability": "vuln", "breach": "incident", "campaign": "campaign", "enforcement": "enforcement",
           "roundup": "roundup", "other": "other"}
#: A later headline that announces another instance is a different event.
_ANOTHER = re.compile(r"\b(?:second|third|another|fresh|other)\b|\bnew (?:zero-day|flaw|wave|attack|campaign)", re.I)


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def same_event(earlier: Mapping[str, Any], later: Mapping[str, Any]) -> bool:
    """`later` reports an event `earlier` already covers (nothing new to identify it).

    * Both name CVEs: they share one and `later` names none `earlier` did not
      (a catalog adding CVEs is new; a story about one CVE of a catalog is not).
    * Otherwise the same kind of event, and either mostly the same named entities
      (Jaccard >= 0.5), or the same vendor's bulk release (both state >= 30 flaws,
      counts within 25 %: one Patch Tuesday told by several outlets).
    Never across kinds (a vulnerability vs a breach of the same vendor), and never
    when the later headline announces another instance ("second zero-day")."""
    if not earlier or not later or earlier.get("v") != 1 or later.get("v") != 1:
        return False
    a, b = _when(earlier), _when(later)
    if a is None or b is None or abs(b - a) > EVENT_WINDOW:
        return False
    ka, kb = str(earlier.get("kind")), str(later.get("kind"))
    if "roundup" in (ka, kb):
        return False                       # a roundup is never "the same event" as one story
    ca, cb = set(earlier.get("cves") or []), set(later.get("cves") or [])
    if ca and cb:
        return bool(ca & cb) and cb <= ca
    if _FAMILY.get(ka, "other") != _FAMILY.get(kb, "other") or later.get("another"):
        return False
    ea, eb = set(earlier.get("entities") or []), set(later.get("entities") or [])
    if not ea & eb:
        return False
    if _jaccard(ea, eb) >= 0.5:
        return True
    fa, fb = int(earlier.get("flaws") or 0), int(later.get("flaws") or 0)
    return fa >= 30 and fb >= 30 and 0.75 <= fb / fa <= 1.34


def update_reason(earlier: Mapping[str, Any], later: Mapping[str, Any]) -> str:
    """A substantive development in `later` that `earlier` did not report, or ''.
    A new headline or a new publisher alone is never one."""
    if later.get("kind") == "breach" and later.get("confirmed") and not earlier.get("confirmed"):
        return "breach confirmed after an earlier report or claim"
    if later.get("kind") == "vulnerability" and later.get("exploited") and not earlier.get("exploited"):
        return "exploitation confirmed after the disclosure"
    if later.get("patched") and not earlier.get("patched") and not earlier.get("exploited"):
        return "patch now available"
    if later.get("enforcement") and not earlier.get("enforcement"):
        return "law-enforcement action"
    ea, la = int(earlier.get("affected") or 0), int(later.get("affected") or 0)
    if ea and la >= ea * 1.5 and la - ea >= 10:
        return f"materially more affected ({ea} -> {la})"
    return ""


def covering(sig: Mapping[str, Any], others: Sequence[tuple[str, Mapping[str, Any]]]) -> tuple[str, str]:
    """(job id that already covers this event, '') when `sig` must not be posted;
    ('', update reason) when it is a substantive update; ('', '') when it is new.
    `others` are (job id, signature) of this account's posted or pending jobs."""
    matches = [(jid, o) for jid, o in others if same_event(o, sig)]
    if not matches:
        return "", ""
    reasons = [update_reason(o, sig) for _, o in matches]
    if all(reasons):
        return "", reasons[0]
    return next(jid for (jid, _), r in zip(matches, reasons) if not r), ""


# ------------------------------------------------------------------ not editorial news

#: Sponsored articles, webinars, vendor promotions and generic roundups are not
#: news posts for Threads, whatever their severity.
_PROMO = re.compile(
    r"\bwebinar\b|\bsponsored\b|\bpartner content\b|\[sponsored\]|this webinar|register now|"
    r"weekly recap|week in review|threatsday|\broundup\b|\+\s*\d+ more stories|"
    r"\bchecklist\b|questions to ask|tips for|\bhow to choose\b|why (?:stronger|better) \w+ matters|"
    r"could be your biggest (?:security )?risk", re.I)


def not_news(payload: Mapping[str, Any], item: Any) -> str:
    """Why this article is not editorial news for Threads ('' when it is). The
    sponsored flag is the pipeline's own evidence assessment (source byline/text)."""
    from ..pipeline.evidence import assess

    head = str(getattr(item, "title", "") or "")
    ev = assess(item)
    if ev.sponsored:
        return f"sponsored content{f' ({ev.sponsor})' if ev.sponsor else ''}"
    m = _PROMO.search(head)
    return f"not editorial news ('{m.group(0)}')" if m else ""


__all__ = ["EVENT_WINDOW", "covering", "not_news", "same_event", "signature", "update_reason"]
