"""Crafted TCP traffic crashes a Linux server: a TCP header (RFC 9293
layout) for the crafted segments, a dense stream of them reaching the
server's network port, and the server console stopped on a kernel failure.

The trace is generic and plausible (receive path, fatal exception in
interrupt); no CVE, function name of the bug or address is claimed."""
from __future__ import annotations

import random

from ..brief import EditorialBrief
from ..kit import H, W, Box, Doc, f, window
from . import scene


def _header(doc: Doc, b: Box, danger: str) -> tuple[float, float]:
    """TCP header diagram: 32-bit rows. Returns the right-middle anchor."""
    p = doc.pal
    doc.shadow(b.x, b.y, b.w, b.h, 12, 0.9)
    doc.rect(b.x, b.y, b.w, b.h, "#111A2A", 12, stroke=danger, sw=2)
    doc.text("TCP segment", b.x + 24, b.y + 40, 20, p.ink, "ui_bold")
    doc.text("crafted", b.r - 24, b.y + 40, 18, danger, "mono_bold", anchor="end")
    gx, gw = b.x + 24, b.w - 48
    top = b.y + 82
    # bit ruler
    for k in range(0, 33, 8):
        x = gx + gw * k / 32
        doc.line((x, top - 14), (x, top - 4), p.muted, 1.2)
        doc.text(str(k if k < 32 else 31), x, top - 20, 11, p.muted, "mono", anchor="middle")
    rows = [
        [("source port", 16), ("destination port", 16)],
        [("sequence number", 32)],
        [("acknowledgment number", 32)],
        [("off", 4), ("rsv", 4), ("flags", 8), ("window", 16)],
        [("checksum", 16), ("urgent pointer", 16)],
        [("options", 32)],
    ]
    rh = 44.0
    for r, cells in enumerate(rows):
        y = top + r * rh
        x = gx
        for name, bits in cells:
            w = gw * bits / 32
            hot = False      # the sources do not say which field is malformed
            doc.rect(x, y, w, rh, "#18233A" if not hot else "#2A1620", 0, stroke="#3A4A66", sw=1.2)
            doc.text(name, x + w / 2, y + rh / 2 + 5, 14, p.ink if not hot else "#FFB4AE", "mono",
                     anchor="middle")
            x += w
    # payload stub
    y = top + len(rows) * rh
    doc.rect(gx, y, gw, 36, "none", 0, stroke="#3A4A66", sw=1.2, extra=' stroke-dasharray="6 6"')
    doc.text("data", gx + gw / 2, y + 23, 14, p.muted, "mono", anchor="middle")
    return b.r, b.y + b.h / 2


def _server(doc: Doc, b: Box, brief: EditorialBrief, danger: str) -> tuple[float, float]:
    """1U server, front elevation. Returns the NIC port position."""
    p = doc.pal
    doc.shadow(b.x, b.y, b.w, b.h, 6, 0.8)
    doc.rect(b.x, b.y, b.w, b.h, doc.lin([(0, "#2A3448", 1), (1, "#1A2232", 1)]), 5, stroke="#3E4C66", sw=1.2)
    for k in range(4):
        dx = b.x + 18 + k * 70
        doc.rect(dx, b.y + 12, 62, b.h - 24, "#121A28", 3, stroke="#33415A", sw=1)
        doc.path("".join(f"M{f(dx + 8)} {f(b.y + 20 + j * 6)}h40" for j in range(int((b.h - 40) / 6))),
                 stroke="#26324A", sw=2.4)
    # status: fault LED
    doc.circle(b.r - 150, b.y + 24, 5, danger)
    doc.glow(b.r - 150, b.y + 24, 14, 14, danger, 0.6)
    doc.circle(b.r - 130, b.y + 24, 5, "#2A3448", "#4A5A78", 1)
    # NIC
    px, py = b.r - 92, b.y + 16
    doc.rect(px, py, 40, 30, "#0B0F18", 3, stroke="#5B6B88", sw=1.2)
    doc.rect(px + 8, py + 6, 24, 16, "#000")
    doc.rect(px + 3, py + 2, 7, 4, "#FBBF24", 1)
    doc.text("eth0", px + 20, b.b + 22, 13, p.muted, "mono", anchor="middle")
    # services named by the sources
    svc = [s for s in ("nginx", "apache", "ssh") if s in brief.text]
    if svc:
        doc.text("  ".join(svc), b.x, b.b + 22, 14, p.muted, "mono")
    return px + 20, py + 15


@scene("kernel_dos")
def kernel_dos(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    doc.rect(0, 0, W, H, doc.lin([(0, p.bg1, 1), (1, p.bg0, 1)], 0, 0, 0.3, 1))
    doc.rect(0, 0, W, H, doc.rad([(0, "#FFFFFF", 0.06), (1, "#FFFFFF", 0)], 0.65, 0.35, 0.6))

    hb = Box(60, 80, 560, 420)
    hx, hy = _header(doc, hb, p.danger)

    srv = Box(70, 690, 520, 64)
    nx, ny = _server(doc, srv, brief, p.danger)

    # the stream: many copies of the crafted segment arriving at the NIC
    sy = 606.0
    xs = [-10 + i * 25.0 for i in range(19)]
    for i, x in enumerate(xs):
        a = 0.25 + 0.75 * i / len(xs)
        doc.rect(x, sy - 10, 20, 20, p.danger, 3, opacity=a)
        doc.rect(x, sy - 10, 7, 20, "#FFFFFF", 2, opacity=0.25 * a)
    doc.path(f"M{f(xs[-1] + 24)} {f(sy)}H{f(nx - 16)}Q{f(nx)} {f(sy)} {f(nx)} {f(sy + 16)}V{f(ny - 18)}",
             stroke=p.danger, sw=3.5)
    doc.poly([(nx, ny - 8), (nx - 9, ny - 24), (nx + 9, ny - 24)], p.danger)
    # the diagram describes each segment of the stream
    doc.path(f"M{f(hb.cx)} {f(hb.b)}V{f(sy - 22)}", stroke=p.danger, sw=1.5, dash="4 5", opacity=0.8)

    # console: stopped on a kernel failure
    win = Box(720, 90, 830, 690)
    body = window(doc, win, title="srv-web-01 - Linux console", surface="#070B12", chrome="#121A28")
    tx, ty = body.x + 28, body.y + 44
    ts = "[ 8125.44{:04d}]"
    lines: list[tuple[str, str]] = [
        ("srv-web-01 login:", "#8C9AB3"),
        ("", "#8C9AB3"),
        (ts.format(1902) + " general protection fault: 0000 [#1] SMP", "#E8EDF5"),
        (ts.format(1917) + " CPU: 3 PID: 0 Comm: swapper/3", "#C9D3E3"),
        (ts.format(1931) + " RIP: 0010:0xffffffff8a3c41d2", "#C9D3E3"),
        (ts.format(1946) + " Call Trace:", "#C9D3E3"),
        (ts.format(1950) + "  <IRQ>", "#8C9AB3"),
        (ts.format(1958) + "  tcp_v4_rcv+0x...", "#C9D3E3"),
        (ts.format(1966) + "  ip_protocol_deliver_rcu+0x...", "#C9D3E3"),
        (ts.format(1973) + "  ip_local_deliver_finish+0x...", "#C9D3E3"),
        (ts.format(1981) + "  __netif_receive_skb_one_core+0x...", "#C9D3E3"),
        (ts.format(1990) + "  net_rx_action+0x...", "#C9D3E3"),
        (ts.format(1998) + "  </IRQ>", "#8C9AB3"),
    ]
    size, lh = 17.0, 31.0
    for i, (s, c) in enumerate(lines):
        doc.text(s, tx, ty + i * lh, size, c, "mono")
    # the panic line (focal)
    py = ty + len(lines) * lh + 34
    doc.rect(body.x + 14, py - 34, body.w - 28, 96, p.danger, 6, opacity=0.14)
    doc.rect(body.x + 14, py - 34, 5, 96, p.danger)
    doc.text("Kernel panic - not syncing:", tx, py, 24, "#FFFFFF", "mono_bold")
    doc.text("Fatal exception in interrupt", tx, py + 38, 24, p.danger, "mono_bold")
    doc.text("---[ end Kernel panic ]---", tx, py + 104, 17, "#8C9AB3", "mono")
    doc.rect(tx, py + 124, 12, 22, "#8C9AB3", opacity=0.6)

    # link: server -> its console
    doc.path(f"M{f(srv.r)} {f(srv.cy)}C{f(srv.r + 60)} {f(srv.cy)} {f(win.x - 60)} {f(win.b - 60)} "
             f"{f(win.x)} {f(win.b - 60)}", stroke="#4A5A78", sw=2, dash="4 6")

    doc.rect(0, 0, W, H, doc.rad([(0.55, "#000", 0), (1, "#000", 0.5)], 0.5, 0.5, 0.78))
    doc.focus = Box(40, 80, 1520, 855)
