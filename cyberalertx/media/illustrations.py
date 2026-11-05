"""Editorial illustrations: who qualifies, what to ask for, and the provider seam.

Scope `all` (default): every public story gets one illustration. Scope
`selective`: only stories the Intelligence Core ranks highly, never out of
scope, unverified, low-confidence or too thin ones. Spending is capped by the
engine (per run, per day, per month).

One illustration per STORY (shared by EN and UA cards). Its prompt is built
only from verified story information: the fact sheet / cluster evidence when
present, otherwise the story's own category and named products. Nothing is
invented to make a prompt more vivid, and exploitation is only depicted when
the evidence says it is confirmed.

Generation runs on the server only, at no per-image cost: the SVG renderer
(media/svg_art.py) always; a local ComfyUI worker (media/comfyui.py) only when
explicitly enabled, healthy and with memory to spare, falling back to SVG.
No paid or remote image API is used.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

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
    #: "all": every public story (in scope, with a published EN or UA brief)
    #: gets one illustration; "selective": only high-priority stories (the
    #: Phase 3 rules below). Env CYBERALERTX_ILLUSTRATION_SCOPE.
    scope: str = "all"

    @classmethod
    def from_env(cls) -> "EligibilityConfig":
        scope = (os.getenv("CYBERALERTX_ILLUSTRATION_SCOPE") or "all").strip().lower()
        return cls(
            min_importance=float(os.getenv("CYBERALERTX_ILLUSTRATION_MIN_SCORE", "55")),
            top_n=int(os.getenv("CYBERALERTX_ILLUSTRATION_TOP_N", "3")),
            scope=scope if scope in ("all", "selective") else "all",
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
    if cfg.scope == "all":
        posts = getattr(story, "posts", None) or {}
        published = [p for p in posts.values() if p is not None
                     and str(getattr(p, "review_status", "auto") or "auto") != "rejected"
                     and str(getattr(p, "generated_by", "") or "") not in ("", "rule_based")]
        if not published:
            no.append("no published AI brief")
        return Eligibility(not no, no or ["public story"])
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
#
# An article-specific visual BRIEF, built only from verified fields of the
# story (category, affected platforms, audience, and the evidence labels from
# pipeline/evidence.py). The title is never sent: it can carry claims the
# evidence does not support. Brands are mapped to their technology category
# (no logos), and the depiction follows the evidence: an unconfirmed
# exploitation or compromise is shown as exposure or inspection, never as an
# attack in progress or data leaving.

PROMPT_VERSION = "illus-2"

STYLE = (
    "Premium editorial illustration for a cybersecurity intelligence publication. "
    "Sophisticated art direction, strong composition with one clear focal point, "
    "cinematic soft lighting and real depth, finely detailed technical forms. "
    "Deep graphite environment (#0E1116 to #1A1F27) with a single restrained cyan "
    "accent (#06B6D4) marking the focal point; otherwise muted steel greys. "
    "Clearly an illustration, not a photograph of a real incident."
)
AVOID = (
    "No text, letters, numbers, code or binary digits anywhere. No logos, brand "
    "marks or product names. No people's faces, no hooded hackers. No screenshots, "
    "terminals, dashboards or fake user interfaces. No padlocks, glowing shields, "
    "matrix rain, generic circuit-board backgrounds or flags."
)

# platform / audience -> scene (technology category, never a brand)
_SCENE = {
    "android": ("a modern smartphone", "сучасний смартфон"),
    "ios": ("a modern smartphone", "сучасний смартфон"),
    "telegram": ("a messaging app conversation on a smartphone, shown abstractly", "розмова в месенджері на смартфоні, абстрактно"),
    "linux": ("a rack of servers in a data centre", "стійка серверів у дата-центрі"),
    "windows": ("a desktop workstation", "робоча станція"),
    "wordpress": ("a website publishing system on a web server", "система публікації сайту на вебсервері"),
    "cisco": ("enterprise network appliances: routers and VPN gateways at the network edge", "мережеве обладнання: маршрутизатори й VPN-шлюзи на межі мережі"),
    "chrome": ("a web browser window frame without readable content", "вікно браузера без читабельного вмісту"),
    "safari": ("a web browser window frame without readable content", "вікно браузера без читабельного вмісту"),
    "outlook": ("a workplace email and collaboration system", "корпоративна пошта й робочі застосунки"),
    "microsoft 365": ("a workplace email and collaboration system", "корпоративна пошта й робочі застосунки"),
    "slack": ("a workplace collaboration system", "робочий застосунок для спільної роботи"),
    "vmware": ("a virtualised data-centre host running many virtual machines", "сервер віртуалізації з багатьма віртуальними машинами"),
    "kubernetes": ("a cluster of containerised services", "кластер контейнерних сервісів"),
    "banking": ("a mobile banking and payment flow", "мобільний банкінг і платежі"),
    "crypto_users": ("a cryptocurrency wallet and its keys, represented abstractly", "криптогаманець і його ключі, абстрактно"),
    "developers": ("a software build pipeline with packages flowing between stages", "конвеєр збирання ПЗ з пакетами між етапами"),
    "sysadmins": ("a server room", "серверна"),
    "enterprise": ("a corporate network connecting offices and servers", "корпоративна мережа офісів і серверів"),
    "mobile_users": ("a modern smartphone", "сучасний смартфон"),
    "normal_users": ("a home computer and phone", "домашній комп'ютер і телефон"),
}

# event -> (what is shown, EN alt, UA alt); chosen by category AND evidence
_ACTION = {
    "exploited": ("an attack path actively entering one exposed component, the cyan accent on the entry point",
                  "attack path entering an exposed component", "шлях атаки, що проникає у вразливий компонент"),
    "exposed": ("one weak point exposed in an otherwise sealed structure, inspected closely; no attack in progress",
                "an exposed weak point, no attack shown", "відкрите вразливе місце, без зображення атаки"),
    "ransomware": ("storage and systems sealed shut and operations halted, a single cyan seal on the locked core",
                   "systems sealed by ransomware", "системи, заблоковані програмою-вимагачем"),
    "breach_confirmed": ("records leaving a breached archive through one opening",
                         "records leaving a breached archive", "записи, що залишають зламаний архів"),
    "breach_unconfirmed": ("an intact archive under inspection, one section highlighted for review; nothing leaving it",
                           "an archive under inspection, no data shown leaving", "архів під перевіркою, без витоку даних"),
    "phishing": ("a deceptive message shape leading toward a counterfeit gateway that mimics a genuine one",
                 "a deceptive message leading to a counterfeit gateway", "оманливе повідомлення, що веде до підробленого входу"),
    "scam": ("a counterfeit storefront and payment path beside the genuine one, subtly wrong",
             "a counterfeit payment path beside a genuine one", "підроблений шлях оплати поруч зі справжнім"),
    "malware": ("a small foreign component travelling along the delivery chain into the system",
                "a foreign component moving through the delivery chain", "чужорідний компонент, що рухається ланцюгом доставки"),
    "botnet": ("many small connected devices pulsing in unison, directed by one hidden node",
               "many devices directed by one hidden node", "багато пристроїв під керуванням одного прихованого вузла"),
    "disrupted": ("dismantled infrastructure: severed links and powered-down nodes",
                  "dismantled attacker infrastructure", "демонтована інфраструктура зловмисників"),
    "analysis": ("a calm analytical cross-section revealing how the mechanism works",
                 "an analytical cross-section of the mechanism", "аналітичний розріз механізму"),
}


def _event(category: str, ev: Any) -> str:
    exploitation = str(getattr(ev, "exploitation", "") or "")
    compromise = str(getattr(ev, "compromise", "") or "")
    campaign = str(getattr(ev, "campaign", "") or "")
    if campaign == "disrupted":
        return "disrupted"
    if category == "ransomware":
        return "ransomware"
    if category in ("breach", "data leak"):
        return "breach_confirmed" if compromise == "confirmed" else "breach_unconfirmed"
    if category in ("phishing", "social engineering"):
        return "phishing"
    if category == "scam":
        return "scam"
    if category == "botnet":
        return "botnet"
    if category in ("malware", "spyware"):
        return "malware"
    if category in ("vulnerability", "exploit", "zero-day"):
        return "exploited" if exploitation == "confirmed" else "exposed"
    return "analysis"


@dataclass
class IllustrationPrompt:
    prompt: str
    inputs: dict[str, Any]
    inputs_hash: str
    alt: dict[str, str]


def build_prompt(story: Any, evaluation: Any) -> IllustrationPrompt:
    """Article-specific brief from verified story fields only (see above)."""
    from ..pipeline.evidence import assess

    anchor = story.anchor
    ev = assess(anchor)
    category = str(anchor.category or "other").lower()
    event = _event(category, ev)
    keys = [str(p).lower() for p in (getattr(anchor, "affected_platforms", None) or [])]
    keys += [str(a) for a in (getattr(anchor, "audience_targets", None) or [])]
    scenes: list[tuple[str, str]] = []
    for k in keys:
        sc = _SCENE.get(k)
        if sc and sc not in scenes:
            scenes.append(sc)
    scenes = scenes[:2]
    action, alt_en, alt_ua = _ACTION[event]
    inputs = {"v": PROMPT_VERSION, "event": event, "category": category,
              "scenes": [s[0] for s in scenes], "exploitation": ev.exploitation,
              "compromise": ev.compromise or "", "campaign": ev.campaign or ""}
    setting = (" Setting: " + " and ".join(s[0] for s in scenes) + ".") if scenes else \
        " Setting: the affected technology, represented as a clean abstract system."
    must_not = [
        "Do not depict a confirmed attack, victims or data leaving unless stated above.",
        "Do not suggest who is responsible: no nationalities, flags or symbols.",
    ]
    prompt = f"{STYLE} Subject: {action}.{setting} {' '.join(must_not)} {AVOID}"
    h = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:16]
    where_en = (" in " + " and ".join(s[0] for s in scenes)) if scenes else ""
    where_ua = (" — " + "; ".join(s[1] for s in scenes)) if scenes else ""
    alt = {"en": f"Illustration: {alt_en}{where_en}.", "ua": f"Ілюстрація: {alt_ua}{where_ua}."}
    return IllustrationPrompt(prompt, inputs, h, alt)


# ---------------------------------------------------------------- SVG visual brief

# platform / audience key -> SVG scene (svg_art.SCENES)
_SCENE_KIND = {
    "android": "phone", "ios": "phone", "telegram": "phone", "mobile_users": "phone",
    "linux": "rack", "sysadmins": "server_room", "windows": "workstation", "wordpress": "web",
    "cisco": "network_edge", "chrome": "browser", "safari": "browser", "outlook": "mail",
    "microsoft 365": "mail", "slack": "mail", "vmware": "vm", "kubernetes": "containers",
    "banking": "payments", "crypto_users": "wallet", "developers": "pipeline", "enterprise": "corporate",
    "normal_users": "home",
}
# technology words in the SOURCE title (verified text) -> scene
_TITLE_SCENE = (
    (re.compile(r"\b(ICS|SCADA|PLC|OT|industrial|water utilit|power plant|turbine|pipeline operator|refrigerat\w*|"
                r"HVAC|building management|medical device|hospital|blood)\b", re.I), "industrial"),
    (re.compile(r"\b(session|cookie|MFA|2FA|OAuth|login|account takeover|passkey|SSO)\b", re.I), "cloud"),
    (re.compile(r"\b(cloud|AWS|Azure|GCP|S3 bucket|tenant|SaaS|Okta|Entra|identity provider)\b", re.I), "cloud"),
    (re.compile(r"\b(LLM|AI model|AI agent|ChatGPT|Copilot|Gemini|Claude|machine learning)\b", re.I), "ai"),
    (re.compile(r"\b(router|firewall|VPN|gateway|switch(es)?|edge device|Fortinet|FortiGate|Ivanti|Citrix|SonicWall|Palo Alto)\b", re.I), "network_edge"),
    (re.compile(r"\b(npm|PyPI|package|supply.chain|GitHub|CI/CD|repository)\b", re.I), "pipeline"),
    (re.compile(r"\b(e-?mail|Exchange|Outlook|mailbox|SharePoint|Microsoft 365)\b", re.I), "mail"),
    (re.compile(r"\b(macOS|Mac|Apple|Windows)\b", re.I), "workstation"),
    (re.compile(r"\b(Android|iPhone|iOS|smartphone|mobile app)\b", re.I), "phone"),
    (re.compile(r"\b(crypto|wallet|bitcoin|exchange hack|DeFi)\b", re.I), "wallet"),
    (re.compile(r"\b(browser|Chrome|Firefox|Safari|extension)\b", re.I), "browser"),
    (re.compile(r"\b(WordPress|plugin|website|CMS|web server)\b", re.I), "web"),
)


# what each SVG scene shows, for alt text (EN, UA)
_KIND_ALT = {
    "phone": ("a smartphone", "смартфон"), "rack": ("server racks", "серверні стійки"),
    "server_room": ("a server room", "серверна"), "workstation": ("a desktop computer", "настільний комп'ютер"),
    "web": ("a web server and a site", "вебсервер і сайт"), "network_edge": ("network edge appliances", "мережеве обладнання на межі мережі"),
    "browser": ("a web browser", "браузер"), "mail": ("an email and collaboration system", "пошта й робочі застосунки"),
    "vm": ("a virtualisation host", "сервер віртуалізації"), "containers": ("containerised services", "контейнерні сервіси"),
    "payments": ("a payment flow", "платіжний процес"), "wallet": ("a cryptocurrency wallet", "криптогаманець"),
    "pipeline": ("a software build pipeline", "конвеєр збирання ПЗ"), "corporate": ("a corporate network", "корпоративна мережа"),
    "home": ("a home computer and phone", "домашній комп'ютер і телефон"),
    "cloud": ("cloud accounts and identity layers", "хмарні облікові записи й рівні доступу"),
    "industrial": ("industrial control equipment", "обладнання промислового керування"),
    "ai": ("an AI model network", "мережа ШІ-моделі"), "core": ("an abstract system", "абстрактна система"),
}


def visual_brief(story: Any) -> tuple[Any, dict[str, str], str]:
    """(svg_art.VisualBrief, alt text, inputs hash) for a story.

    Same grounding as `build_prompt`: category + evidence decide the event,
    verified platform/audience fields and technology words in the source
    title decide the scene. The seed is the story key, so a story keeps its
    image and different stories get different compositions."""
    from ..pipeline.evidence import assess
    from .svg_art import RENDERER_VERSION, VisualBrief

    prompt = build_prompt(story, None)
    anchor = story.anchor
    scenes: list[str] = []
    for rx, kind in _TITLE_SCENE:
        if rx.search(str(anchor.title or "")) and kind not in scenes:
            scenes.append(kind)
    keys = [str(p).lower() for p in (getattr(anchor, "affected_platforms", None) or [])]
    keys += [str(a) for a in (getattr(anchor, "audience_targets", None) or [])]
    for k in keys:
        mapped = _SCENE_KIND.get(k)
        if mapped and mapped not in scenes:
            scenes.append(mapped)
    ev = assess(anchor)
    brief = VisualBrief(event=prompt.inputs["event"], scenes=tuple(scenes[:2]) or ("core",),
                        seed=f"{story.key}:{RENDERER_VERSION}",
                        campaign_active=ev.campaign == "active")
    inputs = {**prompt.inputs, "renderer": RENDERER_VERSION, "svg_scenes": list(brief.scenes),
              "campaign_active": brief.campaign_active}
    h = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:16]
    _, alt_en, alt_ua = _ACTION[prompt.inputs["event"]]
    # Only the primary scene is drawn (svg_art.render_svg), so only it is described.
    where = [_KIND_ALT[brief.scene]] if brief.scene != "core" and brief.scene in _KIND_ALT else []
    alt = {"en": f"Illustration: {alt_en}" + (f", with {' and '.join(w[0] for w in where)}" if where else "") + ".",
           "ua": f"Ілюстрація: {alt_ua}" + (f"; {', '.join(w[1] for w in where)}" if where else "") + "."}
    return brief, alt, h


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
    method: str = "svg"          # "svg" | "comfyui"


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
           "AVOID", "NoProvider", "PROMPT_VERSION", "ProviderError", "ProviderUnavailable", "STYLE",
           "build_prompt", "eligibility", "provider_from_env", "register_provider"]
