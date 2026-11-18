"""Model-assisted code review: source code is being read function by function,
one function is flagged, and the path from untrusted input to a dangerous
call is traced through it. The subject is the review itself (the editor,
its review rail and the finding), not a picture of "AI".

The example is a generic, textbook pattern (user input reaching a shell
command); it stands for "a flaw found by automated review", not for the
specific bug of any story."""
from __future__ import annotations

import random
from typing import Sequence

from ..brief import EditorialBrief
from .. import type as T
from ..kit import Run, Box, Doc, background, code, icon, pill, vignette, window
from . import scene


@scene("ai_code_audit")
def ai_code_audit(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.25, 0.15))
    kw, tx, cm, st, fn = "#C7B8FF", "#DCD6EE", "#6F6889", "#9EE6C4", "#FFD58A"

    # ---- the editor (hero), cropped by the left edge
    win = Box(-36, 84, 1130, 790)
    body = window(doc, win, title="media/views.py", surface="#120E20", chrome="#1D1733")
    # file tab strip
    doc.rect(body.x, body.y, body.w, 42, "#17122A")
    doc.rect(body.x + 60, body.y, 200, 42, "#120E20")
    doc.rect(body.x + 60, body.y, 200, 2, p.accent)
    doc.text("views.py", body.x + 84, body.y + 27, 16, p.ink, "mono")
    doc.text("storage.py", body.x + 292, body.y + 27, 16, p.muted, "mono")
    doc.text("auth.py", body.x + 432, body.y + 27, 16, p.muted, "mono")

    size, lh = 22, 1.66
    step = size * lh
    lines: list[Sequence[Run] | str] = [
        [("def ", kw), ("list_reports", fn), ("(request):", tx)],
        [("    rows = db.reports.for_user(request.user)", tx)],
        [("    return", kw), (" render(", tx), ('"reports.html"', st), (", rows)", tx)],
        "",
        [("def ", kw), ("thumbnail", fn), ("(request):", tx)],
        [("    src = request.form[", tx), ('"url"', st), ("]", tx)],
        [("    size = request.form.get(", tx), ('"size"', st), (", ", tx), ('"128"', st), (")", tx)],
        [("    cmd = ", tx), ('f"convert {src} -resize {size} t.png"', st)],
        [("    subprocess.run(cmd, shell=", tx), ("True", kw), (")", tx)],
        [("    return", kw), (" send_file(", tx), ('"t.png"', st), (")", tx)],
        "",
        [("def ", kw), ("delete_report", fn), ("(request, rid):", tx)],
        [("    report = db.reports.get(rid, owner=request.user)", tx)],
        [("    report.delete()", tx)],
        [("    return", kw), (" redirect(", tx), ('"/reports"', st), (")", tx)],
    ]
    x0 = body.x + 120
    top = body.y + 96
    code(doc, x0, top, lines, size=size, lh=lh, start=37, width=930,
         marks={i: p.danger for i in range(4, 10)})
    # untouched functions sit back
    for rng_lines in ((0, 3), (11, 15)):
        y_a = top + rng_lines[0] * step - size * 1.05
        doc.rect(body.x + 52, y_a, body.w, (rng_lines[1] - rng_lines[0]) * step, "#120E20", opacity=0.45)

    # ---- the review rail: one verdict per function, in the gutter
    rail_x = body.x + 42
    for i, ok in ((0, True), (4, False), (11, True)):
        cy = top + i * step - size * 0.35
        if ok:
            doc.circle(rail_x, cy, 11, "#1C3A2E")
            icon(doc, "check", rail_x, cy, 15, p.safe, 2.4)
        else:
            doc.circle(rail_x, cy, 13, p.danger)
            icon(doc, "warn", rail_x, cy - 1, 17, "#FFFFFF", 2.2)

    # ---- the traced path: input -> command string -> shell
    def tok_x(line: int, prefix: str) -> float:
        return x0 + T.measure(prefix, size, "mono")

    def tok_y(line: int) -> float:
        return top + line * step - size * 0.35

    hops = [
        (5, tok_x(5, "    src = "), tok_x(5, '    src = request.form["url"]')),
        (7, tok_x(7, '    cmd = f"convert '), tok_x(7, '    cmd = f"convert {src}')),
        (8, tok_x(8, "    "), tok_x(8, "    subprocess.run(cmd, shell=True)")),
    ]
    for ln, a, b in hops:
        y = tok_y(ln) + 14
        doc.path(f"M{a:.1f} {y:.1f}H{b:.1f}", stroke=p.danger, sw=3)
    lane = x0 + 760
    pts = []
    for ln, _, _ in hops:
        row = lines[ln]
        flat = row if isinstance(row, str) else "".join(t for t, _ in row)
        end = x0 + T.measure(flat, size, "mono")
        y = tok_y(ln)
        doc.path(f"M{end + 14:.1f} {y:.1f}H{lane - 18:.1f}", stroke=p.danger, sw=1.6, dash="2 6", opacity=0.8)
        pts.append((lane, y))
    doc.path(f"M{lane:.1f} {pts[0][1]:.1f}V{pts[-1][1]:.1f}", stroke=p.danger, sw=3)
    for i, (px, py) in enumerate(pts):
        doc.circle(px, py, 15, p.danger)
        doc.text(str(i + 1), px, py + 6, 17, "#FFFFFF", "mono_bold", anchor="middle")
    # from the trace to the finding
    doc.path(f"M{lane + 16:.1f} {pts[1][1]:.1f}H1066", stroke=p.danger, sw=2, opacity=0.8)

    # ---- the finding (card that leaves the editor)
    card = Box(1070, 300, 480, 382)
    doc.shadow(card.x, card.y, card.w, card.h, 14, 1.0)
    doc.rect(card.x, card.y, card.w, card.h, "#1E1631", 14, stroke=p.danger, sw=2)
    doc.rect(card.x, card.y, card.w, 56, "#2C1830", 14)
    doc.rect(card.x, card.y + 42, card.w, 14, "#2C1830")
    doc.text("AUTOMATED REVIEW", card.x + 26, card.y + 36, 14, p.danger, "ui_bold", tracking=1.6)
    pill(doc, card.r - 22, card.y + 13, "high", fg="#FFFFFF", bg=p.danger, size=13, font="ui_bold",
         anchor="end")
    doc.text("Command injection", card.x + 26, card.y + 104, 32, p.ink, "display")
    doc.text("thumbnail()  views.py:41", card.x + 26, card.y + 138, 17, p.muted, "mono")
    trace = [("1", 'request.form["url"]', "untrusted input"), ("2", "f\"convert {src} ...\"", "string built"),
             ("3", "subprocess.run(shell=True)", "runs in a shell")]
    for i, (n, what, why) in enumerate(trace):
        y = card.y + 192 + i * 58
        doc.circle(card.x + 40, y, 13, p.danger)
        doc.text(n, card.x + 40, y + 6, 16, "#FFFFFF", "mono_bold", anchor="middle")
        if i < 2:
            doc.line((card.x + 40, y + 15), (card.x + 40, y + 43), p.danger, 2, 0.6)
        doc.text(what, card.x + 68, y + 1, 17, p.ink, "mono")
        doc.text(why, card.x + 68, y + 24, 14, p.muted, "ui")
    doc.text("payload:  url=x.png; id", card.x + 26, card.b - 22, 16, p.accent, "mono")

    vignette(doc, 0.45)
    doc.focus = Box(330, 250, 1220, 686)
