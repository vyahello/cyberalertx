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
from functools import lru_cache
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
    r"exploited (?:as|in) (?:a )?zero[- ]day", r"\bexploited in (?:[\w-]+ ){0,4}attacks\b",
    r"\bexploited to \w+", r"\bleverag(?:ed|ing) (?:[\w-]+ ){0,2}zero[- ]days?\b",
    r"\bunder active use\b", r"\balready (?:being )?used in attacks\b", r"\battacks exploiting\b",
    r"\bamid (?:ongoing |active )?(?:attacks|exploitation)\b",
    r"\b(?:begun|began|started) using (?:a |an |the )?(?:[\w()-]+ ){0,3}exploit\b", r"zero[- ]day (?:attacks?|exploits?) (?:against|targeting)",
    r"known exploited vulnerabilit", r"\bkev\b",
    r"(?:hackers|attackers|threat actors|malicious actors|adversaries|cybercriminals|crooks|apt\w*|"
    r"gangs|operators) (?:are |have been |were )?(?:now |actively |still |also )?exploit(?:ing|ed)?\b",
    # Singular only with tense: "an attacker exploiting this flaw could ..." is
    # advisory boilerplate, "the attacker exploited" / "is exploiting" is an event.
    r"\b(?:hacker|attacker|threat actor|malicious actor|adversary|gang|group) (?:(?:is|has been|was|had been) "
    r"(?:now |actively |still |also )?exploiting|exploited)\b",
    r"\b(?:observed|seen|caught|spotted|began|begun|started) exploiting\b",
    r"\b(?:rapid|ongoing|mass|widespread|observed|confirmed) exploitation of\b",
    r"\bexploited (?:flaws?|bugs?|vulnerabilit\w*|zero-days?|security flaws?)\b",
    r"експлуатуються", r"використовуються в атаках", r"вже використовують в атаках",
    r"активно використовують", r"уже атакують", r"вже атакують",
    r"активно експлуат", r"експлуатують(?:ся)? в атаках", r"використовують в атаках",
    r"вже використовують зловмисники", r"у дикій природі",
)
_ATTACKS_OBSERVED = _rx(
    # "campaign" alone is a topic, not an observation ("a campaign could
    # target users"). It counts with an action verb or an observer.
    r"\bcampaigns? (?:that |which )?(?:has |have |had )?(?:been )?(?:is |are |was |were )?"
    r"(?:target(?:s|ed|ing)|hit|hits|infect(?:s|ed|ing)|compromis(?:es|ed|ing)|deliver(?:s|ed|ing)|"
    r"spread(?:s|ing)?|distribut(?:es|ed|ing)|abus(?:es|ed|ing)|stole|steals|lur(?:es|ed|ing)|"
    r"impersonat\w+|exploit(?:s|ed|ing)|sen[dt]s?|push(?:es|ed|ing))\b",
    r"\b(?:observed|detected|spotted|uncovered|discovered|identified|tracked|tracking|tracks)"
    r"(?: an?| the| new| ongoing| active| large-scale| [\w-]+){0,3} campaigns?\b",
    r"attackers? (?:used|abused|sent|targeted|hijacked|deployed)",
    r"hackers? (?:used|abused|sent|targeted|hijacked|deployed|breached|stole)",
    r"threat actors? (?:used|abused|sent|targeted|deployed)",
    # Present-tense headlines: "Hackers Use ...", "APT Deploys ...", "Lazarus Exploits ...".
    r"\b(?:hackers?|attackers?|threat actors?|cybercriminals|crooks|scammers|operators|apt ?\d*|gang|"
    r"(?:state[- ]sponsored|state[- ]backed|nation[- ]state) (?:hackers|actors|group)) (?:now |also |still )?"
    r"(?:use[sd]?|abus(?:e|es|ed)|deploy(?:s|ed)?|target(?:s|ed)?|hijack(?:s|ed)?|weaponi[sz](?:e|es|ed)|"
    r"spied|spy|push(?:es|ed)?|deliver(?:s|ed)?|plant(?:s|ed)?|compromis(?:e|es|ed)|breach(?:es|ed)?|steal|"
    r"infect(?:s|ed)?|exploit(?:s|ed)?|sign(?:ed)? in|hit)\b",
    # Named actor + verb in a headline. "Exploits"/"Hits"/"Targets" are also
    # nouns ("Public Exploits Released", "UniFi Exploits, ..."), so the verb
    # must take an object and the subject must not be a describing word.
    r"(?-i:\b(?!(?:Public|PoC|New|Multiple|Critical|Recent|Weekly|Top|More|Proof-of-Concept)\b)"
    r"[A-Z][\w-]+(?: [A-Z][\w-]+)? (?:Exploits|Deploys|Targets|Compromises|Hijacks|Breaches|Weaponizes|"
    r"Spies on|Spied on|Infects|Hits|Abuses) (?=[A-Z\d]|(?:an?|the|new|known|critical|unpatched|over|more) ))",
    # A count of victims is an observation: "compromises 600 npm packages".
    r"\b(?:compromis(?:e|es|ed)|hits?|infect(?:s|ed)|breach(?:es|ed)|target(?:s|ed)|hijack(?:s|ed)|backdoor(?:s|ed))"
    r"(?: over| more than| nearly| at least| up to)? [\d,.]+\+?(?: million| thousand)? (?:[\w-]+ ){0,2}"
    r"(?:organi[sz]ations|devices|servers|packages|users|victims|companies|sites|websites|tenants|accounts|"
    r"endpoints|routers|systems|networks|repositories|repos|entities|firms|isps|customers|instances|machines|computers)\b",
    r"\b(?:malware|backdoor|trojan|worm|stealer|infostealer|ransomware|botnet|loader|rat|spyware|"
    # The noun phrase may not contain a conjunction: in "a malicious or
    # compromised host can ..." "compromised" is an adjective, not a verb.
    r"malicious (?:(?!(?:or|and)\b)[\w-]+ ){0,3}(?!(?:or|and)\b)[\w-]+|"
    r"fake (?:(?!(?:or|and)\b)[\w-]+ ){0,4}(?!(?:or|and)\b)[\w-]+) (?:now )?"
    r"(?:spreads?|hits?|infects?|infected|targets?|targeted|compromises|steals?|stole|push(?:es|ed)?|"
    r"deliver(?:s|ed)?|deploy(?:s|ed)?|drops?|abus(?:e|es|ed)|hijack(?:s|ed)?)\b",
    r"\b(?:pushed|delivered|deployed|spread|distributed) (?:in|via|through) (?:an? |the )?(?:[\w-]+ ){0,3}"
    r"(?:campaigns?|attacks?)\b",
    r"ransomware attack", r"\bwas hit by\b", r"\bwere hit by\b",
    r"\b(?:was|were|been|being) attacked\b", r"\battacked for\b", r"\bbr(?:eak|oke|eaking) into\b",
    r"\bin attacks\b",
    r"кампані\w* (?:атаку\w*|атакува\w*|поширю\w*|поширюва\w*|націлен\w*|заража\w*|розсила\w*|використову\w*)",
    r"(?:виявили|зафіксували|помітили|відстежують|відстежили) (?:[\w'’-]+ ){0,3}кампані",
    r"зловмисники (?:використали|розсилали|атакували|атакують)",
    r"атакували", r"атакують", r"заражено", r"заразили",
)
# Single words that report an attack only as part of a statement ("targeted
# phishing could hit ..." is a forecast): the rest of their clause is checked too.
_ATTACKS_OBSERVED_WORDS = _rx(
    r"\bhijack(?:ed|s)?\b", r"\binfected\b", r"\btargeting\b", r"\btargeted\b", r"\bhacked\b",
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
    r"active campaign", r"is spreading", r"\breturn(?:s|ed|ing)?\b", r"\bresurfac\w*", r"\bnew wave\b",
    r"\bresum(?:es|ed|ing)\b", r"\bback online\b", r"\bre-?emerge[ds]?\b", r"\brebuil[td]\b",
    r"відновил\w*",
    r"триває", r"досі активн", r"продовжують атакувати", r"повернул\w*", r"нова хвиля",
)

_CAMPAIGN_COMEBACK = _rx(
    r"\breturn(?:s|ed|ing)?\b", r"\bresurfac\w*", r"\bnew wave\b", r"\bresum(?:es|ed|ing)\b",
    r"\bback online\b", r"\bre-?emerge[ds]?\b", r"\brebuil[td]\b", r"повернул\w*", r"нова хвиля", r"відновил\w*",
)

# --- compromise / exposure --------------------------------------------------------
_COMPROMISE_CONFIRMED = _rx(
    r"\bstole\b", r"\bstolen\b", r"\bsteals?\b", r"\bexfiltrat", r"\bleaked\b", r"\bdrain(?:s|ed|ing)?\b",
    r"\btheft of (?:[\w$.,-]+ ){0,3}(?:data|details|information|records|credentials|funds|assets|crypto\w*)\b",
    r"\b(?:confirm\w*|disclos\w*) (?:a |the )?(?:data|information) theft\b",
    r"(?:data|records|information|details|keys|credentials|tokens|secrets|passwords) (?:was|were) "
    r"(?:exposed|accessed|stolen|compromised|leaked)",
    r"\bdata leaks? (?:at|from|of)\b",
    r"exposed (?:the )?(?:(?:around |about |over |more than |nearly |up to )?[\d,.]+(?: million| thousand| billion)? )?"
    r"(?:[\w-]+ )?(?:data|records|information|personal|customer|user)",
    r"confirm(?:ed|s) (?:a |the )?(?:breach|data breach|unauthori[sz]ed access|that attackers)",
    r"\b(?:vaults?|databases?|files|records|data|emails?|mailboxes) (?:were |was |had been |have been )?"
    r"(?:downloaded|exfiltrated|copied)\b",
    r"gained (?:unauthori[sz]ed )?access to (?:its |their |the |a )?(?:customer|user|personal|internal|student|"
    r"patient|employee|corporate|member)",
    r"вкрали", r"викрали", r"злили", r"витекли", r"отримали доступ до (?:даних|облікових|внутрішніх)",
    r"підтвердил\w* (?:витік|злам|несанкціонований доступ)",
    # "data breach" alone is a topic ("how to prevent a data breach"); it
    # counts when someone suffered, disclosed or confirmed one, or it hit
    # / exposed somebody.
    r"(?:suffer(?:s|ed)?|disclos(?:es|ed)|confirm(?:s|ed)|announc(?:es|ed)|report(?:s|ed)|discover(?:s|ed)|"
    r"detect(?:s|ed)|link(?:s|ed)|attribut(?:es|ed)|blam(?:es|ed)|"
    r"(?:notif(?:y|ies|ied)\w*|alert(?:s|ed)?|warn(?:s|ed)?)(?: [\w-]+){0,3} (?:of|about)|hit by|victim of)"
    r"(?: an?| the| its| their)?(?: [\w-]+){0,2} data breach",
    r"\bdata breach(?:es)? (?:at|of|affect(?:s|ed|ing)|impact(?:s|ed|ing)|hits?|expos(?:es|ed)|leak(?:s|ed))\b",
    r"\bdata breach (?:was |is )?(?:caused by|linked to|traced to|tied to|blamed on)\b",
    r"\bbreach(?:es)? (?:affect(?:s|ed)|impact(?:s|ed)|expos(?:es|ed))\b",
    # Fines, settlements and lawsuits follow a breach that happened.
    r"\bdata breach (?:settlement|lawsuit|class[- ]action|fine|penalty)\b",
    r"\b(?:fine[sd]?|penali[sz]e[sd]?|sued|settle[sd]?)\b[^.]{0,60}\bfor (?:a |an |the |its |their )?(?:[\w-]+ ){0,2}data breach\b",
    r"\b(?:hackers|attackers|threat actors|actors|cybercriminals|a hacking group) (?:have |had )?breached\b",
    r"\bexposing\b", r"\bbreach(?:ed|es)? (?:of |at |into )?(?:its |their |the )?"
    r"(?:internal|production|corporate)? ?(?:systems?|servers?|networks?|tools|infrastructure)\b",
    r"\bintrusion into\b", r"\bstealing\b", r"\$[\d.,]+\s*(?:m|million|b|billion)\b[^.]{0,30}"
    r"\b(?:stolen|drained|traced|lost)\b", r"\bcrypto-draining\b",
    r"викрадено", r"викрадають", r"зламали", r"витік даних", r"злили дані",
    r"\bвкрав\w*", r"\bвикраден(?:і|о|их|ий|а|у)\b", r"(?:отримали|отримав) (?:несанкціонований )?доступ до",
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


# --- assertion check -------------------------------------------------------------
# A pattern hit counts only when its own clause asserts it. Hedged, conditional,
# preventive or capability wording ("could be exploited", "how to prevent a data
# breach", "malware designed to steal") and negation ("did not steal", "no attacks
# were confirmed") in the same clause, before or inside the hit, cancel it. The
# window stops at sentence ends and at contrast/coordination ("..., but attackers
# stole"), so a hedge in one clause never cancels a statement in the next.
_CLAUSE_BREAK = _rx(
    r"[.;!?\n]", r"\bbut\b", r",\s*(?:and|while|whereas|yet|with|which|after|as)\b", r"\bhowever\b", r"\balthough\b",
    r"\bале\b", r"\bпроте\b", r"\bоднак\b", r",\s*(?:а|і|та)\b",
)
_HEDGE = _rx(
    r"\b(?:could|might|would|can|cannot|can't)\b", r"(?-i:\bmay\b)", r"\bpotential(?:ly)?\b",
    r"\bpossibl[ey]\b", r"\bif\b", r"\bunless\b", r"\bwhether\b", r"\brisks?\b",
    r"\bprevent\w*", r"\bavoid\w*", r"\b(?:protect|guard|defend)\w* against\b", r"\bhow to\b",
    r"\bhow (?:organi[sz]ations|companies|businesses|teams|users|you) (?:can|should)\b",
    r"\bhypothetical\w*", r"\btheoretical\w*", r"\bsimulat\w*", r"\blearn\b",
    r"\bдля (?:масового )?(?:викрадення|крадіжки|зламу)\b",
    r"\bможуть\b", r"\bможе\b", r"\bмогли б\b", r"\bміг би\b", r"\bякщо\b", r"\bпотенційн\w*",
    r"\bзапобіг\w*", r"\bуникну\w*", r"\bяк захистит\w*",
)
# Capability, not an event: "flaw lets attackers steal", "malware designed to
# steal". Checked only in the few words right before the hit, so "the bug allows
# RCE, with the flaw actively exploited" still counts.
_CAPABILITY = _rx(
    r"\b(?:lets?|allow(?:s|ing)?|enabl(?:es|ing)?)\b",
    r"\b(?:designed|built|able|intended|aim(?:s|ed)?|tr(?:y|ies|ied)|attempt(?:s|ed)?|capable) (?:to|of)\b",
    r"\bздатн\w*", r"\bпризначен\w* для\b", r"\bдозволя\w*",
)
_NEGATION = _rx(
    r"\b(?:no|not|never|none|nothing|nor|neither|without|denie[sd]|den(?:y|ying))\b", r"n't\b",
    # What follows "rather than" / "instead of" is what did NOT happen.
    r"\brather than\b", r"\binstead of\b", r"\bа не\b", r"\bзамість\b",
    r"\bне\b", r"\bні\b", r"\bбез\b", r"\bнемає\b", r"\bжодн\w*", r"\bзаперечу\w*",
)
# Statistics describe a population, not this event ("exploited vulnerabilities
# rose 20%", "fewer than 10% of flaws are exploited").
_STATISTIC = _rx(
    r"\d+(?:[.,]\d+)?\s?%", r"\bper ?cent\b", r"\b(?:number|share|percentage|proportion|count) of\b",
    r"\b(?:rose|grew|increased|fell|dropped|declined|doubled|tripled|jumped|surged) (?:by|to|from)\b",
    r"\bвідсот\w*", r"\bкількість\b",
)


# Formats that discuss attacks without reporting one: webinars, games, guides.
_NON_EVENT = _rx(
    r"\bwebinars?\b", r"\bctf\b", r"capture[- ]the[- ]flag", r"\bpodcast\b", r"\bplay the\b",
    r"\bвебінар\w*",
)


def _clause(text: str, start: int, end: int) -> tuple[str, str]:
    """(lead-in of the clause up to the hit, the whole sentence)."""
    lead = text[max(0, start - 120):start]
    cuts = list(_CLAUSE_BREAK.finditer(lead))
    if cuts:
        lead = lead[cuts[-1].end():]
    s0 = max(text.rfind(c, 0, start) for c in ".!?\n") + 1
    ends = [i for i in (text.find(c, end) for c in ".!?\n") if i != -1]
    return lead, text[s0:min(ends) if ends else len(text)]


def _asserted(pattern: re.Pattern[str], text: str, *, statistics: bool = False,
              whole_clause: bool = False) -> bool:
    """True when some hit of `pattern` is stated, not hedged/negated (see above)."""
    for m in pattern.finditer(text):
        lead, sentence = _clause(text, m.start(), m.end())
        scope = lead + m.group(0)
        if whole_clause:
            tail = text[m.end():m.end() + 120]
            cut = _CLAUSE_BREAK.search(tail)
            scope += tail[:cut.start()] if cut else tail
        if _HEDGE.search(scope) or _NEGATION.search(scope) or _CAPABILITY.search(lead[-40:] + m.group(0)):
            continue
        if statistics and _STATISTIC.search(sentence):
            continue
        if _NON_EVENT.search(sentence):
            continue
        return True
    return False


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
    """Evidence assessment from the source title, excerpt and byline only.

    Pure in (title, excerpt, byline, category), and every feed request renders
    each item twice (signals + evidence), so results are memoized."""
    return _assess(_source_text(item), (item.category or "other").lower())


@lru_cache(maxsize=8192)
def _assess(text: str, category: str) -> Evidence:
    negated = bool(_NEGATED_EXPLOIT.search(text))
    if _asserted(_CONFIRMED_EXPLOIT, text, statistics=True) and not negated:
        exploitation = "confirmed"
    elif _SUSPECTED.search(text):
        exploitation = "suspected"
    # A plain "vulnerability" story needs explicit exploitation wording; an
    # "exploit"/"zero-day" story that reports attacks is "attacks observed".
    elif category != "vulnerability" and (
            _asserted(_ATTACKS_OBSERVED, text, statistics=True)
            or _asserted(_ATTACKS_OBSERVED_WORDS, text, statistics=True, whole_clause=True)):
        exploitation = "attacks_observed"
    else:
        exploitation = "not_reported"

    campaign = ""
    if category in _CAMPAIGN_CATEGORIES or exploitation == "attacks_observed":
        # A comeback ("returns after a takedown") beats the earlier takedown.
        # "Could return" / "may resume" is a forecast, not a comeback.
        comeback = _asserted(_CAMPAIGN_COMEBACK, text)
        if comeback:
            campaign = "active"
        elif _CAMPAIGN_DECLINED.search(text):
            campaign = "declined"
        elif _CAMPAIGN_DISRUPTED.search(text):
            campaign = "disrupted"
        elif _asserted(_CAMPAIGN_ACTIVE, text):
            campaign = "active"
        else:
            campaign = "unknown"

    compromise = ""
    suspected = bool(_SUSPECTED.search(text))
    undisclosed = bool(_UNDISCLOSED.search(text))
    if _asserted(_COMPROMISE_CONFIRMED, text) and not (suspected and not _strong_breach(text)):
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
    return _asserted(_STRONG_BREACH, text)


_STRONG_BREACH = re.compile(
    r"confirm\w* (?:that )?(?:attackers|hackers|the threat actor)? ?(?:stole|accessed|exfiltrated)|"
    r"(?:data|records) (?:was|were) (?:stolen|exfiltrated|leaked)|"
    r"\$[\d.,]+\s*(?:m|million|b|billion)\b[^.]{0,30}\b(?:stolen|drained|traced)\b|"
    r"crypto-draining", re.IGNORECASE)


__all__ = [
    "CAMPAIGN_LEVELS", "COMPROMISE_LEVELS", "EXPLOITATION_LEVELS", "UNKNOWN_CODES",
    "Evidence", "assess",
]
