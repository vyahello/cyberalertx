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
from typing import Any, Dict, List, Literal

from pydantic import BaseModel


ThreatLevel = Literal["Low", "Medium", "High", "Critical"]


@dataclass
class ThreatPost:
    """Structured, human-friendly threat post (output of the AI layer)."""

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
    # Provenance — handy for debugging, telemetry, and cache invalidation.
    language: str = "en"
    source_fingerprint: str = ""
    generated_by: str = "rule_based"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

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


__all__ = ["ThreatPost", "ThreatPostResponse", "ThreatLevel"]
