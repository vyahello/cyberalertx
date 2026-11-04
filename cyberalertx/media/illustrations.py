"""Editorial illustrations: who qualifies, what to ask for, and the provider seam.

Selective by design — an illustration costs money, so only stories the
Intelligence Core already ranks highly can get one, and never stories that are
out of scope, unverified, low-confidence or too thin to describe honestly.

One illustration per STORY (shared by EN and UA cards). Its prompt is built
only from verified story information: the fact sheet / cluster evidence when
present, otherwise the story's own category and named products. Nothing is
invented to make a prompt more vivid, and exploitation is only depicted when
the evidence says it is confirmed.

Providers: no image-generation provider is configured in this project (the
Claude subscription and Anthropic API generate text, not images). The
`ImageProvider` protocol is the seam; `CYBERALERTX_IMAGE_PROVIDER` selects one
(default `none` → the engine runs in branded-card-only mode). Tests use a mock.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

PROMPT_VERSION = "illus-1"


# ---------------------------------------------------------------- eligibility

@dataclass(frozen=True)
class EligibilityConfig:
    min_importance: float = 55.0
    #: Also eligible regardless of score when in the Daily Top N or Breaking.
    top_n: int = 3
    require_verification: tuple[str, ...] = ("verified", "partially_verified")
    reject_confidence: tuple[str, ...] = ("low",)
    #: Minimum source text (chars, best member) to describe the event honestly.
    min_context_chars: int = 300

    @classmethod
    def from_env(cls) -> "EligibilityConfig":
        return cls(
            min_importance=float(os.getenv("CYBERALERTX_ILLUSTRATION_MIN_SCORE", "55")),
            top_n=int(os.getenv("CYBERALERTX_ILLUSTRATION_TOP_N", "3")),
        )


@dataclass
class Eligibility:
    eligible: bool
    reasons: list[str] = field(default_factory=list)


def eligibility(
    story: Any,                      # intel.story.StoryView
    evaluation: Any,                 # intel.scoring.Evaluation | None
    *,
    top_rank: int | None = None,
    breaking: bool = False,
    cfg: EligibilityConfig = EligibilityConfig(),
) -> Eligibility:
    no: list[str] = []
    if getattr(story, "relevance", "in_scope") == "out_of_scope":
        no.append("out of scope")
    if evaluation is None:
        no.append("no intelligence evaluation")
        return Eligibility(False, no)
    if evaluation.dim("verification_status") not in cfg.require_verification:
        no.append(f"verification {evaluation.dim('verification_status')}")
    if evaluation.dim("confidence") in cfg.reject_confidence:
        no.append(f"confidence {evaluation.dim('confidence')}")
    context = max((len(m.raw_content or "") for m in story.members), default=0)
    if context < cfg.min_context_chars and not story.sheets:
        no.append(f"too little context ({context} chars, no fact sheet)")
    if no:
        return Eligibility(False, no)
    yes: list[str] = []
    if breaking:
        yes.append("breaking")
    if top_rank is not None and top_rank <= cfg.top_n:
        yes.append(f"daily top {top_rank}")
    if evaluation.score >= cfg.min_importance:
        yes.append(f"importance {evaluation.score:.0f} ≥ {cfg.min_importance:.0f}")
    if evaluation.dim("exploitation_status") == "confirmed" and evaluation.score >= cfg.min_importance - 10:
        yes.append("exploitation confirmed")
    return Eligibility(bool(yes), yes or [f"importance {evaluation.score:.0f} below threshold"])


# ---------------------------------------------------------------- prompt

STYLE = (
    "Editorial illustration for a cybersecurity news publication. Abstract and "
    "conceptual, restrained, flat geometric shapes and soft depth on a deep "
    "graphite background (#0E1116), one cyan accent (#06B6D4) used sparingly, "
    "muted greys. No text, letters, numbers or logos. No people's faces. No "
    "screenshots, terminals, code, dashboards or user interfaces. No padlocks, "
    "shields, hooded hackers, matrix rain, binary digits or neon glow. Not "
    "photorealistic: it must not look like evidence from a real incident."
)

_MOTIF = {
    "vulnerability_disclosure": "an exposed component in an otherwise sealed structure",
    "active_exploitation": "an exposed component in an otherwise sealed structure, with a single intrusion path entering it",
    "ransomware": "an orderly grid of storage blocks, several of them sealed shut",
    "breach": "an orderly archive of record cards with a section spilling outward",
    "malware_campaign": "a small foreign element moving through a network of nodes",
    "phishing_campaign": "a familiar-looking envelope shape with one subtly wrong detail",
    "supply_chain": "a chain of interlocking components where one link is a different material",
    "policy_or_advisory": "a calm signal radiating across a network of nodes",
    "research": "a magnified cross-section of a mechanism revealing an internal flaw",
    "other": "an abstract network of nodes with one node highlighted",
}
_CATEGORY_EVENT = {
    "vulnerability": "vulnerability_disclosure", "exploit": "active_exploitation",
    "zero-day": "active_exploitation", "ransomware": "ransomware", "breach": "breach",
    "data leak": "breach", "malware": "malware_campaign", "spyware": "malware_campaign",
    "botnet": "malware_campaign", "phishing": "phishing_campaign", "scam": "phishing_campaign",
    "social engineering": "phishing_campaign",
}


@dataclass
class IllustrationPrompt:
    prompt: str
    inputs: dict[str, Any]
    inputs_hash: str
    alt: dict[str, str]


def build_prompt(story: Any, evaluation: Any) -> IllustrationPrompt:
    """From verified story information only."""
    ev = getattr(story, "evidence", None)
    event = str(getattr(ev, "event_type", "") or "")
    if not event or event == "other":
        event = _CATEGORY_EVENT.get(str(story.anchor.category), "other")
    exploited = evaluation is not None and evaluation.dim("exploitation_status") == "confirmed"
    if event == "active_exploitation" and not exploited:
        # The evidence does not establish exploitation: depict the exposure only.
        event = "vulnerability_disclosure"
    products: list[str] = []
    for s in getattr(story, "sheets", []) or []:
        for p in getattr(s, "affected_products", []) or []:
            name = str(getattr(p, "product", "") or "").strip()
            if name and name not in products:
                products.append(name)
    inputs = {"v": PROMPT_VERSION, "event": event, "exploited": exploited,
              "category": str(story.anchor.category), "products": sorted(products)[:3]}
    subject = _MOTIF.get(event, _MOTIF["other"])
    kind = (f" The affected technology is a kind of {', '.join(inputs['products'])}; "
            "represent its category abstractly, never its brand.") if inputs["products"] else ""
    prompt = f"{STYLE} Subject: {subject}.{kind}"
    h = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:16]
    alt = {
        "en": f"Abstract illustration: {subject}.",
        "ua": "Абстрактна ілюстрація: " + _MOTIF_UA.get(event, _MOTIF_UA["other"]) + ".",
    }
    return IllustrationPrompt(prompt, inputs, h, alt)


_MOTIF_UA = {
    "vulnerability_disclosure": "відкритий елемент у загалом закритій конструкції",
    "active_exploitation": "відкритий елемент у закритій конструкції, до якого веде шлях проникнення",
    "ransomware": "упорядкована сітка блоків зберігання, кілька з них запечатано",
    "breach": "упорядкований архів карток, частина яких висипається назовні",
    "malware_campaign": "чужорідний елемент, що рухається мережею вузлів",
    "phishing_campaign": "знайомий на вигляд конверт з однією непомітно хибною деталлю",
    "supply_chain": "ланцюг зчеплених деталей, де одна ланка з іншого матеріалу",
    "policy_or_advisory": "спокійний сигнал, що розходиться мережею вузлів",
    "research": "збільшений розріз механізму з помітною внутрішньою вадою",
    "other": "абстрактна мережа вузлів з одним виділеним вузлом",
}


# ---------------------------------------------------------------- providers

class ProviderUnavailable(RuntimeError):
    """No provider configured — the engine runs in branded-card-only mode."""


class ProviderError(RuntimeError):
    """The provider failed for this request (timeout, refusal, bad output)."""


@dataclass
class GeneratedImage:
    data: bytes
    mime: str
    model: str
    cost_usd: float = 0.0


class ImageProvider(Protocol):
    name: str

    def generate(self, prompt: str, *, width: int, height: int, timeout_s: float) -> GeneratedImage: ...


class NoProvider:
    name = "none"

    def generate(self, prompt: str, *, width: int, height: int, timeout_s: float) -> GeneratedImage:
        raise ProviderUnavailable(
            "no image provider configured (CYBERALERTX_IMAGE_PROVIDER); branded cards only")


_REGISTRY: dict[str, type] = {"none": NoProvider}


def register_provider(name: str, cls: type) -> None:
    _REGISTRY[name] = cls


def provider_from_env() -> Any:
    name = (os.getenv("CYBERALERTX_IMAGE_PROVIDER") or "none").strip().lower()
    cls = _REGISTRY.get(name)
    if cls is None:
        raise ProviderUnavailable(f"unknown image provider {name!r}")
    return cls()


__all__ = ["Eligibility", "EligibilityConfig", "GeneratedImage", "IllustrationPrompt", "ImageProvider",
           "NoProvider", "PROMPT_VERSION", "ProviderError", "ProviderUnavailable", "STYLE",
           "build_prompt", "eligibility", "provider_from_env", "register_provider"]
