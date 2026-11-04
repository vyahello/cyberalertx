"""Fact-sheet stage: one structured extraction per story, shared by both locales.

Why it exists. The EN and UA briefs of one story are rendered independently
from the same source (not translated), so nothing tied them to the same set
of facts: one UA brief moved an attack from 1 to 2 November. And because the
sources are mostly RSS teasers, the model padded the analysis with background
knowledge it was never given. The fact sheet is the shared, explicit list of
what the source actually says — products and versions, CVEs, CVSS, actors,
dates, figures, exploitation and patch status, attributed claims and open
questions — extracted ONCE per fingerprint and handed to both renders inside
the user prompt.

Budget (the owner's decision, binding): exactly +1 LLM call per story.

  * The sheet is cached per fingerprint in `data/fact_sheets.json`
    (`AISettings.fact_sheet_path`), so the second locale and every later
    re-render reuse it.
  * A failed extraction is cached too, as a failure marker, and is NOT
    retried automatically — a retry would be a second call for the same
    story. The render simply proceeds without a sheet, exactly as before this
    stage existed. Delete the entry from the file to force a new attempt.
  * The rule-based path never touches any of this.

The sheet is sanitized against the source before it is stored: a CVE id or
CVSS score the source does not contain is dropped (and listed in the cache
record's `dropped`), so the sheet can never vouch for a hallucinated
identifier in `fact_check.py`.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .fact_check import build_support, extract_tokens
from .templates import _truncate_source_body

if TYPE_CHECKING:
    from ..models import NewsItem

logger = logging.getLogger(__name__)

#: 2 added event_type, attack_techniques, impact, mitigations, iocs,
#: contradictions, evidence and the six-value claim vocabulary. Every new
#: field defaults, so version-1 records load unchanged.
FACT_SHEET_SCHEMA_VERSION = 2

ExploitationStatus = Literal["confirmed", "reported", "not_reported", "unknown"]
PatchStatus = Literal["available", "partial", "workaround_only", "not_available", "unknown"]
#: confirmed      — verified by the article or an authority it cites;
#: reported       — a party asserts it (the gang, the vendor, a researcher);
#: interpretation — the article's own editorial reading, not a reported fact;
#: unverified     — accusation or unconfirmed report nobody stands behind;
#: contradictory  — sources disagree;
#: unknown        — status cannot be told from the text.
ClaimStatus = Literal["confirmed", "reported", "interpretation", "unverified",
                      "contradictory", "unknown"]
EventType = Literal[
    "vulnerability_disclosure", "active_exploitation", "breach", "ransomware",
    "malware_campaign", "phishing_campaign", "supply_chain", "policy_or_advisory",
    "research", "other",
]

_EXPLOITATION = ("confirmed", "reported", "not_reported", "unknown")
_PATCH = ("available", "partial", "workaround_only", "not_available", "unknown")
_CLAIM = ("confirmed", "reported", "interpretation", "unverified", "contradictory", "unknown")
#: Version-1 vocabulary → version 2. "claimed" was "a party asserts it";
#: "alleged" was "accusations and unverified reports".
_CLAIM_LEGACY = {"claimed": "reported", "claim": "reported", "alleged": "unverified",
                 "disputed": "contradictory", "editorial": "interpretation",
                 "opinion": "interpretation", "analysis": "interpretation"}
_EVENT_TYPES = ("vulnerability_disclosure", "active_exploitation", "breach", "ransomware",
                "malware_campaign", "phishing_campaign", "supply_chain",
                "policy_or_advisory", "research", "other")
#: Longest verbatim excerpt an evidence entry may carry.
MAX_EXCERPT_WORDS = 25
_MITRE_RE = re.compile(r"^(?:T\d{4}(?:\.\d{3})?|TA\d{4}|S\d{4}|G\d{4})$")


def _coerce(value: object, allowed: tuple[str, ...], default: str,
            legacy: dict[str, str] | None = None) -> str:
    """Map a free-form status to the enum instead of failing the whole sheet."""
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if legacy and text in legacy:
        return legacy[text]
    return text if text in allowed else default


def _norm_space(text: str) -> str:
    return " ".join((text or "").split()).lower()


# ===========================================================================
# Schema (the LLM boundary — pydantic, like ThreatPostResponse)
# ===========================================================================

class AffectedProduct(BaseModel):
    model_config = ConfigDict(extra="ignore")
    vendor: str = ""
    product: str
    versions: list[str] = Field(default_factory=list)


class CvssScore(BaseModel):
    model_config = ConfigDict(extra="ignore")
    score: float
    cve_id: str = ""
    version: str = ""


class DatedEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: str
    event: str = ""


class KeyNumber(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: str
    unit: str = ""
    context: str = ""


class Claim(BaseModel):
    model_config = ConfigDict(extra="ignore")
    statement: str
    attribution: str = ""
    status: ClaimStatus = "reported"

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: object) -> str:
        return _coerce(value, _CLAIM, "reported", _CLAIM_LEGACY)


class AttackTechnique(BaseModel):
    """How the attack works, in the article's words; a MITRE ATT&CK id only
    when the article itself prints one."""
    model_config = ConfigDict(extra="ignore")
    description: str
    mitre_id: str = ""


class Ioc(BaseModel):
    """An indicator exactly as the article prints it."""
    model_config = ConfigDict(extra="ignore")
    type: str = ""          # ip | domain | url | hash | email | file | other
    value: str


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    statement: str
    sources: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    """One important claim or identifier, tied to where it was read."""
    model_config = ConfigDict(extra="ignore")
    claim: str
    source: str = ""
    url: str = ""
    excerpt: str = ""       # verbatim, at most MAX_EXCERPT_WORDS words
    primary: bool = False   # the vendor / agency / victim / researcher itself
    status: ClaimStatus = "reported"

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, value: object) -> str:
        return _coerce(value, _CLAIM, "reported", _CLAIM_LEGACY)

    @field_validator("excerpt", mode="before")
    @classmethod
    def _excerpt(cls, value: object) -> str:
        words = str(value or "").split()
        return " ".join(words[:MAX_EXCERPT_WORDS])


class FactSheet(BaseModel):
    """What one source article states. Nothing more."""

    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    affected_products: list[AffectedProduct] = Field(default_factory=list)
    cve_ids: list[str] = Field(default_factory=list)
    cvss_scores: list[CvssScore] = Field(default_factory=list)
    threat_actors: list[str] = Field(default_factory=list)
    malware_families: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    dates: list[DatedEvent] = Field(default_factory=list)
    key_numbers: list[KeyNumber] = Field(default_factory=list)
    exploitation_status: ExploitationStatus = "unknown"
    patch_status: PatchStatus = "unknown"
    claims: list[Claim] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    # --- schema version 2 (all optional) ---
    event_type: EventType = "other"
    attack_techniques: list[AttackTechnique] = Field(default_factory=list)
    impact: str = ""
    mitigations: list[str] = Field(default_factory=list)
    iocs: list[Ioc] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)

    @field_validator("event_type", mode="before")
    @classmethod
    def _event_type(cls, value: object) -> str:
        return _coerce(value, _EVENT_TYPES, "other")

    @field_validator("exploitation_status", mode="before")
    @classmethod
    def _exploitation(cls, value: object) -> str:
        return _coerce(value, _EXPLOITATION, "unknown")

    @field_validator("patch_status", mode="before")
    @classmethod
    def _patch(cls, value: object) -> str:
        return _coerce(value, _PATCH, "unknown")

    # -- views ---------------------------------------------------------------

    def compact_dict(self) -> dict[str, Any]:
        """Non-empty fields only — what the render prompt shows."""
        data = self.model_dump()
        return {
            k: v for k, v in data.items()
            if v not in ("", [], None)
            and not (k.endswith("_status") and v == "unknown")
            and not (k == "event_type" and v == "other")
        }

    def support_text(self) -> str:
        """Every string and number in the sheet, one per line, for matching."""
        parts: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            elif isinstance(node, (str, int, float)) and str(node).strip():
                parts.append(str(node))

        walk(self.model_dump())
        return "\n".join(parts)

    def to_prompt_block(self) -> str:
        """The delimited block `render_prompts` appends to the user prompt."""
        body = json.dumps(self.compact_dict(), ensure_ascii=False, indent=1)
        return (
            "FACT SHEET\n"
            "Extracted once from the source article above and shared by every "
            "language edition of this story. Treat it as the list of what is known:\n"
            "- every name, number, date, CVE id, CVSS score, version, IP address, "
            "domain and hash in your brief must appear here or in the source article;\n"
            "- a claim with status \"reported\", \"unverified\" or \"contradictory\" "
            "keeps its attribution in your text (\"the gang says\", \"according to "
            "Microsoft\"); \"interpretation\" is the outlet's reading, never a fact; "
            "an item under contradictions is reported as disputed;\n"
            "- iocs, CVE ids, versions and MITRE ids are copied exactly;\n"
            "- exploitation_status and patch_status are the only basis for saying "
            "attacks are happening or a fix exists;\n"
            "- items under open_questions stay unanswered.\n"
            "<<<FACT_SHEET\n"
            f"{body}\n"
            "FACT_SHEET>>>"
        )


# ===========================================================================
# Extraction
# ===========================================================================

FACT_SHEET_SYSTEM_PROMPT = """
You extract facts from ONE cybersecurity news article for a newsroom. Two
writers (one English, one Ukrainian) will use your fact sheet as their list of
what is known, so it must contain exactly what the article states and nothing
else.

RULES
- Use only the article text you are given. Add nothing you know from
  elsewhere: no earlier campaigns, no history of the group, no statement about
  whether a decryptor exists, no CVSS score or CVE id the article does not
  print. If the article does not say it, it is not in the sheet.
- Copy identifiers exactly as written: CVE ids, version strings, product
  names, numbers, dates, domains, IP addresses, hashes.
- summary: 1-2 neutral sentences on what happened, in the article's language.
- affected_products: vendor, product and the affected versions the article
  names (versions empty when it names none).
- dates: each dated event as the article gives it — ISO YYYY-MM-DD when it
  gives day, month and year, otherwise as written. Never turn "yesterday" or
  "on Monday" into a calendar date; the publication date is not an event.
- key_numbers: figures that matter (victims, records, money, percentages,
  durations), the value as written plus its unit and a few words of context.
- exploitation_status: "confirmed" when the article (or the vendor/agency it
  cites) says attacks are happening; "reported" when someone claims
  exploitation that is not confirmed; "not_reported" when the article says no
  exploitation is known; "unknown" when it does not say.
- patch_status: "available", "partial", "workaround_only", "not_available"
  or "unknown" — from the article only.
- claims: statements the article attributes to someone. `attribution` names
  who says it ("Microsoft", "the LockBit gang", "ESET researchers").
  `status`, one of:
    "confirmed"      verified by the article or an authority it cites;
    "reported"       a party asserts it (the gang, the vendor, a researcher);
    "interpretation" the article's own editorial reading or speculation;
    "unverified"     an accusation or report nobody named stands behind;
    "contradictory"  the article itself reports conflicting accounts;
    "unknown"        you cannot tell.
  Write claims in the article's language.
- open_questions: what the article leaves unknown that a defender would want
  to know (who is behind it, whether a patch exists, how many victims). Each
  under 15 words.
- event_type: one of vulnerability_disclosure, active_exploitation, breach,
  ransomware, malware_campaign, phishing_campaign, supply_chain,
  policy_or_advisory, research, other — what the article is mainly about.
- attack_techniques: how the attack works, in a few words each, as the
  article describes it. `mitre_id` ONLY when the article prints an ATT&CK id
  (T1566, T1059.001); otherwise leave it empty. Never map a technique to an
  id yourself.
- impact: one sentence on the consequences the article states, or "".
- mitigations: the defensive steps the article (or the vendor it cites)
  gives — patch to version X, disable feature Y. Nothing generic of your own.
- iocs: indicators the article prints (ip, domain, url, hash, email, file),
  `value` copied character for character, including any defanging ("[.]").
- contradictions: places where the article reports conflicting accounts
  (vendor says no exploitation, researchers say otherwise), with who says
  what in `sources`.
- evidence: for each important claim and identifier (CVE, affected
  version, exploitation, patch, attribution, victim count), one entry:
  `claim` (short), `source` (who says it), `url` only if the article gives
  it, `excerpt` copied VERBATIM from the article (at most 25 words),
  `primary` true only when the source is the vendor, agency, victim or
  researcher speaking for itself, and `status` from the claim vocabulary.
- An empty list or "unknown" is the correct answer when the article says
  nothing. Never guess.
""".strip()


def build_fact_sheet_prompts(item: "NewsItem") -> tuple[str, str]:
    """(system, user) for one extraction. The system prompt is byte-stable."""
    user = (
        f"SOURCE: {item.source}\n"
        f"URL: {item.url}\n"
        f"PUBLISHED: {item.published_at.isoformat()}\n"
        f"TITLE: {item.title}\n"
        f"BODY:\n{_truncate_source_body(item.raw_content)}\n\n"
        "Return the fact sheet as one JSON object."
    )
    return FACT_SHEET_SYSTEM_PROMPT, user


def extract_fact_sheet(provider: Any, item: "NewsItem") -> FactSheet:
    """One provider call → a validated FactSheet. Raises on any failure."""
    generate_json = getattr(provider, "generate_json", None)
    if generate_json is None:
        raise RuntimeError("provider has no generate_json")
    system, user = build_fact_sheet_prompts(item)
    from ..ops.usage import stage
    with stage("fact_sheet"):
        raw = generate_json(system, user, schema=FactSheet.model_json_schema())
    if not isinstance(raw, dict):
        raise RuntimeError("fact sheet answer was not a JSON object")
    return FactSheet.model_validate(raw)


def sanitize_fact_sheet(
    sheet: FactSheet, source_title: str, source_body: str,
    *, source_name: str = "", source_url: str = "",
) -> tuple[FactSheet, list[str]]:
    """Drop hard identifiers the source does not contain.

    Returns the cleaned sheet and the list of what was removed. Only CVE ids
    and CVSS scores are filtered — they are the sheet's structured hard
    fields, and the ones `fact_check` lets the sheet vouch for.
    """
    support = build_support(source_title, source_body, None)
    source_cves = support.hard.get("cve", set())
    dropped: list[str] = []

    cves: list[str] = []
    for raw in sheet.cve_ids:
        toks = [t for t in extract_tokens(raw) if t.kind == "cve"]
        if not toks:
            dropped.append(f"cve:{raw}")
            continue
        norm = toks[0].norm
        if norm not in source_cves:
            dropped.append(f"cve:{norm}")
        elif norm not in cves:
            cves.append(norm)

    scores: list[CvssScore] = []
    for score in sheet.cvss_scores:
        key = f"{score.score:.1f}"
        if not 0 <= score.score <= 10 or (
            key not in support.hard.get("cvss", set()) and key not in support.decimals
        ):
            dropped.append(f"cvss:{key}")
            continue
        cve = score.cve_id.upper().strip()
        scores.append(CvssScore(
            score=score.score,
            cve_id=cve if cve in source_cves else "",
            version=score.version,
        ))

    # Version-2 fields: anything presented as verbatim must be verbatim.
    haystack = _norm_space(f"{source_title}\n{source_body}")
    iocs: list[Ioc] = []
    for ioc in sheet.iocs:
        if ioc.value.strip() and _norm_space(ioc.value) in haystack:
            iocs.append(ioc)
        else:
            dropped.append(f"ioc:{ioc.value[:60]}")
    techniques: list[AttackTechnique] = []
    for tech in sheet.attack_techniques:
        mitre = tech.mitre_id.strip().upper()
        if mitre and (not _MITRE_RE.match(mitre) or mitre.lower() not in haystack):
            dropped.append(f"mitre:{mitre}")
            mitre = ""
        techniques.append(AttackTechnique(description=tech.description, mitre_id=mitre))
    evidence: list[Evidence] = []
    for ev in sheet.evidence:
        if ev.excerpt and _norm_space(ev.excerpt) not in haystack:
            dropped.append(f"excerpt:{ev.excerpt[:40]}")
            ev = ev.model_copy(update={"excerpt": ""})
        evidence.append(ev.model_copy(update={
            "source": ev.source or source_name,
            "url": ev.url or source_url,
        }))

    cleaned = sheet.model_copy(update={
        "cve_ids": cves, "cvss_scores": scores, "iocs": iocs,
        "attack_techniques": techniques, "evidence": evidence,
    })
    return cleaned, dropped


# ===========================================================================
# Cache
# ===========================================================================

@dataclass
class FactSheetEntry:
    """One cache record: a sheet, or the marker that extraction failed."""

    status: str                     # "ok" | "failed"
    sheet: FactSheet | None = None
    provider: str = ""
    created_at: str = ""
    error: str = ""
    dropped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": self.status, "provider": self.provider,
            "created_at": self.created_at, "schema_version": FACT_SHEET_SCHEMA_VERSION,
        }
        if self.sheet is not None:
            out["sheet"] = self.sheet.model_dump()
        if self.error:
            out["error"] = self.error
        if self.dropped:
            out["dropped"] = list(self.dropped)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FactSheetEntry":
        sheet_raw = data.get("sheet")
        sheet = FactSheet.model_validate(sheet_raw) if isinstance(sheet_raw, dict) else None
        status = str(data.get("status") or ("ok" if sheet else "failed"))
        return cls(
            status=status if sheet is not None or status == "failed" else "failed",
            sheet=sheet,
            provider=str(data.get("provider") or ""),
            created_at=str(data.get("created_at") or ""),
            error=str(data.get("error") or ""),
            dropped=[str(x) for x in (data.get("dropped") or [])],
        )


class FactSheetCache:
    """`{fingerprint: entry}` in one JSON file. Same discipline as
    `ThreatPostCache`: atomic temp-file writes, mtime-based reload so a
    concurrent `generate` and `serve` see each other's writes.

    Constructing one never creates the file; only `set` does. That keeps
    read-only tools (`review score-archive`) from leaving artifacts behind.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._store: dict[str, dict[str, Any]] = {}
        self._mtime_seen = 0.0
        self._load()

    def _mtime(self) -> float:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return 0.0

    def _load(self) -> None:
        if not self._path.exists():
            self._store, self._mtime_seen = {}, 0.0
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            raw = payload.get("sheets", {}) if isinstance(payload, dict) else {}
            self._store = {k: v for k, v in raw.items() if isinstance(v, dict)}
            self._mtime_seen = self._mtime()
        except (OSError, ValueError) as exc:
            logger.warning("Corrupt fact-sheet cache at %s (%s) — starting empty.", self._path, exc)
            self._store, self._mtime_seen = {}, 0.0

    def _maybe_reload(self) -> None:
        if self._mtime() > self._mtime_seen:
            self._load()

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".fact-sheets-", suffix=".json", dir=str(self._path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": FACT_SHEET_SCHEMA_VERSION, "sheets": self._store},
                          fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self._path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        self._mtime_seen = self._mtime()

    def get(self, fingerprint: str) -> FactSheetEntry | None:
        self._maybe_reload()
        raw = self._store.get(fingerprint)
        if raw is None:
            return None
        try:
            return FactSheetEntry.from_dict(raw)
        except Exception as exc:  # pydantic ValidationError on a hand edit
            logger.warning("fact sheet for %s is malformed (%s) — ignoring", fingerprint, exc)
            return None

    def set(self, fingerprint: str, entry: FactSheetEntry) -> None:
        self._maybe_reload()
        self._store[fingerprint] = entry.to_dict()
        self._flush()

    def __len__(self) -> int:
        return len(self._store)


# ===========================================================================
# Get-or-create
# ===========================================================================

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_or_create_fact_sheet(
    provider: Any,
    item: "NewsItem",
    cache: FactSheetCache | None,
    memo: dict[str, FactSheet | None] | None = None,
) -> FactSheet | None:
    """The sheet for `item`, extracting it (one call) only if never attempted.

    `memo` is an in-process map for when no cache is configured, so the two
    locale renders of one story inside one process still share one call.
    Never raises: any failure means "no sheet".
    """
    fp = item.fingerprint
    if memo is not None and fp in memo:
        return memo[fp]
    if cache is not None:
        entry = cache.get(fp)
        if entry is not None:
            sheet = entry.sheet if entry.status == "ok" else None
            if memo is not None:
                memo[fp] = sheet
            _bump("fact_sheet_cache_hits")
            return sheet

    name = str(getattr(provider, "name", "") or "")
    try:
        raw_sheet = extract_fact_sheet(provider, item)
        sheet, dropped = sanitize_fact_sheet(
            raw_sheet, item.title, item.raw_content,
            source_name=item.source, source_url=item.url,
        )
    except Exception as exc:
        logger.warning("fact sheet extraction failed for %s (%s); rendering without one",
                       fp, exc)
        _bump("fact_sheet_failures")
        if cache is not None:
            try:
                cache.set(fp, FactSheetEntry(status="failed", provider=name,
                                             created_at=_now_iso(), error=str(exc)[:300]))
            except OSError as write_exc:  # pragma: no cover - disk trouble
                logger.warning("could not record fact-sheet failure: %s", write_exc)
        if memo is not None:
            memo[fp] = None
        return None

    if dropped:
        logger.info("fact sheet for %s: dropped identifiers not in source: %s", fp, dropped)
    if cache is not None:
        try:
            cache.set(fp, FactSheetEntry(status="ok", sheet=sheet, provider=name,
                                         created_at=_now_iso(), dropped=dropped))
        except OSError as exc:  # pragma: no cover - disk trouble
            logger.warning("could not cache fact sheet for %s: %s", fp, exc)
    if memo is not None:
        memo[fp] = sheet
    _bump("fact_sheet_extracted")
    return sheet


def _bump(counter: str) -> None:
    try:
        from ..observability import get_quality_metrics
        get_quality_metrics().bump(counter)
    except Exception:  # pragma: no cover - observability never blocks generation
        pass


# ===========================================================================
# Cluster evidence — one story, several articles, independent origins only
# ===========================================================================

class SupportedFact(BaseModel):
    """One identifier or claim across a story's articles.

    `origins` are INDEPENDENT origins (`pipeline.dedup.source_origins`): two
    syndicated copies, or an article that says "according to
    BleepingComputer", count once. `sources` lists every outlet that carried
    it, for display.
    """
    model_config = ConfigDict(extra="ignore")
    kind: str                         # cve | product | actor | malware | ioc | claim
    value: str
    origins: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    primary: bool = False
    status: ClaimStatus = "reported"
    evidence: list[Evidence] = Field(default_factory=list)


class ClusterEvidence(BaseModel):
    model_config = ConfigDict(extra="ignore")
    independent_sources: list[str] = Field(default_factory=list)
    members: int = 0
    sheets: int = 0
    event_type: EventType = "other"
    exploitation_status: ExploitationStatus = "unknown"
    patch_status: PatchStatus = "unknown"
    facts: list[SupportedFact] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)

    def confirmed(self) -> list[SupportedFact]:
        return [f for f in self.facts if f.status == "confirmed"]


_EXPLOIT_RANK = {"confirmed": 3, "reported": 2, "not_reported": 1, "unknown": 0}
_PATCH_RANK = {"available": 4, "partial": 3, "workaround_only": 2, "not_available": 1, "unknown": 0}


def cluster_evidence(
    members: "Sequence[NewsItem]",
    sheets: "Mapping[str, FactSheet | None]",
) -> ClusterEvidence:
    """Merge the fact sheets of one story's articles.

    `sheets` maps fingerprint → sheet (missing / None = no sheet). Pure.

    * An identifier or claim is "confirmed" when two INDEPENDENT origins
      carry it, or a primary source states it as confirmed. Syndicated
      copies never confirm each other.
    * Disagreements become `contradictions`: exploitation confirmed by one
      origin and "not reported" by another; a patch available vs not
      available; different affected versions for the same product (the same
      CVE with different version ranges stays ONE story — the difference is
      recorded here, not split off).
    * Each sheet's own contradictions are carried over with their sources.
    """
    from ..pipeline.dedup import StoryFeatures, source_origins

    origin = source_origins([StoryFeatures.from_item(m) for m in members])
    by_fp = {m.fingerprint: m for m in members}
    facts: dict[tuple[str, str], SupportedFact] = {}

    def add(kind: str, value: str, fp: str, ev: list[Evidence] | None = None,
            primary: bool = False, status: str = "reported") -> None:
        value = (value or "").strip()
        if not value:
            return
        key = (kind, _norm_space(value))
        fact = facts.get(key)
        if fact is None:
            fact = facts[key] = SupportedFact(kind=kind, value=value)
        o, src = origin.get(fp, by_fp[fp].source), by_fp[fp].source
        if o not in fact.origins:
            fact.origins.append(o)
        if src not in fact.sources:
            fact.sources.append(src)
        fact.evidence.extend(ev or [])
        if primary and status == "confirmed":
            fact.primary = True
        if status in ("contradictory", "interpretation") and fact.status == "reported":
            fact.status = "contradictory" if status == "contradictory" else "interpretation"

    used = [(m.fingerprint, sheets.get(m.fingerprint)) for m in members]
    present = [(fp, sh) for fp, sh in used if sh is not None]
    contradictions: list[Contradiction] = []
    versions: dict[str, dict[str, set[str]]] = {}
    exploitation: dict[str, set[str]] = {}
    patch: dict[str, set[str]] = {}
    event_types: list[str] = []

    for fp, sheet in present:
        assert sheet is not None
        o = origin.get(fp, by_fp[fp].source)
        ev_for = {_norm_space(e.claim): e for e in sheet.evidence}

        def evid(value: str) -> list[Evidence]:
            hit = [e for k, e in ev_for.items() if _norm_space(value) in k]
            return hit[:2]

        for cve in sheet.cve_ids:
            add("cve", cve, fp, evid(cve))
        for prod in sheet.affected_products:
            name = " ".join(x for x in (prod.vendor, prod.product) if x)
            add("product", name, fp, evid(prod.product))
            if prod.versions:
                versions.setdefault(_norm_space(name), {}).setdefault(o, set()).update(
                    prod.versions)
        for actor in sheet.threat_actors:
            add("actor", actor, fp, evid(actor))
        for fam in sheet.malware_families:
            add("malware", fam, fp, evid(fam))
        for ioc in sheet.iocs:
            add("ioc", f"{ioc.type}:{ioc.value}" if ioc.type else ioc.value, fp)
        for claim in sheet.claims:
            add("claim", claim.statement, fp, status=claim.status)
        for e in sheet.evidence:
            add("claim", e.claim, fp, [e], primary=e.primary, status=e.status)
        if sheet.exploitation_status != "unknown":
            exploitation.setdefault(sheet.exploitation_status, set()).add(o)
        if sheet.patch_status != "unknown":
            patch.setdefault(sheet.patch_status, set()).add(o)
        if sheet.event_type != "other":
            event_types.append(sheet.event_type)
        for c in sheet.contradictions:
            contradictions.append(Contradiction(
                statement=c.statement, sources=list(c.sources) or [o]))

    for fact in facts.values():
        if fact.status in ("contradictory", "interpretation"):
            continue
        if len(fact.origins) >= 2 or fact.primary:
            fact.status = "confirmed"

    if "not_reported" in exploitation and ({"confirmed", "reported"} & exploitation.keys()):
        yes = sorted(exploitation.get("confirmed", set()) | exploitation.get("reported", set()))
        contradictions.append(Contradiction(
            statement="exploitation reported by some sources, not reported by others",
            sources=yes + sorted(exploitation["not_reported"])))
    if "available" in patch and "not_available" in patch:
        contradictions.append(Contradiction(
            statement="sources disagree on whether a patch is available",
            sources=sorted(patch["available"] | patch["not_available"])))
    for product, per_origin in versions.items():
        distinct = {frozenset(v) for v in per_origin.values()}
        if len(distinct) > 1:
            listing = "; ".join(f"{o}: {', '.join(sorted(v))}" for o, v in per_origin.items())
            contradictions.append(Contradiction(
                statement=f"affected versions of {product} differ ({listing})",
                sources=sorted(per_origin)))

    def best(found: dict[str, set[str]], rank: dict[str, int]) -> str:
        return max(found, key=lambda k: rank.get(k, 0)) if found else "unknown"

    independent: list[str] = []
    for o in origin.values():
        if o not in independent:
            independent.append(o)
    event = max(sorted(set(event_types)), key=event_types.count) if event_types else "other"
    return ClusterEvidence.model_validate({
        "independent_sources": independent,
        "members": len(members),
        "sheets": len(present),
        "event_type": event,
        "exploitation_status": best(exploitation, _EXPLOIT_RANK),
        "patch_status": best(patch, _PATCH_RANK),
        "facts": list(facts.values()),
        "contradictions": contradictions,
    })


__all__ = [
    "AttackTechnique",
    "ClusterEvidence",
    "Contradiction",
    "Evidence",
    "EventType",
    "Ioc",
    "MAX_EXCERPT_WORDS",
    "SupportedFact",
    "cluster_evidence",
    "AffectedProduct",
    "Claim",
    "CvssScore",
    "DatedEvent",
    "FACT_SHEET_SYSTEM_PROMPT",
    "FactSheet",
    "FactSheetCache",
    "FactSheetEntry",
    "KeyNumber",
    "build_fact_sheet_prompts",
    "extract_fact_sheet",
    "get_or_create_fact_sheet",
    "sanitize_fact_sheet",
]
