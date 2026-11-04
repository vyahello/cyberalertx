"""Source reliability for the intelligence layer.

`pipeline.credibility` already gives every source one number (its
`base_score`, hand-curated) and a tier. That number blends several things an
analyst would keep apart, so this module describes each source on five
explicit axes and derives reliability from them:

    primary        0..1  how much of its output is first-hand: the advisory
                         itself, the vendor's own disclosure, original
                         research — versus rewriting someone else's report
    official       0/1   a government body, CERT or the affected vendor
                         speaking about its own product
    technical      0..1  how often it carries technical evidence: CVE ids,
                         affected versions, IOCs, exploitation details
    methodology    0..1  how transparent it is about how it knows
    historical     0..1  track record. Seeded from
                         `pipeline.credibility.SOURCE_PROFILES[...].base_score`

    reliability = 0.40*historical + 0.20*primary + 0.15*official
                + 0.15*technical + 0.10*methodology

The axis values below are editorial judgements, recorded here so they can be
argued with. Override any of them without touching code in
`data/intel/sources.json`:

    {"BleepingComputer": {"primary": 0.6}, "New Feed": {"kind": "specialist_media",
     "historical": 0.5}}

Reliability is a property of a SOURCE. How many sources reported a story is a
property of the STORY and is handled with syndication collapsed
(`evidence.independent_sources`) — five outlets repeating one report add
nothing here.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Mapping

from ..pipeline.credibility import DEFAULT_PROFILE, SOURCE_PROFILES

logger = logging.getLogger(__name__)

#: Axis weights of the reliability formula. Sum to 1.0.
RELIABILITY_WEIGHTS: Mapping[str, float] = {
    "historical": 0.40,
    "primary": 0.20,
    "official": 0.15,
    "technical": 0.15,
    "methodology": 0.10,
}

KINDS = (
    "government_cert",     # CISA, NCSC, CERT-UA: official advisories
    "vendor",              # the affected vendor's own advisory / blog
    "research",            # vendor threat-research teams publishing original work
    "specialist_media",    # cybersecurity newsrooms
    "general_media",       # tech / business outlets, cyber is one beat of many
    "unknown",
)


@dataclass(frozen=True)
class SourceReliability:
    name: str
    kind: str
    primary: float
    official: float
    technical: float
    methodology: float
    historical: float
    note: str = ""

    @property
    def reliability(self) -> float:
        total = sum(RELIABILITY_WEIGHTS[k] * float(getattr(self, k)) for k in RELIABILITY_WEIGHTS)
        return round(max(0.0, min(1.0, total)), 3)

    @property
    def is_official(self) -> bool:
        return self.official >= 0.5

    @property
    def is_primary(self) -> bool:
        return self.primary >= 0.75

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["reliability"] = self.reliability
        return out


def _hist(name: str) -> float:
    return float(SOURCE_PROFILES.get(name, DEFAULT_PROFILE).base_score)


def _p(name: str, kind: str, primary: float, official: float, technical: float,
       methodology: float, note: str = "") -> SourceReliability:
    return SourceReliability(name, kind, primary, official, technical, methodology,
                             _hist(name), note)


#: Code defaults. `historical` always comes from the credibility registry.
DEFAULT_SOURCES: Mapping[str, SourceReliability] = {p.name: p for p in (
    _p("CISA Alerts", "government_cert", 1.0, 1.0, 0.9, 0.9,
       "Federal advisories and the KEV catalog; ICS advisories republish vendor CSAF."),
    _p("CISA Advisories", "government_cert", 1.0, 1.0, 0.9, 0.9),
    _p("US-CERT", "government_cert", 1.0, 1.0, 0.9, 0.9),
    _p("NCSC", "government_cert", 1.0, 1.0, 0.8, 0.9),
    _p("Microsoft Security", "vendor", 1.0, 1.0, 0.9, 0.8,
       "Official for Microsoft products; research otherwise."),
    _p("Mandiant", "research", 1.0, 0.0, 0.9, 0.8),
    _p("Securelist (Kaspersky)", "research", 1.0, 0.0, 0.9, 0.8, "Original threat research."),
    _p("Krebs on Security", "specialist_media", 0.8, 0.0, 0.6, 0.8, "Original investigative reporting."),
    _p("BleepingComputer", "specialist_media", 0.5, 0.0, 0.7, 0.6,
       "Mix of original reporting and vendor-advisory coverage."),
    _p("The Hacker News", "specialist_media", 0.3, 0.0, 0.6, 0.5,
       "Mostly rewrites of vendor and research publications."),
    _p("DarkReading", "specialist_media", 0.4, 0.0, 0.5, 0.5),
    _p("SecurityWeek", "specialist_media", 0.4, 0.0, 0.6, 0.5),
    _p("InfoSecurity Magazine", "specialist_media", 0.2, 0.0, 0.4, 0.4),
    _p("SC Media", "specialist_media", 0.2, 0.0, 0.4, 0.4),
    _p("Threatpost", "specialist_media", 0.3, 0.0, 0.5, 0.4),
    _p("itc.ua", "general_media", 0.2, 0.0, 0.3, 0.4),
    _p("ain.ua", "general_media", 0.3, 0.0, 0.3, 0.4),
    _p("dev.ua", "general_media", 0.2, 0.0, 0.3, 0.4),
    _p("dou.ua", "general_media", 0.3, 0.0, 0.4, 0.4),
)}

# Defaults for a source nobody has profiled yet: treated as secondary,
# non-official, with little technical evidence until an editor says otherwise.
_UNKNOWN_KIND = "unknown"
_UNKNOWN_AXES: Mapping[str, float] = {"primary": 0.0, "official": 0.0, "technical": 0.2,
                                      "methodology": 0.2}


class SourceTable:
    """Name → `SourceReliability`, with defaults for unprofiled names."""

    def __init__(self, overrides: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self._table: dict[str, SourceReliability] = dict(DEFAULT_SOURCES)
        for name, values in (overrides or {}).items():
            if not isinstance(values, Mapping):
                continue
            base = self._table.get(name) or self._unknown(name)
            allowed = {f.name for f in fields(SourceReliability)} - {"name"}
            changes: dict[str, Any] = {}
            for key, value in values.items():
                if key not in allowed:
                    continue
                changes[key] = str(value) if key in ("kind", "note") else float(value)
            self._table[name] = replace(base, **changes)

    @staticmethod
    def _unknown(name: str) -> SourceReliability:
        return SourceReliability(name=name, historical=_hist(name), note="not profiled",
                                 kind=_UNKNOWN_KIND,
                                 primary=_UNKNOWN_AXES["primary"],
                                 official=_UNKNOWN_AXES["official"],
                                 technical=_UNKNOWN_AXES["technical"],
                                 methodology=_UNKNOWN_AXES["methodology"])

    def get(self, name: str) -> SourceReliability:
        return self._table.get(name) or self._unknown(name)

    def reliability(self, name: str) -> float:
        return self.get(name).reliability

    def fingerprint(self) -> dict[str, float]:
        """What scoring depends on, for the input hash."""
        return {n: p.reliability for n, p in sorted(self._table.items())}

    def all(self) -> list[SourceReliability]:
        return [self._table[n] for n in sorted(self._table)]

    @classmethod
    def load(cls, path: Path | None) -> "SourceTable":
        if path is None or not Path(path).exists():
            return cls()
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("root must be an object")
            return cls(data)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("intel sources %s unreadable (%s) — using defaults", path, exc)
            return cls()


__all__ = ["DEFAULT_SOURCES", "KINDS", "RELIABILITY_WEIGHTS", "SourceReliability", "SourceTable"]
