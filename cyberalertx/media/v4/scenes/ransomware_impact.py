"""Ransomware impact: a file share whose files carry the encryptor's extension
and padlocks, with the ransom note open on top. Variants follow the sources:
a hypervisor datastore with locked virtual-machine disks when the story is
about ESXi / vCenter, database files when the claim is about databases, and a
"data theft claimed" marker only when the sources say so. The note's contact
is an `.example` domain and its victim ID a placeholder."""
from __future__ import annotations

import random
import re

from .. import type as T
from ..brief import EditorialBrief
from ..kit import Box, Doc, background, icon, pill, vignette, window
from . import scene


def _files(text: str) -> tuple[str, list[str], str]:
    """(path, file names, kind) for the share the story concerns."""
    if re.search(r"esxi|vcenter|hypervisor|гіпервізор", text):
        return ("[datastore1] /vmfs/volumes", ["vm-dc01.vmdk", "vm-sql02.vmdk", "vm-files03.vmdk",
                                               "vm-erp04.vmx", "vm-mail05.vmdk", "vm-web06.vmdk"], "vm")
    if re.search(r"database|бази даних|\bsql\b", text):
        return ("\\\\db01\\data", ["students.mdf", "staff.mdf", "research.bak", "records.ldf", "finance.mdf",
                                   "archive.bak"], "db")
    return ("\\\\fs01\\shares\\finance", ["budget.xlsx", "payroll.xlsx", "contracts.pdf", "invoices.zip",
                                            "minutes.docx", "backup.vhdx"], "fs")


@scene("ransomware_impact")
def ransomware_impact(doc: Doc, brief: EditorialBrief, rng: random.Random) -> None:
    p = doc.pal
    background(doc, light=(0.72, 0.3))
    doc.glow(1180, 470, 420, 300, p.danger, 0.16)
    t = brief.text
    path, names, kind = _files(t)
    ext = "." + "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(6))
    theft = bool(re.search(r"data theft|stole|exfiltrat|викра", t))

    # ---- the share, every entry encrypted
    win = Box(60, 96, 900, 700)
    body = window(doc, win, title="datastore browser" if kind == "vm" else "file explorer", surface="#1A1211", chrome="#251816")
    doc.rect(body.x + 24, body.y + 18, body.w - 48, 40, "#120C0B", 8, stroke=p.line, sw=1)
    icon(doc, "server", body.x + 48, body.y + 38, 20, p.muted, 1.8)
    doc.text(path, body.x + 70, body.y + 44, 18, p.ink, "mono")
    hy = body.y + 100
    for xx, lab in ((body.x + 40, "NAME"), (body.x + 560, "STATUS")):
        doc.text(lab, xx, hy, 15, p.muted, "ui_bold", tracking=2)
    doc.line((body.x + 24, hy + 14), (body.r - 24, hy + 14), p.line, 1.5)
    rh = 74.0
    for i, n in enumerate(names):
        y = hy + 30 + i * rh
        doc.rect(body.x + 24, y, body.w - 48, rh - 10, "#241817" if i % 2 == 0 else "#1E1413", 8)
        icon(doc, "file", body.x + 64, y + 32, 34, "#8A6A60", 2)
        label = f"{n}{ext}"
        icon(doc, "lock", body.x + 80, y + 46, 22, p.accent, 2.4)
        doc.text(T.fit(label, 24, 400, "mono"), body.x + 112, y + 42, 24, p.ink, "mono")
        doc.text("encrypted", body.x + 560, y + 42, 20, p.accent, "mono_bold")

    # ---- the ransom note (focal)
    note = Box(880, 190, 640, 520)
    nb = window(doc, note, title="README_RESTORE.txt", surface="#FFF8F2", chrome="#F0E2D8", depth=1.3)
    doc.rect(note.x, note.y, note.w, note.h, "none", 14, stroke=p.danger, sw=3)
    vid = "-".join("".join(rng.choice("0123456789ABCDEF") for _ in range(4)) for _ in range(3))
    lines: list[tuple[str, str, str, float]] = [
        ("YOUR FILES ARE", "#1A0F0E", "mono_bold", 40),
        ("ENCRYPTED", p.danger, "mono_bold", 52),
        ("", "", "", 4),
        (f"Extension: {ext}", "#3C2B28", "mono", 22),
        (f"Victim ID: {vid}", "#3C2B28", "mono", 22),
        ("", "", "", 14),
        ("To restore access, contact:", "#3C2B28", "mono", 22),
        ("negotiate.example", p.danger, "mono_bold", 26),
    ]
    y = nb.y + 76
    for s, c, font, size in lines:
        if s:
            doc.text(s, nb.x + 44, y, size, c, font)
        y += size * 1.55
    icon(doc, "lock", nb.r - 80, nb.y + 70, 64, p.danger, 3)
    if theft:
        pill(doc, note.x + 44, note.b + 26, "data theft claimed", fg="#FFFFFF", bg=p.danger, size=20, font="ui_bold",
             pad=16)
        icon(doc, "upload", note.x + 44 + T.measure("data theft claimed", 20, "ui_bold") + 64, note.b + 45, 30,
             p.danger, 2.6)
    doc.focus = Box(60, 96, 1460, 821)
    vignette(doc, 0.55)
