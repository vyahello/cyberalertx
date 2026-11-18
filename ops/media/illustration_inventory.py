"""Read-only inventory of editorial illustrations, for renderer rollouts.

    venv/bin/python ops/media/illustration_inventory.py snapshot OUT.json
    venv/bin/python ops/media/illustration_inventory.py compare BEFORE.json [--strict]
    venv/bin/python ops/media/illustration_inventory.py v4-stories

`snapshot` records, per illustration: story key, status, renderer, current
file and alt text. `compare` reports, against a snapshot, which existing
illustrations changed (file, renderer, status or alt), which are new, and the
renderer of every new one; exit code 1 when an existing illustration changed
(or, with --strict, when anything did). `v4-stories` lists the stories whose
illustration was made by cax-editorial-4 (the canary set, for review or
rollback). Never writes to the media store.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _rows() -> dict[str, dict[str, object]]:
    from cyberalertx.media.assets import MediaStore
    out: dict[str, dict[str, object]] = {}
    for a in MediaStore().all():
        if a.asset_type != "editorial_illustration":
            continue
        out[a.story_key] = {"status": a.status, "model": a.generation_model, "file": a.storage_key,
                            "alt": dict(a.alt_text), "source": a.source, "updated_at": a.updated_at}
    return out


def snapshot(path: Path) -> int:
    rows = _rows()
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"{len(rows)} illustrations -> {path}")
    print("by renderer:", dict(Counter(str(r["model"]) for r in rows.values())))
    return 0


def compare(path: Path, strict: bool) -> int:
    before = json.loads(path.read_text(encoding="utf-8"))
    now = _rows()
    changed = {k: [f for f in ("file", "model", "status", "alt") if before[k].get(f) != now[k].get(f)]
               for k in before if k in now}
    changed = {k: v for k, v in changed.items() if v}
    gone = sorted(set(before) - set(now))
    new = sorted(set(now) - set(before))
    print(f"before {len(before)}  now {len(now)}  unchanged {len(before) - len(changed) - len(gone)}  "
          f"changed {len(changed)}  missing {len(gone)}  new {len(new)}")
    for k, fields in sorted(changed.items()):
        print(f"CHANGED {k}: {', '.join(fields)} ({before[k].get('model')} -> {now[k].get('model')})")
    for k in gone:
        print(f"MISSING {k}")
    for k in new:
        print(f"NEW {k}: {now[k]['model']} {now[k]['status']}")
    print("new by renderer:", dict(Counter(str(now[k]["model"]) for k in new)))
    bad = bool(changed or gone) or (strict and bool(new))
    return 1 if bad else 0


def v4_stories() -> int:
    for k, r in sorted(_rows().items()):
        if r["model"] == "cax-editorial-4":
            print(k)
    return 0


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(ROOT))
    if len(argv) >= 2 and argv[0] == "snapshot":
        return snapshot(Path(argv[1]))
    if len(argv) >= 2 and argv[0] == "compare":
        return compare(Path(argv[1]), "--strict" in argv)
    if argv[:1] == ["v4-stories"]:
        return v4_stories()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
