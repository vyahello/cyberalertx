"""Shared helpers of the analysis / advisory / fallback scenes (weekly_recap,
vuln_advisory, dossier, mfa_policy, selfhosted_saas, governance, ...).

Not a scene: no @scene here. Product names come from the headline's
capitalised entities, cleaned of headline verbs and adjectives and re-joined
where the source text shows them adjacent ("Red Hat Quay", "Xen Orchestra")."""
from __future__ import annotations

import re

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Doc, f

# Capitalised headline words that are not product or organisation names.
_NOISE = {
    "Including", "Year-Old", "Enabling", "Authenticated", "Unauthenticated", "Adds", "Two", "Three", "Four", "Five",
    "Six", "Seven", "Eight", "Nine", "Ten", "Known", "Exploited", "Vulnerabilities", "Zero-Day", "Zero-Days",
    "Turns", "Security", "Critical", "High", "Read", "Overwrite", "Leak", "Enable", "Execution", "Let", "Execute",
    "Privilege", "Escalation", "Fixes", "Malicious", "Repositories", "During", "Recursive", "November", "October",
    "December", "January", "February", "March", "April", "May", "June", "July", "August", "September", "Tuesday",
    "Expose", "Actively", "Despite", "Auth", "Bypass", "Gain", "Sandbox-Evading", "Python", "Backdoor", "Group",
    "Chat", "Privacy", "Pairing", "CVSS", "Active", "Exploitation", "Empties", "Wallets", "Other", "Catalog",
    "Warns", "Admin", "Access", "Root", "RCE", "Exploit", "Flaw", "Flaws", "Bug", "Bugs", "Target", "Targets",
    "Reverse", "Shells", "Stage", "Revokes", "It", "Previously", "Declared", "Unaffected", "Your", "Endpoint",
    "Management", "Platform", "Be", "Biggest", "Risk", "Rootkits", "Underground", "Actors", "Are", "Taking",
    "Notice", "Beats", "Cyber", "Police", "Compromise", "Deliver", "Wallet-Stealing", "Default", "Helps",
    "Researchers", "Hack", "Who", "Runs", "Q3", "Q4", "Q1", "Q2", "Non-mobile", "Do", "Is", "Can", "Will",
    "Bluetooth", "Image", "Images", "Container", "Private", "All", "Can", "Lets", "Allows", "Allow", "Could",
    "Patched", "Fixed", "Update", "Updates", "Released", "Cumulative", "Multi-Stage", "Benchmark",
}
# Names that report on a product rather than being it.
_REPORTERS = {"CISA", "FBI", "Google", "Claude", "Opus", "Anthropic", "Kaspersky", "Microsoft-owned", "NIST"}


def product_groups(brief: EditorialBrief) -> list[str]:
    """Product / organisation names of the headline, in headline order, with
    adjacent capitalised words joined ("Red Hat Quay")."""
    ents = [e for e in brief.entities if e not in _NOISE and T.supported(e, "display") == e]
    text = brief.text
    groups: list[list[str]] = []
    for e in ents:
        if groups and f"{groups[-1][-1]} {e}".lower() in text:
            groups[-1].append(e)
        else:
            groups.append([e])
    return [" ".join(g) for g in groups]


def primary_product(brief: EditorialBrief) -> tuple[str, list[str]]:
    """(the product the story is about, other named products)."""
    groups = product_groups(brief)
    if not groups:
        return "", []
    ranked = [g for g in groups if g.split()[0] not in _REPORTERS] or groups
    main = ranked[0]
    return main, [g for g in groups if g != main]


def ascii_ids(text: str, limit: int = 3) -> list[str]:
    """Domain-like and product-like ASCII identifiers in the (lower-cased) source
    text, e.g. `robota.ua`, `bee-js`, `ESXi` stays lower-case here."""
    out: list[str] = []
    for m in re.finditer(r"\b[a-z0-9][a-z0-9-]{1,30}\.(?:ua|com|org|net|io|ai|gov|eu)\b", text):
        s = m.group(0)
        if s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def fit_size(s: str, size: float, max_w: float, font: str = "display", min_size: float = 10) -> float:
    """Largest size <= `size` at which `s` fits `max_w`."""
    w = T.measure(T.supported(s, font), size, font)
    if w <= max_w:
        return size
    return max(min_size, size * max_w / max(w, 1))


def grid(doc: Doc, step: int = 40, opacity: float = 0.35, color: str = "") -> None:
    p = doc.pal
    d = "".join(f"M{x} 0V900" for x in range(0, 1601, step)) + "".join(f"M0 {y}H1600" for y in range(0, 901, step))
    doc.path(d, stroke=color or p.line, sw=1, opacity=opacity)


def hatch(doc: Doc, x: float, y: float, w: float, h: float, color: str, gap: float = 12, sw: float = 2,
          opacity: float = 0.5) -> None:
    """45-degree hatching clipped to a rectangle."""
    d = ""
    k = -h
    while k < w:
        d += f"M{f(x + k)} {f(y + h)}L{f(x + k + h)} {f(y)}"
        k += gap
    with doc.g(clip=doc.clip_rect(x, y, w, h)):
        doc.path(d, stroke=color, sw=sw, opacity=opacity, cap="butt")


def stamp(doc: Doc, cx: float, cy: float, label: str, color: str, size: float = 30, angle: float = -8) -> None:
    """A rubber-stamp status mark (double rule, spaced capitals)."""
    w = T.measure(T.supported(label, "ui_bold"), size, "ui_bold", tracking=size * 0.12) + size * 1.2
    h = size * 1.9
    with doc.g(transform=f"rotate({angle} {f(cx)} {f(cy)})", opacity=0.92):
        doc.rect(cx - w / 2, cy - h / 2, w, h, "none", 6, stroke=color, sw=4)
        doc.rect(cx - w / 2 + 7, cy - h / 2 + 7, w - 14, h - 14, "none", 3, stroke=color, sw=1.5)
        doc.text(label, cx, cy + T.cap_height(size, "ui_bold") / 2, size, color, "ui_bold", anchor="middle",
                 tracking=size * 0.12)


def phone(doc: Doc, x: float, y: float, w: float, h: float, *, body: str = "#1B1D22", screen: str = "#FFFFFF",
          depth: float = 1.0) -> tuple[float, float, float, float]:
    """A modern phone in front elevation: aluminium frame, glass, side keys,
    camera island. Returns the screen box (x, y, w, h)."""
    p = doc.pal
    r = w * 0.16
    if depth:
        doc.shadow(x, y, w, h, r, depth)
    # side keys (behind the frame)
    doc.rect(x - 4, y + h * 0.20, 6, h * 0.08, "#3A3D44", 2)
    doc.rect(x - 4, y + h * 0.31, 6, h * 0.08, "#3A3D44", 2)
    doc.rect(x + w - 2, y + h * 0.25, 6, h * 0.12, "#3A3D44", 2)
    doc.rect(x, y, w, h, doc.lin([(0, "#4A4E57", 1), (0.5, "#2A2D33", 1), (1, "#5A5F69", 1)], 0, 0, 1, 0), r)
    doc.rect(x + 3, y + 3, w - 6, h - 6, body, r - 3)
    bz = w * 0.045
    sx, sy, sw_, sh = x + bz, y + bz, w - 2 * bz, h - 2 * bz
    doc.rect(sx, sy, sw_, sh, screen, r - bz)
    # glass sheen
    doc.path(f"M{f(sx)} {f(sy + sh * 0.18)}L{f(sx + sw_ * 0.55)} {f(sy)}H{f(sx + sw_ * 0.85)}"
             f"L{f(sx)} {f(sy + sh * 0.5)}Z", fill="#FFFFFF", opacity=0.07 if p.dark else 0.18)
    # camera island
    doc.rect(sx + sw_ / 2 - w * 0.16, sy + w * 0.05, w * 0.32, w * 0.085, "#0B0C0F", w * 0.045)
    return sx, sy, sw_, sh


def rack_unit(doc: Doc, x: float, y: float, w: float, h: float, *, kind: str = "server", led: str = "#4ADE80",
              face: str = "#2A2F37", rng_bits: int = 0) -> None:
    """One rack-mounted unit in front elevation (server, storage or switch)."""
    doc.rect(x, y, w, h, doc.lin([(0, face, 1), (1, "#1A1E24", 1)]), 3, stroke="#0E1014", sw=1)
    doc.rect(x, y, w, 2, "#FFFFFF", opacity=0.10)
    # rack ears with screws
    for ex in (x + 4, x + w - 18):
        doc.rect(ex, y + 3, 14, h - 6, "#3A404A", 2)
        doc.circle(ex + 7, y + h / 2, 2.6, "#11141A")
    if kind == "switch":
        n = int((w - 120) // 22)
        for i in range(n):
            px = x + 34 + i * 22
            doc.rect(px, y + h / 2 - 7, 16, 13, "#0C0E12", 2)
            doc.rect(px + 5, y + h / 2 - 9, 6, 3, led if (i * 7 + rng_bits) % 5 else "#3A404A", 1)
    elif kind == "storage":
        n = int((w - 90) // 44)
        for i in range(n):
            px = x + 28 + i * 44
            doc.rect(px, y + 5, 38, h - 10, "#20252C", 3, stroke="#0E1014", sw=1)
            doc.rect(px + 5, y + h - 12, 10, 3, led, 1)
    else:
        # vent slots + drive bays + status LEDs
        vx = x + 28
        for i in range(int((w * 0.45) // 9)):
            doc.rect(vx + i * 9, y + 6, 4, h - 12, "#14171C", 1.5)
        bx = x + w * 0.55
        for i in range(3):
            doc.rect(bx + i * (w * 0.1), y + 5, w * 0.085, h - 10, "#20252C", 2, stroke="#0E1014", sw=1)
        doc.circle(x + w - 34, y + h / 2 - 4, 3, led)
        doc.circle(x + w - 34, y + h / 2 + 5, 3, "#3A404A")
