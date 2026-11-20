"""Which stories the website's current edition shows: the one resolver.

The homepage (frontend/app/[locale]/page.tsx) shows the first FEED_SIZE (40)
posts available in each language, from an OVERVIEW_POOL of 120 requested as
`/posts?language=..&limit=120&cached_only=1`. This module asks the API the
same question, then maps every visible article to the story the intel engine
places it in NOW: that story's key is what `media.engine.run(only=...)`
regenerates. (An article's stored `story_key` can lag behind the clustering;
the asset currently displayed can belong to a dissolved story. Neither is used.)

`ops/media/edition_stories.py` prints this list for review and for
`tools.media backfill --batch N --only-file FILE`; nothing else selects an
edition.
"""
from __future__ import annotations

from typing import Any, Sequence

FEED_SIZE = 40
POOL = 120


def visible_fingerprints(api: str, size: int = FEED_SIZE) -> list[str]:
    """Article ids the homepage shows now, EN then UA, without repeats."""
    import httpx

    out: list[str] = []
    for loc in ("en", "ua"):
        r = httpx.get(f"{api.rstrip('/')}/posts", params={"language": loc, "limit": POOL, "cached_only": 1},
                      timeout=60)
        r.raise_for_status()
        visible = [p for p in r.json().get("items", []) if loc in (p.get("available_locales") or [])][:size]
        out += [str(p["id"]) for p in visible if str(p["id"]) not in out]
    return out


def story_keys(fingerprints: Sequence[str], stories: Sequence[Any]) -> tuple[list[str], list[str]]:
    """(story keys of these articles in edition order, articles no story contains)."""
    of = {m.fingerprint: st.key for st in stories for m in st.members}
    keys = list(dict.fromkeys(of[fp] for fp in fingerprints if fp in of))
    return keys, [fp for fp in fingerprints if fp not in of]


def edition_story_keys(api: str, items: Sequence[Any], *, size: int = FEED_SIZE, sheets: Any = None,
                       posts: Any = None) -> tuple[list[str], list[str]]:
    """(story keys behind the visible edition, visible articles with no story)."""
    from ..intel.engine import run as intel_run

    intel = intel_run(list(items), sheets=sheets, posts=posts, write=False)
    return story_keys(visible_fingerprints(api, size), intel.stories)


__all__ = ["FEED_SIZE", "edition_story_keys", "story_keys", "visible_fingerprints"]
