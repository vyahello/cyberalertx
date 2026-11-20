"""Read-only: the story keys of the stories the website currently shows.

    venv/bin/python ops/media/edition_stories.py [--api http://127.0.0.1:8000] [--size 40] > edition.txt

The single source of truth for edition membership: it prints what
`cyberalertx.media.edition` resolves (the first `--size` posts available in
each language, as the homepage requests them, mapped to the story the intel
engine places each article in now). One story key per line, preceded by a
comment line naming its current renderer and headline. Feed the file to

    venv/bin/python -m cyberalertx.tools.media backfill --batch 60 --only-file edition.txt

to regenerate exactly these stories; nothing else is touched. Writes nothing.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(ROOT))
    from cyberalertx.config import DATA_DIR
    from cyberalertx.media.assets import MediaStore
    from cyberalertx.media.edition import FEED_SIZE, edition_story_keys
    from cyberalertx.storage.json_store import JsonNewsStore
    from cyberalertx.tools.media import _stores

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--size", type=int, default=FEED_SIZE)
    ap.add_argument("--store", default="", help="media store to report renderers from (default: production)")
    args = ap.parse_args(argv)

    items = JsonNewsStore(DATA_DIR / "items.json").all()
    sheets, posts = _stores()
    keys, orphans = edition_story_keys(args.api, items, size=args.size, sheets=sheets, posts=posts)
    store = MediaStore(Path(args.store)) if args.store else MediaStore()
    titles = {i.fingerprint: i.title for i in items}
    for key in keys:
        a = store.get(f"illus:{key}")
        model = a.generation_model if a is not None and a.status in ("validated", "published") else "no image"
        title = titles.get(a.members[0], "") if a is not None and a.members else ""
        print(f"# {model} | {title[:90]}")
        print(key)
    print(f"{len(keys)} stories in the visible edition"
          + (f"; {len(orphans)} visible articles belong to no story: {', '.join(orphans)}" if orphans else ""),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
