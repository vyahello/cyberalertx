"""SYNTHETIC end-to-end dataset — every name, CVE, product and figure below is
invented for tests (vendors like "Widget", CVE-2026-5xxxx in a reserved test
range we never publish). Nothing here is real-world evidence.

Twelve scenarios required by the Phase 7 validation plan; each item's
`scenario` tag says which one it serves.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)
SYNTHETIC = "[SYNTHETIC TEST DATA]"


@dataclass(frozen=True)
class Spec:
    key: str
    scenario: str
    source: str
    title: str
    body: str
    hours_ago: float
    language: str = "en"


def _b(*sentences: str) -> str:
    return " ".join(sentences) + f" {SYNTHETIC}"


SPECS: tuple[Spec, ...] = (
    Spec("kev_cisa", "1 critical vuln, confirmed exploitation (official)", "CISA Alerts",
         "CISA adds Widget Gateway CVE-2026-50001 to Known Exploited Vulnerabilities catalog",
         _b("CISA added CVE-2026-50001, a critical authentication bypass in Widget Gateway 9.1, to the Known "
            "Exploited Vulnerabilities catalog after confirming active exploitation.",
            "Federal agencies must patch by November 25. Widget released version 9.2 to fix the flaw.",
            "The CVSS score is 9.8 and attackers use it to take over exposed gateways."), 3),
    Spec("kev_bc", "7 second article, same event", "BleepingComputer",
         "Hackers exploit critical Widget Gateway flaw CVE-2026-50001 to hijack devices",
         _b("Attackers are exploiting CVE-2026-50001 in Widget Gateway to bypass authentication and hijack "
            "edge devices, BleepingComputer has learned.",
            "Widget Gateway 9.2 fixes the vulnerability; admins should upgrade immediately.",
            "Researchers counted thousands of exposed gateways online."), 2),
    Spec("newvuln", "2 new vuln, no confirmed exploitation", "SecurityWeek",
         "Acme Router 5.2 patches remote code execution flaw CVE-2026-50002",
         _b("Acme fixed CVE-2026-50002, a remote code execution vulnerability in Acme Router firmware 5.2.",
            "There is no evidence of exploitation in the wild. Firmware 5.3 contains the patch.",
            "The vulnerability affects the web management interface."), 5),
    Spec("ransom", "3 ransomware incident", "BleepingComputer",
         "LockFox ransomware attack shuts down Northwind Hospital systems",
         _b("Northwind Hospital confirmed a LockFox ransomware attack encrypted its patient scheduling systems.",
            "The hospital diverted ambulances while it restores from backups.",
            "The LockFox gang claimed the attack on its leak site."), 6),
    Spec("breach", "4 data breach", "The Hacker News",
         "Contoso Retail data breach exposes 2 million customer records",
         _b("Contoso Retail disclosed a data breach that exposed names, emails and order histories of "
            "2 million customers after attackers accessed a misconfigured database.",
            "Payment card data was not affected, the company said."), 8),
    Spec("phish", "5 phishing campaign", "Krebs on Security",
         "Phishing campaign impersonates Globex Bank with fake security alerts",
         _b("A phishing campaign is sending fake Globex Bank security alerts that lead to a credential "
            "harvesting site.", "The emails use lookalike domains and urge victims to verify their account."), 9),
    Spec("malware", "6 malware report", "The Hacker News",
         "New StealBit infostealer malware spreads through fake browser updates",
         _b("Researchers found StealBit, a new infostealer malware distributed through fake browser update "
            "pages.", "It steals saved passwords, cookies and crypto wallets from infected Windows computers."), 10),
    Spec("ransom_city", "8 similar but unrelated (A)", "SecurityWeek",
         "Ransomware attack disrupts city of Springfield online services",
         _b("The city of Springfield said a ransomware attack disrupted online payment and permit services.",
            "City officials did not name the ransomware group."), 4),
    Spec("ransom_school", "8 similar but unrelated (B)", "The Record",
         "Ransomware attack disrupts Shelbyville school district",
         _b("Shelbyville school district closed for two days after a ransomware attack hit its network.",
            "The district is working with law enforcement."), 4),
    Spec("old_vpn", "9 outdated story (original)", "SecurityWeek",
         "Initech VPN appliance vulnerability CVE-2026-50009 disclosed",
         _b("Initech disclosed CVE-2026-50009, an authentication flaw in Initech VPN appliances, and released "
            "patches.", "No exploitation has been observed."), 24 * 6),
    Spec("new_vpn", "9 significant new development", "BleepingComputer",
         "Initech VPN flaw CVE-2026-50009 now exploited in attacks",
         _b("Attackers are now exploiting CVE-2026-50009 in Initech VPN appliances, Initech warned on Tuesday.",
            "The company urged customers who have not patched to do so immediately."), 1),
    Spec("bakery", "10 irrelevant item", "The Hacker News",
         "Local bakery wins regional award for sourdough bread",
         _b("A family bakery won the regional bread award for its sourdough recipe.",
            "The owners plan to open a second shop next spring."), 2),
    Spec("umbrella_a", "11 conflicting claims (A)", "BleepingComputer",
         "Umbrella Corp hit by data breach, hackers claim 5 million records stolen",
         _b("A hacking group claims it stole 5 million Umbrella Corp customer records and posted samples.",
            "Umbrella Corp is investigating the claim."), 3),
    Spec("umbrella_b", "11 conflicting claims (B)", "SecurityWeek",
         "Umbrella Corp denies data breach claims after hackers post records",
         _b("Umbrella Corp denied that its systems were breached and said the posted Umbrella Corp records "
            "came from an old third-party leak.", "The company found no evidence of intrusion."), 2),
    Spec("grid_claim", "12 low-confidence high-impact", "dev.ua",
         "Hackers claim breach of national power grid operator control systems",
         _b("A hacker group claimed on a forum that it breached the control systems of a national power grid "
            "operator.", "There is no confirmation from the operator or authorities."), 2),
)


def items():
    from cyberalertx.models import NewsItem
    return [NewsItem(title=s.title, source=s.source, url=f"https://synthetic.test/{s.key}",
                     published_at=NOW - timedelta(hours=s.hours_ago), raw_content=s.body, language=s.language)
            for s in SPECS]
