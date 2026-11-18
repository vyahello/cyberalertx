"""GitHub Actions pinning: a workflow file whose pinned commit is not the
official one. The mechanism is the subject: a `uses:` line that looks right
(pinned SHA, version comment) resolves to a look-alike commit outside the
action's official history."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from .. import type as T
from ..kit import Box, Doc, arrow, background, code, icon, pill, vignette, window
from . import scene


def _paper_grid(doc: Doc, step: int = 40) -> None:
    p = doc.pal
    d = "".join(f"M{x} 0V900" for x in range(0, 1601, step)) + "".join(f"M0 {y}H1600" for y in range(0, 901, step))
    doc.path(d, stroke=p.line, sw=1, opacity=0.35)


def _sha(rng: random.Random, n: int = 40) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(n))


@scene("ci_pinning")
def ci_pinning(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.35, 0.2))
    _paper_grid(doc)

    bad_sha, good_sha = _sha(rng), _sha(rng)
    key, val, s_col, com = p.on_surface, "#3D4452", p.accent, p.muted

    # ---- the workflow file (hero), cropped by the left edge like a magazine spread
    win = Box(-40, 110, 1050, 660)
    body = window(doc, win, title=".github/workflows/release.yml", surface="#FFFFFF", chrome="#F1ECE3")
    lines = [
        [("name", key), (": release", val)],
        [("on", key), (":", val)],
        [("  push", key), (": { tags: [", val), ('"v*"', s_col), ("] }", val)],
        [("jobs", key), (":", val)],
        [("  build", key), (":", val)],
        [("    runs-on", key), (": ubuntu-latest", val)],
        [("    steps", key), (":", val)],
        [("      - uses", key), (": actions/checkout@", val), (bad_sha[:12], p.danger), ("…", p.danger),
         ("  # v4.2.2", com)],
        [("      - uses", key), (": actions/setup-node@", val), (good_sha[:12], p.safe), ("…", p.safe),
         ("  # v4.0.4", com)],
        [("      - run", key), (": npm ci && npm test", val)],
        [("      - run", key), (": ./scripts/publish.sh", val)],
    ]
    size = 24.5
    top = body.y + 64
    lh = size * 1.62
    code(doc, body.x + 112, top, lines, size=size, lh=1.62, marks={7: p.danger}, width=900)
    pin_y = top + 7 * lh - size * 0.35
    pin_x_end = body.x + 112 + T.measure("".join(t for t, _ in lines[7]), size, "mono")

    # ---- the commit history of the action (right): official line vs look-alike commit
    gx, g_top, g_bot = 1395, 150, 770
    doc.text("actions/checkout", gx - 10, 118, 20, p.ink, "mono_bold", anchor="middle")
    doc.line((gx, g_top), (gx, g_bot), p.ink, 4)
    tags = {1: "v4.2.0", 3: "v4.2.1", 5: "v4.2.2"}
    ys = [g_top + 40 + i * 100 for i in range(6)]
    for i, y in enumerate(ys):
        doc.circle(gx, y, 13, p.surface, p.ink, 4)
        doc.text(_sha(rng, 7), gx - 26, y + 6, 15, p.muted, "mono", anchor="end")
        if i in tags:
            pill(doc, gx + 26, y - 14, tags[i], fg=p.surface, bg=p.ink, size=14)
    official = ys[5]
    icon(doc, "check", gx + 132, official + 1, 26, p.safe, 3)

    # The look-alike: same name and version label, not on the official line.
    lx, ly = 1180, 555
    doc.path(f"M{gx} {ys[2]}C{gx - 120} {ys[2] + 40} {lx + 20} {ly - 120} {lx} {ly - 16}", stroke=p.danger, sw=3,
             dash="2 9", opacity=0.9)
    doc.circle(lx, ly, 30, p.danger, opacity=0.15)
    doc.circle(lx, ly, 16, p.surface, p.danger, 5)
    doc.circle(lx, ly, 5, p.danger)
    doc.text(bad_sha[:7], lx, ly + 52, 17, p.danger, "mono_bold", anchor="middle")
    pill(doc, lx, ly + 66, "unverified", fg=p.danger, bg="#FBE3DF", size=14, anchor="middle")

    # What the comment promises vs what the SHA resolves to.
    arrow(doc, [(pin_x_end + 22, pin_y), (1085, pin_y + 6), (lx - 36, ly - 10)], p.danger, sw=4.5, head=20)

    vignette(doc, 0.35)
    doc.focus = Box(430, 200, 960, 540)          # the pinned line, the arrow and the impostor commit
