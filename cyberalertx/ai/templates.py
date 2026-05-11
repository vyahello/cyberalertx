"""Prompt template system.

Design goals:
  * categorical lookup — pick a template by (language, category, audience)
  * fallback chain — every lookup must resolve (English-default is the floor)
  * single render function — templates contribute persona + style notes;
    the JSON schema and metadata block are shared across all of them
  * no string interpolation in the system prompt — the *user* prompt carries
    the per-item facts, so the system prompt is a stable cache prefix

Adding a new template = appending one `PromptTemplate(...)` to the registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping, Tuple

from ..models import NewsItem
from .models import ThreatPostResponse


# Audience labels surfaced to readers — human form of the internal id.
_AUDIENCE_LABELS: Mapping[str, str] = {
    "normal_users": "Everyday users",
    "developers": "Developers",
    "sysadmins": "IT / sysadmins",
    "enterprise": "Enterprise IT",
    "mobile_users": "Mobile users",
    "crypto_users": "Crypto users",
    "general": "Anyone following cybersecurity",
}


@dataclass(frozen=True)
class PromptTemplate:
    """A reusable persona + style preset.

    `id` is purely for telemetry/debug — the registry keys on (lang, cat, aud).

    Fields:
      * `persona`, `style_notes`, `extra_guidance` — drive the LLM prompt
        when a provider is configured.
      * `rule_based` — optional copy that the rule-based generator can pick
        up for the same (lang, cat, aud) triple. Supported keys:
            "why_it_matters" (str)
            "what_to_do"     (list[str])
            "what_not_to_do" (list[str])
        Anything omitted falls back to the rule-based defaults.
    """
    id: str
    language: str      # "en" | "uk"
    category: str      # "phishing" | "ransomware" | "vulnerability" | "default"
    audience: str      # "normal_users" | "developers" | "sysadmins" | "general"
    persona: str
    style_notes: str
    extra_guidance: str = ""
    rule_based: Mapping[str, object] | None = None


# -------- Shared schema / general guidance (appended to every system prompt).

_SHARED_RULES_EN = """
WRITING RULES (apply to every field):
- Modern, clear, practical. Address the reader as "you" when natural.
- No fake fear. No clickbait. No ALL-CAPS. No exclamation marks.
- Avoid corporate jargon ("synergy", "leverage", "robust solution").
- Translate technical risk into human impact: "attackers can steal saved
  passwords" beats "this enables session token theft via XSS".
- Be specific in actions ("Update Chrome from Settings > About") beats
  vague advice ("Stay safe online").

FIELD CONTRACTS:
- title — 6-14 words. Descriptive, not sensational. No questions, no caps.
- short_summary — 2-4 sentences. Answer what / who / why in plain language.
- threat_level — Low | Medium | High | Critical. Calibrate using the metadata:
    urgent_action + threat_score >= 50 OR active mass exploitation -> Critical
    urgent_action OR threat_score >= 50                            -> High
    recommended_action OR threat_score >= 30                       -> Medium
    informational with no immediate user exposure                  -> Low
- why_it_matters — 1-2 sentences. Lead with human consequence.
- affected_users — 1-6 entries. Concrete audience labels
  ("Chrome users on Windows", "Gmail account holders", "iPhone users").
- what_to_do — 1-4 concrete actions. Each starts with a verb.
- what_not_to_do — 0-3 anti-patterns. Use "Don't ..." or "Avoid ...".
- quick_facts — 2-4 ultra-short bullets (3-7 words each).
- emotional_weight — float in [0, 1]. NOT fear. Represents urgency + how
  much it should disrupt the reader's day. Routine FYI ~0.2; critical
  actively-exploited zero-day ~0.95.
- reading_time_seconds — integer 15-45 estimating mobile read time.

OUTPUT: exactly one JSON object matching the schema. No prose around it.
""".strip()


_SHARED_RULES_UK = """
ПРАВИЛА ПИСЬМА (для всіх полів):
- Сучасно, чітко, практично. Звертайтеся до читача на "ви".
- Без штучного страху. Без клікбейту. Без КАПСЛОКУ. Без знаків оклику.
- Уникайте корпоративного жаргону.
- Перекладайте технічні ризики у людський вплив: "зловмисники можуть
  викрасти збережені паролі" краще ніж "це дозволяє RCE через XSS".
- Конкретика в діях ("Оновіть Chrome у Налаштуваннях > Про програму")
  замість загальних порад ("Будьте обережні в інтернеті").

КОНТРАКТИ ПОЛІВ — такі самі як в англійській версії; усі тексти українською.
OUTPUT: один JSON-обʼєкт відповідно до схеми. Без додаткового тексту.
""".strip()


# --------------------------- Template registry -----------------------------

_TEMPLATES: list[PromptTemplate] = [
    # ---------------- English ----------------
    PromptTemplate(
        id="en/default/general",
        language="en",
        category="default",
        audience="general",
        persona=(
            "You write for CyberAlertX, a modern cybersecurity awareness "
            "product whose audience is normal users, developers, and IT "
            "professionals. Your voice is calm, direct, and useful."
        ),
        style_notes=(
            "Keep things scannable. Lead with the user impact, not the "
            "technical mechanism. Cite specifics from the source article."
        ),
    ),
    PromptTemplate(
        id="en/phishing/normal_users",
        language="en",
        category="phishing",
        audience="normal_users",
        persona=(
            "You write phishing & scam alerts for everyday users on "
            "CyberAlertX. Most readers are not technical."
        ),
        style_notes=(
            "Center the user's experience: what does the lure look like, "
            "where does it arrive (email, SMS, DM), what does the attacker "
            "want (credentials, payment, OTP). Concrete red flags beat theory."
        ),
        extra_guidance=(
            "what_to_do should include verification steps the user can take "
            "BEFORE clicking. what_not_to_do should call out the exact bait "
            "behavior to avoid."
        ),
        rule_based={
            "why_it_matters": (
                "These campaigns aim straight at your login. A few "
                "seconds of caution before clicking is the whole defense."
            ),
            "what_to_do": [
                "Open the service directly in your browser instead of clicking the email link",
                "Check the sender address — not the display name — for lookalike domains",
                "Turn on two-factor authentication if you haven't already",
            ],
            "what_not_to_do": [
                "Don't paste your password into a page you reached by clicking a link",
                "Don't share one-time codes — no real service will ever ask",
            ],
        },
    ),
    PromptTemplate(
        id="en/ransomware/general",
        language="en",
        category="ransomware",
        audience="general",
        persona=(
            "You explain ransomware incidents to a mixed audience. Some "
            "readers are sysadmins; some are everyday users curious about "
            "the news."
        ),
        style_notes=(
            "Name the strain when possible. Note the victim sector. Be "
            "explicit about what data is at risk and whether decryptors "
            "are available."
        ),
    ),
    PromptTemplate(
        id="en/vulnerability/developers",
        language="en",
        category="vulnerability",
        audience="developers",
        persona=(
            "You write for software engineers triaging a vulnerability. "
            "They want to know: which library, which CVE, is there a fix."
        ),
        style_notes=(
            "Technical specificity is welcome — CVE IDs, affected versions, "
            "package names, exploitation status. Keep prose tight."
        ),
        extra_guidance=(
            "what_to_do should focus on package upgrades, dependency audits, "
            "and detection queries."
        ),
        rule_based={
            "why_it_matters": (
                "Worth a quick check against your dependencies — if you're "
                "shipping the affected version, you're on the hook."
            ),
            "what_to_do": [
                "Grep your lockfiles for the affected package/version",
                "Upgrade and redeploy as soon as a fixed version is published",
                "Check vendor advisories for indicators of compromise",
            ],
        },
    ),
    PromptTemplate(
        id="en/exploit/sysadmins",
        language="en",
        category="exploit",
        audience="sysadmins",
        persona=(
            "You write for IT admins and network engineers managing the "
            "infrastructure under attack."
        ),
        style_notes=(
            "Mention affected products by vendor and version. Mention IOC "
            "availability if the article does. Prefer concrete remediation."
        ),
    ),
    # ---------------- Ukrainian --------------
    PromptTemplate(
        id="uk/default/general",
        language="uk",
        category="default",
        audience="general",
        persona=(
            "Ви пишете для CyberAlertX — сучасного продукту з кібербезпеки "
            "для звичайних користувачів, розробників та ІТ-фахівців. "
            "Тон спокійний, прямий, корисний."
        ),
        style_notes=(
            "Текст має бути легко проглядати. Спочатку — вплив на користувача, "
            "потім — технічна суть. Цитуйте конкретику зі статті."
        ),
    ),
    PromptTemplate(
        id="uk/phishing/normal_users",
        language="uk",
        category="phishing",
        audience="normal_users",
        persona=(
            "Ви пишете попередження про фішинг та шахрайство для пересічних "
            "користувачів. Більшість читачів не мають технічного фону."
        ),
        style_notes=(
            "Зосередьтеся на досвіді користувача: який вигляд має приманка, "
            "де вона з'являється, що хочуть зловмисники."
        ),
    ),
]


class TemplateRegistry:
    """Indexes templates by (language, category, audience) with a fallback chain.

    Lookup order — most specific to least:
      1. exact (lang, cat, aud)
      2. (lang, cat, general)
      3. (lang, default, aud)
      4. (lang, default, general)
      5. (en, default, general)  ← guaranteed by `_TEMPLATES`

    This means: ANY input resolves to a real template; we never raise.
    """

    def __init__(self, templates: Iterable[PromptTemplate] | None = None) -> None:
        seq = list(templates) if templates is not None else list(_TEMPLATES)
        self._templates = seq
        self._by_key: dict[Tuple[str, str, str], PromptTemplate] = {
            (t.language, t.category, t.audience): t for t in seq
        }

    def select(self, language: str, category: str, audience: str) -> PromptTemplate:
        for key in self._fallback_chain(language, category, audience):
            t = self._by_key.get(key)
            if t is not None:
                return t
        # `_TEMPLATES` guarantees ("en", "default", "general"); this is unreachable.
        raise LookupError("No template registered for English default — registry corrupted")

    def all(self) -> list[PromptTemplate]:
        return list(self._templates)

    @staticmethod
    def _fallback_chain(
        language: str, category: str, audience: str,
    ) -> Iterator[Tuple[str, str, str]]:
        yield (language, category, audience)
        yield (language, category, "general")
        yield (language, "default", audience)
        yield (language, "default", "general")
        # Cross-language safety net.
        if language != "en":
            yield ("en", "default", "general")


def default_template_registry() -> TemplateRegistry:
    return TemplateRegistry()


# --------------------------- Render --------------------------------------

def _audience_label(audience: str) -> str:
    return _AUDIENCE_LABELS.get(audience, audience.replace("_", " "))


def render_prompts(
    template: PromptTemplate,
    item: NewsItem,
    *,
    target_language: str,
) -> Tuple[str, str]:
    """Build the (system, user) prompt pair for a single item.

    The system prompt is engineered to be byte-stable for prompt caching —
    nothing per-item leaks into it. Per-item facts live in the user prompt.
    """
    rules = _SHARED_RULES_UK if target_language == "uk" else _SHARED_RULES_EN

    system = (
        f"{template.persona}\n\n"
        f"STYLE NOTES:\n{template.style_notes}"
        + (f"\n\nEXTRA GUIDANCE:\n{template.extra_guidance}" if template.extra_guidance else "")
        + f"\n\n{rules}\n\n"
        + f"TEMPLATE_ID: {template.id}\n"
        + f"OUTPUT_LANGUAGE: {target_language}\n"
        + "SCHEMA: respond with a single JSON object matching the provided ThreatPostResponse schema."
    )

    platforms = ", ".join(item.affected_platforms) or "—"
    audiences = ", ".join(item.audience_targets) or "—"
    user = (
        "SOURCE METADATA\n"
        f"- source: {item.source} (tier: {item.source_tier}, "
        f"credibility: {item.source_credibility_score:.2f})\n"
        f"- published: {item.published_at.isoformat()}\n"
        f"- category: {item.category} (confidence: {item.category_confidence:.2f})\n"
        f"- platforms: {platforms}\n"
        f"- audiences: {audiences}\n"
        f"- actionability: {item.actionability_level} "
        f"({item.actionability_score:.2f})\n"
        f"- threat_score: {item.threat_score:.1f}/100\n"
        f"- detected_language: {item.language}\n"
        f"- target_audience_label: {_audience_label(template.audience)}\n"
        "\nSOURCE ARTICLE\n"
        f"Title: {item.title}\n"
        f"Body:\n{item.raw_content}\n"
        "\nProduce the structured threat post."
    )
    return system, user


__all__ = [
    "PromptTemplate",
    "TemplateRegistry",
    "default_template_registry",
    "render_prompts",
]
