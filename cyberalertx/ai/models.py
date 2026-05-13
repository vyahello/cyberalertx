"""Domain models for the AI content layer.

`ThreatPost` is the structured output the generator produces — what an UI,
notifier, or downstream feed renders. It is intentionally decoupled from
the data-layer `NewsItem`: a single NewsItem can produce multiple
ThreatPosts (different languages, different audiences) without polluting
the ingestion schema.

`ThreatPostResponse` is the Pydantic shape we hand to the Claude SDK for
`messages.parse()`. Keeping it separate from `ThreatPost` lets us:
  - evolve the public output schema without forcing model-prompt changes
  - swap in different schemas per provider if their constraint coverage differs
  - validate inbound LLM output before constructing the public dataclass
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


ThreatLevel = Literal["Low", "Medium", "High", "Critical"]

# Reference types we recognize. Frontend renders an icon per type.
ReferenceType = Literal["cve", "advisory", "vendor", "cert", "news"]


@dataclass
class Reference:
    """One external reference attached to a ThreatPost.

    Examples:
      * {"type": "cve",      "label": "CVE-2026-1234", "url": "https://nvd.nist.gov/.../CVE-2026-1234"}
      * {"type": "advisory", "label": "CISA AA26-...",  "url": "https://www.cisa.gov/..."}
      * {"type": "vendor",   "label": "Microsoft MSRC", "url": "https://msrc.microsoft.com/..."}
    """
    type: str
    label: str
    url: str

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "label": self.label, "url": self.url}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Reference":
        return cls(
            type=str(data.get("type", "news")),
            label=str(data.get("label", "")),
            url=str(data.get("url", "")),
        )


class ReferenceResponse(BaseModel):
    """Pydantic mirror of `Reference` for LLM structured output."""
    type: ReferenceType = "news"
    label: str
    url: str


@dataclass
class ThreatPost:
    """Structured, human-friendly threat post (output of the AI layer).

    Two layers of body content:
      * `short_summary` — the FEED text. One tight paragraph, 100-200
        chars, scanning-friendly. The card displays this.
      * `detail_body` — the DETAIL PAGE text. 2-5 short paragraphs
        separated by `\\n\\n`, expanding on what happened, who's
        affected, attack flow, signs of compromise. Detail page
        renders this. Empty for items where no expanded analysis
        was generated (rule-based or older cached posts).

    `references` lists external pointers (CVE, advisory, vendor blog).
    Frontend shows them as a compact list on the detail page only —
    never on cards."""

    title: str
    short_summary: str
    threat_level: str  # one of ThreatLevel
    why_it_matters: str
    affected_users: List[str]
    what_to_do: List[str]
    what_not_to_do: List[str] = field(default_factory=list)
    quick_facts: List[str] = field(default_factory=list)
    emotional_weight: float = 0.0
    reading_time_seconds: int = 25
    # ----- new in v0.4 (additive — defaults preserve cache compat) -----
    detail_body: str = ""
    references: List[Reference] = field(default_factory=list)
    # Provenance — handy for debugging, telemetry, and cache invalidation.
    language: str = "en"
    source_fingerprint: str = ""
    generated_by: str = "rule_based"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThreatPost":
        return cls(
            title=data["title"],
            short_summary=data["short_summary"],
            threat_level=data["threat_level"],
            why_it_matters=data["why_it_matters"],
            affected_users=list(data.get("affected_users", [])),
            what_to_do=list(data.get("what_to_do", [])),
            what_not_to_do=list(data.get("what_not_to_do", [])),
            quick_facts=list(data.get("quick_facts", [])),
            emotional_weight=float(data.get("emotional_weight", 0.0)),
            reading_time_seconds=int(data.get("reading_time_seconds", 25)),
            detail_body=str(data.get("detail_body", "")),
            references=[
                Reference.from_dict(r) if isinstance(r, dict) else r
                for r in (data.get("references") or [])
            ],
            language=data.get("language", "en"),
            source_fingerprint=data.get("source_fingerprint", ""),
            generated_by=data.get("generated_by", "rule_based"),
        )


class ThreatPostResponse(BaseModel):
    """Schema we ask the LLM to produce via structured outputs.

    Field order matches the spec for prompt-cache friendliness.
    Constraints (min/max length, ge/le) are intentionally minimal — the
    Anthropic SDK strips unsupported constraints; we re-validate ourselves
    in `ContentGenerator._post_from_response()`.

    `detail_body` and `references` are optional (default empty) — the
    generator works without them on older prompts and the validator
    treats their absence as "nothing extra to show".
    """

    title: str
    short_summary: str
    threat_level: ThreatLevel
    why_it_matters: str
    affected_users: List[str]
    what_to_do: List[str]
    what_not_to_do: List[str]
    quick_facts: List[str]
    emotional_weight: float
    reading_time_seconds: int
    detail_body: str = ""
    references: List[ReferenceResponse] = Field(default_factory=list)


__all__ = [
    "ThreatPost",
    "ThreatPostResponse",
    "ThreatLevel",
    "Reference",
    "ReferenceResponse",
    "ReferenceType",
]
