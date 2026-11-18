"""Criminal (or civil) cases against alleged cybercriminals: the case file is
the subject. An open manila folder holds the docket sheet, whose one legible
entry is the step the story reports (plea, acquittal, extradition, sentence),
with the court's stamp across it. Beside it lies the case's exhibit, chosen
from the sources: a contact sheet of leaked video frames, a print-out of
blockchain blocks, the maximum-sentence scale, or a gavel when the story names
nothing more specific.

No seal, no jurisdiction, no names; case numbers are masked."""
from __future__ import annotations

import random
import re

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, f, icon, pill
from . import scene

_PAPER = "#FBF8F0"
_MANILA = ("#E7C989", "#D8B26A", "#C49A52")


def _fact(brief: EditorialBrief, key: str) -> str:
    v = brief.facts.get(key)
    if not v:
        return ""
    if brief.facts.get(key + "_approx"):
        return f"~{v}"
    if brief.facts.get(key + "_plus"):
        return f"{v}+"
    return str(v)


def _verdict(text: str) -> tuple[str, str, str]:
    """(stamp word, docket entry, tone) for the step the story reports."""
    t = text
    if re.search(r"acquit|\bclears?\b|cleared|not guilty|виправда", t):
        return "ACQUITTED", "JUDGMENT OF ACQUITTAL entered", "safe"
    if re.search(r"extradit|екстрадиц", t):
        return "EXTRADITED", "DEFENDANT EXTRADITED - in custody", "danger"
    if re.search(r"plead\w* guilty|pleads guilty|guilty plea|визнав провину|admits", t):
        return "GUILTY PLEA", "PLEA OF GUILTY entered", "danger"
    if re.search(r"sentenced|вирок|засуджен", t):
        return "SENTENCED", "JUDGMENT AND SENTENCE entered", "danger"
    if re.search(r"convicted|found guilty", t):
        return "CONVICTED", "VERDICT: GUILTY on all counts", "danger"
    if re.search(r"lawsuit|\bsues?\b|sued|подав до суду|позов", t):
        return "FILED", "COMPLAINT filed - civil action", "accent"
    if re.search(r"indict|charged|charges", t):
        return "INDICTED", "INDICTMENT unsealed", "danger"
    if re.search(r"arrest|арешт|затрима", t):
        return "ARRESTED", "DEFENDANT ARRESTED - initial appearance", "danger"
    return "FILED", "CASE OPENED", "accent"


# ---------------------------------------------------------------- paper props

def _binder_clip(doc: Doc, cx: float, y: float, w: float = 96) -> None:
    """A black binder clip seen from above, gripping the top edge of a stack."""
    doc.rect(cx - w / 2 + 4, y + 8, w, 46, "#000", 6, opacity=0.18, extra=f' filter="{doc.blur(5)}"')
    doc.path(f"M{f(cx - w / 2)} {f(y)}H{f(cx + w / 2)}L{f(cx + w / 2 - 6)} {f(y + 44)}"
             f"H{f(cx - w / 2 + 6)}Z", fill=doc.lin([(0, "#3A3F49", 1), (0.5, "#1C2028", 1), (1, "#0E1116", 1)]))
    doc.rect(cx - w / 2 + 6, y + 3, w - 12, 4, "#FFFFFF", 2, opacity=0.18)
    # wire handles folded back over the clip
    # wire handles folded back over the clip (two narrow loops)
    for s_ in (-1, 1):
        x0, x1 = cx + s_ * (w / 2 - 14), cx + s_ * (w / 2 - 30)
        top = y - 40
        d = (f"M{f(x0)} {f(y + 6)}L{f(x0 + s_ * 4)} {f(top + 6)}Q{f(x0 + s_ * 4)} {f(top)} {f((x0 + x1) / 2)} "
             f"{f(top)}Q{f(x1 - s_ * 4)} {f(top)} {f(x1 - s_ * 4)} {f(top + 6)}L{f(x1)} {f(y + 6)}")
        doc.path(d, stroke="#000", sw=5, opacity=0.15, extra=f' transform="translate(3 5)"')
        doc.path(d, stroke="#8E959F", sw=4.5)
        doc.path(d, stroke="#F2F4F6", sw=1.6, opacity=0.8)


def _stamp(doc: Doc, cx: float, cy: float, word: str, color: str, rot: float, size: float = 50,
           sub: str = "") -> None:
    """Rubber-stamp impression: double rule, uneven ink."""
    w = T.measure(word, size, "display", 3) + 64
    h = size * 1.65 + (24 if sub else 0)
    with doc.g(f"rotate({f(rot)} {f(cx)} {f(cy)})", opacity=0.86):
        doc.rect(cx - w / 2, cy - h / 2, w, h, "none", 8, stroke=color, sw=5)
        doc.rect(cx - w / 2 + 9, cy - h / 2 + 9, w - 18, h - 18, "none", 4, stroke=color, sw=2)
        doc.text(word, cx, cy + size * 0.36 - (10 if sub else 0), size, color, "display", anchor="middle",
                 tracking=3)
        if sub:
            doc.text(sub, cx, cy + h / 2 - 20, 15, color, "mono_bold", anchor="middle", tracking=2)
    # ink starvation: a few paper-coloured flecks over the impression
    rng = random.Random(word)
    for _ in range(26):
        doc.circle(cx + rng.uniform(-w / 2, w / 2), cy + rng.uniform(-h / 2, h / 2) * 0.8,
                   rng.uniform(1.2, 3.4), _PAPER, opacity=0.75)


def _folder(doc: Doc, x: float, y: float, w: float, h: float, case_no: str) -> None:
    """An open manila case folder (back cover with tab), lying flat."""
    p = doc.pal
    doc.shadow(x, y, w, h, 6, 1.0)
    tab_x, tab_w = x + w - 330, 280
    doc.path(f"M{f(tab_x)} {f(y + 2)}L{f(tab_x + 18)} {f(y - 40)}H{f(tab_x + tab_w - 18)}"
             f"L{f(tab_x + tab_w)} {f(y + 2)}Z", fill=_MANILA[1])
    doc.rect(x, y, w, h, doc.lin([(0, _MANILA[0], 1), (1, _MANILA[1], 1)], 0, 0, 0.4, 1), 6)
    # tab label
    doc.rect(tab_x + 26, y - 32, tab_w - 52, 26, "#FFFDF6", 3)
    doc.text(case_no, tab_x + tab_w / 2, y - 13, 15, p.ink, "mono_bold", anchor="middle")
    # crease and the edge of the front cover folded underneath
    doc.rect(x - 14, y + 10, 18, h - 4, _MANILA[2], 4)
    doc.line((x + 3, y + 4), (x + 3, y + h - 4), "#000", 1.5, opacity=0.12)


def _docket(doc: Doc, x: float, y: float, w: float, h: float, entry: str, rng: random.Random,
            tone: str, case_no: str, pending: str = "") -> tuple[float, float]:
    """Docket sheet. Every entry is texture except the one the story reports.
    Returns the centre of the highlighted entry."""
    p = doc.pal
    # the pages underneath
    for i, (dx, dy) in enumerate(((10, 8), (5, 4))):
        doc.rect(x + dx, y + dy, w, h, "#F3EEE2" if i == 0 else "#F7F3EA", 2, stroke="#D9CFBC", sw=1)
    doc.rect(x, y, w, h, _PAPER, 2, stroke="#D6CCB8", sw=1)
    doc.text("CIVIL DOCKET" if tone == "accent" else "CRIMINAL DOCKET", x + 44, y + 78, 30, p.ink, "display",
             tracking=2)
    doc.text(f"CASE No. {case_no}", x + w - 44, y + 76, 16, p.muted, "mono", anchor="end")
    doc.line((x + 44, y + 98), (x + w - 44, y + 98), p.ink, 2.5)
    doc.text("DEFENDANT", x + 44, y + 130, 14, p.muted, "ui_bold", tracking=1.5)
    doc.text("[name withheld]", x + 150, y + 131, 18, p.ink, "mono")
    # table head
    ty = y + 172
    doc.rect(x + 44, ty - 24, w - 88, 34, "#EFE6D4", 2)
    for lab, cx in (("#", x + 64), ("FILED", x + 108), ("DOCKET TEXT", x + 240)):
        doc.text(lab, cx, ty - 1, 14, p.muted, "ui_bold", tracking=1.5)
    rows = 9
    hi = 6
    rh = (h - (ty - y) - 50) / rows
    hit = (0.0, 0.0)
    for i in range(rows):
        ry = ty + 22 + i * rh
        if i == hi:
            col = p.safe if tone == "safe" else p.danger if tone == "danger" else p.accent
            doc.rect(x + 36, ry - 6, w - 72, rh - 6, col, 2, opacity=0.12)
            doc.rect(x + 36, ry - 6, 5, rh - 6, col)
            doc.text(str(i + 1), x + 64, ry + rh * 0.42, 16, p.ink, "mono_bold")
            doc.text("--/--", x + 108, ry + rh * 0.42, 16, p.ink, "mono")
            doc.text(T.fit(entry, 19, w - 300, "mono_bold"), x + 240, ry + rh * 0.42, 19, col, "mono_bold")
            hit = (x + w - 60, ry + rh * 0.3)
            continue
        if i > hi + 1:
            continue                            # the sheet ends after the next (pending) entry
        doc.text(str(i + 1), x + 64, ry + rh * 0.42, 15, p.muted, "mono")
        if i == hi + 1 and pending:
            doc.text("--/--", x + 108, ry + rh * 0.42, 16, p.muted, "mono")
            doc.text(pending, x + 240, ry + rh * 0.42, 18, p.muted, "mono")
            continue
        doc.rect(x + 108, ry + rh * 0.42 - 11, 62, 11, "#CFC5B1", 3)
        segs = rng.randint(2, 4)
        cx = x + 240
        for s in range(segs):
            sw_ = rng.uniform(60, 170)
            if cx + sw_ > x + w - 60:
                break
            doc.rect(cx, ry + rh * 0.42 - 11, sw_, 11, "#D8CFBD" if i != hi + 1 else "#E3DBCB", 3)
            cx += sw_ + 12
        if i < 3:
            doc.rect(x + 240, ry + rh * 0.42 + 8, rng.uniform(120, 260), 8, "#E3DBCB", 3)
    return hit


# ---------------------------------------------------------------- exhibits

def _exhibit_card(doc: Doc, x: float, y: float, w: float, h: float, label: str, rot: float) -> None:
    p = doc.pal
    doc.add(f'<g transform="rotate({f(rot)} {f(x + w / 2)} {f(y + h / 2)})">')
    doc.shadow(x, y, w, h, 4, 0.8)
    doc.rect(x, y, w, h, "#FFFEFA", 3, stroke="#D6CCB8", sw=1)
    # evidence label, top-left
    doc.rect(x + 26, y + 22, 150, 30, "#F6E7B8", 2, stroke="#C9B37A", sw=1)
    doc.text(label, x + 101, y + 43, 15, p.ink, "mono_bold", anchor="middle", tracking=1.5)
    doc.add("</g>")


def _contact_sheet(doc: Doc, x: float, y: float, rng: random.Random, n: int) -> tuple[float, float, float, float]:
    """Leaked video frames, printed as a contact sheet: soft generic frames, never game art.
    Draws `n` frames (capped to the grid) and returns the grid box."""
    cols, rows = 10, 9
    fw, fh, gap = 40, 23, 6
    total = min(n, cols * rows) if n else cols * rows
    gw, gh = cols * (fw + gap) - gap, rows * (fh + gap) - gap
    doc.rect(x - 10, y - 10, gw + 20, gh + 20, "#16181D", 3)
    hues = ("#3C5A7A", "#7A5A3C", "#5A7A62", "#6B4E78", "#2E4F63", "#8A6A48", "#4C6070")
    sky = []
    for i in range(total):
        r, c = divmod(i, cols)
        fx, fy = x + c * (fw + gap), y + r * (fh + gap)
        a, b = rng.choice(hues), rng.choice(hues)
        sky.append(f'<rect x="{f(fx)}" y="{f(fy)}" width="{fw}" height="{fh}" fill="{a}"/>'
                   f'<rect x="{f(fx)}" y="{f(fy + fh * rng.uniform(0.45, 0.7))}" width="{fw}" '
                   f'height="{f(fh * 0.4)}" fill="{b}" opacity="0.9"/>'
                   f'<circle cx="{f(fx + rng.uniform(8, 32))}" cy="{f(fy + rng.uniform(6, 12))}" r="4" '
                   f'fill="#F3D9A4" opacity="0.6"/>')
    doc.add(f'<g filter="{doc.blur(1.6)}">{"".join(sky)}</g>')
    for i in range(total):
        r, c = divmod(i, cols)
        fx, fy = x + c * (fw + gap), y + r * (fh + gap)
        doc.path(f"M{f(fx + 16)} {f(fy + 7)}v9l8-4.5z", fill="#FFFFFF", opacity=0.7)
    # sprocket holes along both edges, like a printed film strip
    for k in range(rows * 2):
        sy = y - 4 + k * (gh + 8) / (rows * 2)
        doc.rect(x - 8, sy, 5, 7, "#3A3D44", 1)
        doc.rect(x + gw + 3, sy, 5, 7, "#3A3D44", 1)
    return x, y, gw, gh


def _blocks(doc: Doc, x: float, y: float, rng: random.Random, money: str, highlight: str,
            caption: str = "in crypto") -> None:
    """Exhibit print-out: a run of chained blocks, one transaction circled."""
    p = doc.pal
    bw, bh, gap = 150, 176, 40
    hexs = "0123456789abcdef"
    base = rng.randint(17_000_000, 19_000_000)
    for i in range(3):
        bx = x + i * (bw + gap)
        doc.rect(bx + 3, y + 5, bw, bh, "#000", 6, opacity=0.08, extra=f' filter="{doc.blur(3)}"')
        doc.rect(bx, y, bw, bh, "#FFFFFF", 6, stroke=p.ink, sw=2)
        doc.rect(bx, y, bw, 36, p.ink, 6)
        doc.rect(bx, y + 28, bw, 8, p.ink)
        doc.text(f"#{base + i:,}", bx + bw / 2, y + 24, 15, "#FFFFFF", "mono_bold", anchor="middle")
        doc.text("prev", bx + 14, y + 60, 12, p.muted, "ui")
        doc.text("0x" + "".join(rng.choice(hexs) for _ in range(8)), bx + 14, y + 78, 14, p.ink, "mono")
        for k in range(4):
            ly = y + 100 + k * 18
            doc.rect(bx + 14, ly, rng.uniform(70, 120), 8, "#DDD5C5", 3)
        if i == 1:
            doc.rect(bx + 8, y + 94 + 2 * 18, bw - 16, 24, highlight, 4, opacity=0.18)
            doc.rect(bx + 8, y + 94 + 2 * 18, bw - 16, 24, "none", 4, stroke=highlight, sw=2)
        if i < 2:
            # hash pointer from the next block back to this one
            cy = y + 74
            doc.path(f"M{f(bx + bw + 4)} {f(cy)}H{f(bx + bw + gap - 4)}", stroke=p.ink, sw=2.5)
            doc.circle(bx + bw + 4, cy, 4, p.ink)
            doc.circle(bx + bw + gap - 4, cy, 4, p.ink)
    if money:
        mx = x + (bw + gap) + bw / 2
        doc.path(f"M{f(mx)} {f(y + bh + 4)}V{f(y + bh + 36)}", stroke=highlight, sw=2.5)
        doc.text(money, mx, y + bh + 92, 58, highlight, "display", anchor="middle")
        doc.text(caption, mx, y + bh + 122, 18, p.muted, "ui", anchor="middle")


def _sentence_scale(doc: Doc, x: float, y: float, years: int, color: str) -> None:
    """Maximum sentence as a row of years: one cell per year the charges carry."""
    p = doc.pal
    cols = 9
    cw, ch, gap = 34, 34, 7
    for i in range(years):
        r, c = divmod(i, cols)
        cx, cy = x + c * (cw + gap), y + r * (ch + gap)
        doc.rect(cx, cy, cw, ch, color, 3, opacity=0.9)
        doc.rect(cx, cy, cw, 8, "#000", 3, opacity=0.12)
    rows = (years + cols - 1) // cols
    by = y + rows * (ch + gap) + 6
    doc.path(f"M{f(x)} {f(by)}v10H{f(x + cols * (cw + gap) - gap)}v-10", stroke=p.ink, sw=2)


def _gavel(doc: Doc, cx: float, cy: float) -> None:
    """A gavel resting on its sound block, three-quarter view, turned wood."""
    wood = doc.lin([(0, "#8A5530", 1), (0.45, "#B87A47", 1), (0.55, "#A86C3C", 1), (1, "#5E3518", 1)])
    wood_h = doc.lin([(0, "#6E4122", 1), (0.5, "#C08552", 1), (1, "#4A2A12", 1)], 0, 0, 0, 1)
    # sound block (an elliptical puck)
    doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy + 64)}" rx="150" ry="40" fill="#000" opacity="0.18" '
            f'filter="{doc.blur(10)}"/>')
    doc.path(f"M{f(cx - 130)} {f(cy + 18)}V{f(cy + 46)}A130 34 0 0 0 {f(cx + 130)} {f(cy + 46)}V{f(cy + 18)}Z",
             fill=doc.lin([(0, "#5A3319", 1), (0.5, "#8C5631", 1), (1, "#4A2912", 1)], 0, 0, 1, 0))
    doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy + 18)}" rx="130" ry="34" fill="{wood}"/>')
    doc.add(f'<ellipse cx="{f(cx)}" cy="{f(cy + 18)}" rx="96" ry="24" fill="none" stroke="#5E3518" '
            f'stroke-width="1.5" opacity="0.5"/>')
    # handle, lying diagonally
    with doc.g(f"rotate(-24 {f(cx)} {f(cy)})"):
        doc.rect(cx - 20, cy - 34, 300, 22, wood_h, 11)
        doc.rect(cx + 250, cy - 37, 40, 28, wood_h, 14)
        # head: a turned cylinder with brass bands
        hx, hy = cx - 70, cy - 76
        doc.rect(hx, hy, 74, 108, doc.lin([(0, "#5E3518", 1), (0.35, "#C08552", 1), (0.6, "#9C6436", 1),
                                           (1, "#4A2A12", 1)], 0, 0, 1, 0), 12)
        band = doc.lin([(0, "#7A5A22", 1), (0.4, "#E8C46A", 1), (1, "#6A4A18", 1)], 0, 0, 1, 0)
        doc.rect(hx - 2, hy + 18, 78, 9, band, 3)
        doc.rect(hx - 2, hy + 81, 78, 9, band, 3)
        doc.rect(hx + 16, hy + 6, 8, 96, "#FFFFFF", 4, opacity=0.18)


# ---------------------------------------------------------------- scene

@scene("court_case")
def court_case(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    text = brief.text or ""
    # desk: warm paper ground, lit from the upper left
    doc.rect(0, 0, 1600, 900, doc.lin([(0, "#EDE5D3", 1), (1, "#DCCFB4", 1)], 0, 0, 0.4, 1))
    doc.rect(0, 0, 1600, 900, doc.rad([(0, "#FFFFFF", 0.55), (1, "#FFFFFF", 0)], 0.3, 0.2, 0.7))

    word, entry, tone = _verdict(text)
    col = p.safe if tone == "safe" else p.danger if tone == "danger" else p.accent
    case_no = ("XX-CV-" if tone == "accent" else "XX-CR-") + "".join(rng.choice("0123456789") for _ in range(2)) \
        + "XX"                                                              # masked

    videos = brief.facts.get("videos")
    money = _fact(brief, "money")
    years = str(brief.facts.get("years") or "")
    crypto = re.search(r"crypto|ethereum|bitcoin|blockchain|криптовал|wallet", text) is not None
    kind = ("videos" if videos else "crypto" if crypto
            else "years" if years.isdigit() and int(years) <= 45 else "gavel")

    # ---- the case file (hero), slightly turned on the desk
    fx, fy, fw, fh = 120, 150, 860, 690
    if kind == "gavel":
        fx = 250
    with doc.g(f"rotate(-2.2 {f(fx + fw / 2)} {f(fy + fh / 2)})"):
        _folder(doc, fx, fy, fw, fh, case_no)
        pending = ("SENTENCING scheduled" if word == "GUILTY PLEA" and re.search(r"sentenc|покаранн", text)
                   else "")
        hit = _docket(doc, fx + 46, fy + 34, fw - 110, fh - 30, entry, rng, tone, case_no, pending)
        _binder_clip(doc, fx + fw / 2 - 30, fy + 18)
        _stamp(doc, fx + fw / 2 + 130, fy + fh - 62, word, col, -7)

    # ---- the exhibit
    if kind == "videos":
        ex, ey, ew, eh = 1010, 190, 540, 520
        _exhibit_card(doc, ex, ey, ew, eh, "EXHIBIT A", 3.0)
        with doc.g(f"rotate(3 {f(ex + ew / 2)} {f(ey + eh / 2)})"):
            gx, gy, gw, gh = _contact_sheet(doc, ex + 47, ey + 82, rng, int(str(videos).replace(",", "")))
            doc.text(f"{_fact(brief, 'videos')} videos", ex + 44, ey + eh - 50, 54, p.ink, "display")
            doc.text("leaked", ex + ew - 44, ey + eh - 52, 26, p.danger, "ui_bold", anchor="end")
    elif kind == "crypto":
        ex, ey, ew, eh = 1000, 190, 560, 480
        _exhibit_card(doc, ex, ey, ew, eh, "EXHIBIT A", 2.5)
        with doc.g(f"rotate(2.5 {f(ex + ew / 2)} {f(ey + eh / 2)})"):
            _blocks(doc, ex + 25, ey + 90, rng, money, col if tone != "safe" else p.accent,
                    "alleged theft, in crypto" if tone == "safe" else "in crypto")
    elif kind == "years":
        ex, ey, ew, eh = 1010, 220, 520, 420
        _exhibit_card(doc, ex, ey, ew, eh, "PENALTY", 2.0)
        with doc.g(f"rotate(2 {f(ex + ew / 2)} {f(ey + eh / 2)})"):
            doc.text("faces up to", ex + 50, ey + 110, 24, p.muted, "ui")
            doc.text(f"{years} years", ex + 46, ey + 180, 70, p.ink, "display")
            _sentence_scale(doc, ex + 52, ey + 222, int(years), p.danger)
            doc.text("maximum sentence, one cell per year", ex + 52, ey + 222 + 3 * 41 + 52, 16, p.muted, "ui")
            if re.search(r"ransomware|вимагач", text):
                pill(doc, ex + ew - 50, ey + 36, "charges: ransomware", fg=p.danger, bg="#F6DEDA", size=15,
                     anchor="end")
    else:
        _gavel(doc, 1270, 560)
        if money:
            doc.text(money, 1270, 300, 80, p.ink, "display", anchor="middle")

    doc.focus = Box(140, 120, 1400, 788) if kind != "gavel" else Box(250, 140, 1280, 720)

    # ---- a pen across the folder edge: scale and desk realism
    with doc.g("rotate(-14 1000 800) translate(170 -10)"):
        doc.rect(860, 806, 18, 14, "#000", 6, opacity=0.15, extra=f' filter="{doc.blur(4)}"')
        doc.rect(860, 790, 300, 16, doc.lin([(0, "#2A3348", 1), (0.5, "#4A5672", 1), (1, "#1B2333", 1)]), 8)
        doc.rect(1120, 790, 46, 16, doc.lin([(0, "#8C7A4C", 1), (0.5, "#E1C98A", 1), (1, "#7A6A3E", 1)]), 4)
        doc.path("M860 790L828 798L860 806Z", fill="#C9B98E")
        doc.path("M836 796L828 798L836 800Z", fill="#1B2333")
    _ = (hit, icon)
