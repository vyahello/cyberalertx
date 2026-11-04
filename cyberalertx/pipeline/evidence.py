"""What the source reporting actually establishes, kept apart from severity.

Severity (`threat_level`) is potential impact. Action priority
(`actionability_level`) is how soon to act. Neither says whether attacks
happened. This module answers the separate evidence questions from the
SOURCE text only (title + feed excerpt, never the generated brief):

  exploitation  confirmed | attacks_observed | suspected | not_reported
  campaign      active | declined | disrupted | unknown | "" (not a campaign story)
  compromise    confirmed | not_confirmed | "" (no incident/exposure angle)
  sponsored     the source marks the piece as sponsored / partner content
  unknowns      codes for gaps the reporting itself leaves open

Rules, in order of importance:
  * Strong labels need explicit wording in the source. "Suspicious activity",
    "investigating", "may have" never become a confirmed compromise, and a
    vendor telling users to change passwords is advice, not evidence.
  * A negated statement ("no evidence of exploitation") never confirms.
  * When the source says nothing, the answer is "not reported"/"unknown",
    not a guess.

Pure functions; the UI localizes the codes (so EN and UA always agree).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models import NewsItem

EXPLOITATION_LEVELS = ("confirmed", "attacks_observed", "suspected", "not_reported")
CAMPAIGN_LEVELS = ("active", "declined", "disrupted", "unknown")
COMPROMISE_LEVELS = ("confirmed", "not_confirmed")
UNKNOWN_CODES = (
    "exposure_unconfirmed",
    "exploitation_unconfirmed",
    "scope_undisclosed",
    "timeline_undisclosed",
    "attribution_unconfirmed",
    "campaign_end_unconfirmed",
)

_CAMPAIGN_CATEGORIES = frozenset({
    "phishing", "malware", "ransomware", "spyware", "scam", "botnet", "social engineering",
})
_VULN_CATEGORIES = frozenset({"vulnerability", "exploit", "zero-day"})
_INCIDENT_CATEGORIES = frozenset({"breach", "data leak", "ransomware", "other"})


def _rx(*parts: str) -> re.Pattern[str]:
    return re.compile("|".join(parts), re.IGNORECASE)


# --- exploitation ---------------------------------------------------------------
_NEGATED_EXPLOIT = _rx(
    r"no (?:evidence|sign|signs|indication|reports?) (?:of|that)[^.]{0,40}(?:exploit|attack)",
    r"(?:not|never) (?:been |yet )?(?:actively )?exploited",
    r"not aware of (?:any )?(?:active )?(?:exploitation|attacks|exploits)",
    r"no (?:known |active )?exploitation",
    r"без ознак експлуатації", r"не (?:виявлено|зафіксовано) (?:ознак )?експлуатаці",
    r"не експлуатув", r"немає (?:даних|ознак) (?:про )?(?:експлуатаці|атак)",
)
_CONFIRMED_EXPLOIT = _rx(
    r"actively exploited", r"exploited in the wild", r"in[- ]the[- ]wild",
    r"under active (?:attack|exploitation)", r"active exploitation",
    # A specific event, not a statistic ("fewer than 10% of flaws are exploited").
    r"(?:was|were|has been|have been|is being|are being) exploited",
    r"exploited (?:as|in) (?:a )?zero[- ]day", r"zero[- ]day (?:attacks?|exploits?) (?:against|targeting)",
    r"known exploited vulnerabilit", r"\bkev\b catalog",
    r"(?:hackers|attackers|threat actors|cybercriminals|crooks|apt\w*) (?:are |have been |were )?(?:now |actively |still )?exploit(?:ing|ed)?\b",
    r"\bexploited (?:flaws?|bugs?|vulnerabilit\w*|zero-days?|security flaws?)\b",
    r"експлуатуються", r"використовуються в атаках", r"вже використовують в атаках",
    r"активно використовують", r"уже атакують", r"вже атакують",
    r"активно експлуат", r"експлуатують(?:ся)? в атаках", r"використовують в атаках",
    r"вже використовують зловмисники", r"у дикій природі",
)
_ATTACKS_OBSERVED = _rx(
    r"\bcampaign\b", r"attackers? (?:used|abused|sent|targeted|hijacked|deployed)",
    r"hackers? (?:used|abused|sent|targeted|hijacked|deployed|breached|stole)",
    r"threat actors? (?:used|abused|sent|targeted|deployed)",
    r"\bhijack(?:ed|s)?\b", r"\binfected\b", r"\btargeting\b", r"\btargeted\b",
    r"ransomware attack", r"\bwas hit by\b", r"\bwere hit by\b",
    r"\b(?:was|were|been|being) attacked\b", r"\battacked for\b", r"\bbr(?:eak|oke|eaking) into\b",
    r"\bhacked\b", r"\bin attacks\b",
    r"кампані", r"зловмисники (?:використали|розсилали|атакували|атакують)",
    r"атакували", r"атакують", r"заражено", r"заразили",
)
_SUSPECTED = _rx(
    r"suspicious activity", r"suspected (?:breach|compromise|intrusion|attack)",
    r"\bmay have been\b", r"\bmight have been\b", r"\bpossibl[ey] (?:breach|compromise|unauthori[sz]ed)",
    r"potentially (?:compromised|exposed|accessed)", r"(?:is|are) investigating",
    r"under investigation", r"investigation is ongoing", r"looking into",
    r"підозріл[уаоі]\w* активн", r"розслідує", r"розслідування триває", r"можлив\w* (?:витік|злам)",
)

# --- campaign status --------------------------------------------------------------
_CAMPAIGN_DECLINED = _rx(
    r"\bdispersed\b", r"appears? to have (?:stopped|ended|declined|subsided|dispersed)",
    r"(?:has|have) (?:since )?(?:stopped|ceased|ended)", r"no longer active",
    r"activity (?:has )?(?:declined|dropped|subsided)", r"looks finished", r"winding down",
    r"активність (?:зменшилась|зменшилася|припинилась|припинилася|вщухла)", r"більше не активн",
)
_CAMPAIGN_DISRUPTED = _rx(
    r"tak(?:en|e|ing) down", r"takedown", r"\bdisrupted\b", r"\bseized\b", r"\bdismantled\b",
    r"sinkholed", r"\barrested\b", r"law enforcement operation",
    r"заблокували (?:домени|інфраструктуру)", r"ліквідували", r"знешкодили", r"затримали",
)
_CAMPAIGN_ACTIVE = _rx(
    r"\bongoing\b", r"still active", r"remains? active", r"continues? to (?:target|spread|send|attack)",
    r"active campaign", r"is spreading", r"\breturns?\b", r"\bresurfac\w*", r"\bnew wave\b",
    r"триває", r"досі активн", r"продовжують атакувати", r"повернул\w*", r"нова хвиля",
)

_CAMPAIGN_COMEBACK = _rx(r"\breturns?\b", r"\bresurfac\w*", r"\bnew wave\b", r"повернул\w*", r"нова хвиля")

# --- compromise / exposure --------------------------------------------------------
_COMPROMISE_CONFIRMED = _rx(
    r"\bstole\b", r"\bstolen\b", r"\bsteal\b", r"\bexfiltrat", r"\bleaked\b", r"\bdrain(?:ed|ing)\b",
    r"(?:data|records|information|details) (?:was|were) (?:exposed|accessed|stolen|compromised|leaked)",
    r"exposed (?:the )?(?:data|records|information|personal|customer|user)",
    r"confirm(?:ed|s) (?:a |the )?(?:breach|data breach|unauthori[sz]ed access|that attackers)",
    r"gained (?:unauthori[sz]ed )?access to (?:customer|user|personal|internal)",
    r"вкрали", r"викрали", r"злили", r"витекли", r"отримали доступ до (?:даних|облікових|внутрішніх)",
    r"підтвердил\w* (?:витік|злам|несанкціонований доступ)",
    r"\bexposing\b", r"\bdata breach\b", r"\bbreach(?:ed|es)? (?:of |at |into )?(?:its |their |the )?"
    r"(?:internal|production|corporate)? ?(?:systems?|servers?|networks?|tools|infrastructure)\b",
    r"\bintrusion into\b", r"\bstealing\b", r"\$[\d.,]+\s*(?:m|million|b|billion)\b[^.]{0,30}"
    r"\b(?:stolen|drained|traced|lost)\b", r"\bcrypto-draining\b",
    r"викрадено", r"викрадають", r"зламали", r"витік даних", r"злили дані",
)
_UNDISCLOSED = _rx(
    r"(?:does|did) not (?:say|disclose|specify|reveal|name|state) (?:what|whether|which|how|if|when|the)",
    r"(?:has|have) not (?:said|disclosed|specified|revealed) (?:what|whether|which|how|if|when)",
    r"(?:it is |it's )?(?:unclear|not clear|unknown) (?:whether|what|how|if|which)",
    r"no details (?:were|have been) (?:shared|released|provided)",
    r"не (?:повідомля|розкрива|уточню|називає|каже)\w* ?(?:,)? (?:чи|що|які|коли|як)",
    r"невідомо, (?:чи|що|які|коли|як)",
)
_TIMELINE_UNDISCLOSED = _rx(
    r"(?:does|did) not (?:say|disclose|specify) when", r"(?:has|have) not (?:said|disclosed) when",
    r"unclear when", r"не (?:повідомля|уточню)\w* ?,? коли", r"невідомо, коли",
)
_ATTRIBUTION_UNCONFIRMED = _rx(
    r"not (?:yet )?(?:been )?attributed", r"unknown (?:threat )?actors?", r"unidentified (?:threat )?actors?",
    r"no group has (?:claimed|been named)", r"has not been attributed",
    r"невстановлен\w* (?:угруповання|зловмисник)", r"не приписали",
)
_SPONSORED = _rx(
    r"sponsored (?:and written )?by\b", r"\bsponsored content\b", r"\bpartner content\b",
    r"\bpaid (?:post|content)\b", r"\badvertorial\b",
)
_SPONSOR_NAME = re.compile(r"sponsored (?:and written )?by\s+([A-Z][\w&.\- ]{1,60}?)(?:[.,;]|$)", re.IGNORECASE)


@dataclass(frozen=True)
class Evidence:
    exploitation: str = "not_reported"
    campaign: str = ""
    compromise: str = ""
    sponsored: bool = False
    sponsor: str = ""
    unknowns: tuple[str, ...] = field(default_factory=tuple)

    @property
    def exploitation_confirmed(self) -> bool:
        return self.exploitation == "confirmed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "exploitation": self.exploitation,
            "campaign": self.campaign,
            "compromise": self.compromise,
            "sponsored": self.sponsored,
            "sponsor": self.sponsor,
            "unknowns": list(self.unknowns),
        }


def _source_text(item: NewsItem) -> str:
    byline = getattr(item, "byline", "") or ""
    return f"{item.title}\n{item.raw_content}\n{byline}"


def assess(item: NewsItem) -> Evidence:
    """Evidence assessment from the source title, excerpt and byline only."""
    text = _source_text(item)
    category = (item.category or "other").lower()

    negated = bool(_NEGATED_EXPLOIT.search(text))
    if _CONFIRMED_EXPLOIT.search(text) and not negated:
        exploitation = "confirmed"
    elif _SUSPECTED.search(text):
        exploitation = "suspected"
    # A plain "vulnerability" story needs explicit exploitation wording; an
    # "exploit"/"zero-day" story that reports attacks is "attacks observed".
    elif _ATTACKS_OBSERVED.search(text) and category != "vulnerability":
        exploitation = "attacks_observed"
    else:
        exploitation = "not_reported"

    campaign = ""
    if category in _CAMPAIGN_CATEGORIES or exploitation == "attacks_observed":
        # A comeback ("returns after a takedown") beats the earlier takedown.
        if _CAMPAIGN_ACTIVE.search(text) and _CAMPAIGN_COMEBACK.search(text):
            campaign = "active"
        elif _CAMPAIGN_DECLINED.search(text):
            campaign = "declined"
        elif _CAMPAIGN_DISRUPTED.search(text):
            campaign = "disrupted"
        elif _CAMPAIGN_ACTIVE.search(text):
            campaign = "active"
        else:
            campaign = "unknown"

    compromise = ""
    suspected = bool(_SUSPECTED.search(text))
    undisclosed = bool(_UNDISCLOSED.search(text))
    if _COMPROMISE_CONFIRMED.search(text) and not (suspected and not _strong_breach(text)):
        compromise = "confirmed"
    elif suspected or (undisclosed and category in _INCIDENT_CATEGORIES):
        compromise = "not_confirmed"

    unknowns: list[str] = []
    if compromise == "not_confirmed":
        unknowns.append("exposure_unconfirmed")
    if category in _VULN_CATEGORIES and exploitation == "not_reported" and not negated:
        unknowns.append("exploitation_unconfirmed")
    if undisclosed and compromise != "confirmed":
        unknowns.append("scope_undisclosed")
    if _TIMELINE_UNDISCLOSED.search(text):
        unknowns.append("timeline_undisclosed")
    if _ATTRIBUTION_UNCONFIRMED.search(text):
        unknowns.append("attribution_unconfirmed")
    if campaign in ("declined", "disrupted"):
        unknowns.append("campaign_end_unconfirmed")

    sponsored = bool(_SPONSORED.search(text))
    sponsor = ""
    if sponsored:
        m = _SPONSOR_NAME.search(text)
        sponsor = m.group(1).strip() if m else ""

    return Evidence(exploitation=exploitation, campaign=campaign, compromise=compromise,
                    sponsored=sponsored, sponsor=sponsor, unknowns=tuple(dict.fromkeys(unknowns)))


def _strong_breach(text: str) -> bool:
    """Exposure stated outright even though the story also mentions an
    investigation ("confirmed that attackers stole ..." + "investigating")."""
    return bool(re.search(r"confirm\w* (?:that )?(?:attackers|hackers|the threat actor)? ?(?:stole|accessed|exfiltrated)|"
                          r"(?:data|records) (?:was|were) (?:stolen|exfiltrated|leaked)|"
                          r"\$[\d.,]+\s*(?:m|million|b|billion)\b[^.]{0,30}\b(?:stolen|drained|traced)\b|"
                          r"crypto-draining", text, re.IGNORECASE))


__all__ = [
    "CAMPAIGN_LEVELS", "COMPROMISE_LEVELS", "EXPLOITATION_LEVELS", "UNKNOWN_CODES",
    "Evidence", "assess",
]
