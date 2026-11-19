"""V4.1 canary in quarantine: candidates are reviewed before anything is published.

Production keeps rendering with V3. No systemd override is used. A canary
**session** collects V4.1 candidates for real eligible stories into a review
directory outside the media store:

* `start`: creates the session. It records the eligible stories that exist
  now (only stories published later count as new), the image-index
  checksum, and an **expiry** (6 h by default). After the expiry, `collect`
  refuses. That is the secondary guard; the primary one is that nothing is
  published.
* `collect`: renders each new eligible story with V4.1 in memory and writes
  its SVG, alt text, labels, brief and consistency check into the session.
  Stories the hybrid policy routes to V3 are listed, never drawn. The image
  index is not written: its checksum is verified before and after, and a
  change aborts the run.
* `gallery`: a static review page (source, full size, 176 px feed crop,
  EN/UA alt text, scores) in the session directory.
* `review`: records scores and a verdict per candidate.
* `promote`: puts **explicitly approved** candidates, and nothing else, into
  production. The candidate must re-render byte for byte with the deployed
  code. Only those stories may change in the index; their previous files
  stay in `previous_storage_keys`, so old URLs keep working.
* `cleanup`: deletes a session's files; the image index is untouched.

Candidates never have a public URL: `/media` serves only files the image
index references, and Telegram and Threads only send the index's images.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any, Iterable, Sequence

from .assets import MediaStore

SESSION = "session.json"
MANIFEST = "candidates.json"
REVIEW = "review.json"
PROMOTED = "promoted.json"
V4 = "cax-editorial-4"
#: Gates a candidate must meet to be approved (scores 1-5).
GATES = {"relevance": 4, "recognition": 4, "visual": 4, "composition": 3, "accuracy": 4, "integrity": 5,
         "thumbnail": 4}


class CandidateError(RuntimeError):
    """A quarantine rule refused the operation; nothing was changed."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True, default=list), encoding="utf-8")
    os.replace(tmp, path)


def index_digest(store: MediaStore) -> str:
    """Checksum of the production image index (empty when there is none)."""
    return hashlib.sha256(store.index.read_bytes()).hexdigest() if store.index.exists() else ""


def illustrations(store: MediaStore) -> dict[str, tuple[str, str, str]]:
    """{asset_id: (storage key, renderer, status)} of every editorial illustration."""
    return {a.asset_id: (a.storage_key, a.generation_model, a.status) for a in store.all()
            if a.asset_type == "editorial_illustration"}


# ------------------------------------------------------------------ session

def start(root: Path, eligible_keys: Iterable[str], *, store: MediaStore, hours: float = 6.0,
          release: str = "", now: datetime | None = None) -> Path:
    now = now or _now()
    if not 0 < hours <= 12:
        raise CandidateError("expiry must be between 0 and 12 hours")
    session = Path(root) / now.strftime("%Y%m%d-%H%M%S")
    session.mkdir(parents=True, exist_ok=False)
    os.chmod(session, 0o700)
    _write(session / SESSION, {
        "created_at": now.isoformat(), "expires_at": (now + timedelta(hours=hours)).isoformat(),
        "baseline_stories": sorted(set(eligible_keys)), "index_sha256": index_digest(store), "release": release,
    })
    return session


def load(session: Path) -> dict[str, Any]:
    data = _read(Path(session) / SESSION, None)
    if not isinstance(data, dict):
        raise CandidateError(f"{session} is not a candidate session")
    return data


def expired(session: Path, now: datetime | None = None) -> bool:
    return (now or _now()) >= datetime.fromisoformat(load(session)["expires_at"])


# ------------------------------------------------------------------ collect

def _crop_box(svg: str) -> list[float]:
    m = re.search(r'<rect id="cax-focus" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg)
    return [float(v) for v in m.groups()] if m else [0.0, 0.0, 1600.0, 900.0]


def collect(session: Path, stories: Sequence[Any], *, store: MediaStore, eligible: Any,
            recent: int = 0, refresh: Sequence[str] = (), now: datetime | None = None) -> dict[str, Any]:
    """Render V4.1 candidates for the new eligible stories (and, with
    `recent`, that many of the newest existing stories that have no V4.1
    image). `eligible(story) -> bool` is the production eligibility test.
    Never writes the image index."""
    from .renderer import plan_for
    from .v4.consistency import check_brief
    from .v4.render import render_doc

    session = Path(session)
    meta = load(session)
    now = now or _now()
    if expired(session, now):
        raise CandidateError(f"session expired at {meta['expires_at']}; start a new one")
    before = index_digest(store)
    baseline = set(meta["baseline_stories"])
    manifest: dict[str, Any] = _read(session / MANIFEST, {})
    current = illustrations(store)
    added, routed, extra = [], [], 0
    redo = set(refresh)
    unknown = redo - set(manifest)
    if unknown:
        raise CandidateError(f"not candidates of this session: {sorted(unknown)}")
    for story in sorted(stories, key=lambda s: s.anchor.published_at, reverse=True):
        if story.key in redo:
            # a corrected candidate replaces the reviewed one; the old file is kept beside it
            old = manifest.pop(story.key)
            if old.get("file") and (session / old["file"]).exists():
                (session / old["file"]).rename(session / f"{old['file'][:-4]}.{old['svg_sha256'][:8]}.svg")
            redo.discard(story.key)
            new = bool(old.get("new"))
        elif story.key in manifest or not eligible(story):
            continue
        else:
            new = story.key not in baseline
        if not new and story.key not in refresh:
            if extra >= recent or current.get(f"illus:{story.key}", ("", "", ""))[1] == V4:
                continue
        plan = plan_for(story, V4)
        if plan.renderer != V4:
            manifest[story.key] = {"route": plan.renderer, "routed": plan.routed, "title": story.anchor.title,
                                   "new": new, "collected_at": now.isoformat()}
            routed.append(story.key)
            continue
        doc = render_doc(plan.brief)
        svg = doc.svg()
        name = story.key.split(":", 1)[-1]
        (session / f"{name}.svg").write_text(svg, encoding="utf-8")
        b = plan.brief
        manifest[story.key] = {
            "route": V4, "new": new, "collected_at": now.isoformat(), "file": f"{name}.svg",
            "svg_sha256": hashlib.sha256(svg.encode("utf-8")).hexdigest(), "inputs_hash": plan.inputs_hash,
            "title": story.anchor.title, "source": str(story.anchor.source or ""), "url": str(story.anchor.url or ""),
            "published_at": str(story.anchor.published_at), "excerpt": str(story.anchor.raw_content or "")[:700],
            "scene": b.scene, "confidence": b.confidence, "status": b.status, "facts": b.facts,
            "entities": list(b.entities), "labels": list(dict.fromkeys(doc.labels)), "alt": plan.alt,
            "alt_problems": check_brief(b, doc.labels), "focus": _crop_box(svg),
            "production_image": current.get(f"illus:{story.key}", ("", "", ""))[0],
        }
        added.append(story.key)
        if not new and story.key not in refresh:
            extra += 1
    if index_digest(store) != before:
        raise CandidateError("the image index changed during collection: aborting (no candidate saved)")
    _write(session / MANIFEST, manifest)
    return {"added": added, "routed_to_v3": routed, "index_sha256": before,
            "candidates": sum(1 for v in manifest.values() if v.get("route") == V4)}


# ------------------------------------------------------------------ review and gallery

def review(session: Path, key: str, *, scores: dict[str, int], verdict: str, reviewer: str,
           notes: str = "") -> dict[str, Any]:
    manifest = _read(Path(session) / MANIFEST, {})
    if manifest.get(key, {}).get("route") != V4:
        raise CandidateError(f"{key} is not a V4.1 candidate of this session")
    if verdict not in ("approved", "rejected"):
        raise CandidateError("verdict must be 'approved' or 'rejected'")
    missing = [g for g in GATES if g not in scores]
    if missing:
        raise CandidateError(f"missing scores: {', '.join(missing)}")
    failed = [g for g, floor in GATES.items() if int(scores[g]) < floor]
    if verdict == "approved" and (failed or manifest[key]["alt_problems"]):
        raise CandidateError(f"{key} cannot be approved: gates failed {failed or manifest[key]['alt_problems']}")
    data = _read(Path(session) / REVIEW, {})
    data[key] = {"scores": scores, "verdict": verdict, "reviewer": reviewer, "notes": notes,
                 "at": _now().isoformat(), "svg_sha256": manifest[key]["svg_sha256"]}
    _write(Path(session) / REVIEW, data)
    entry: dict[str, Any] = data[key]
    return entry


def gallery(session: Path) -> Path:
    """index.html in the session directory (relative image links only)."""
    session = Path(session)
    meta, manifest, rev = load(session), _read(session / MANIFEST, {}), _read(session / REVIEW, {})
    cards, routed = [], []
    for key, c in sorted(manifest.items(), key=lambda kv: kv[1].get("published_at", ""), reverse=True):
        if c.get("route") != V4:
            routed.append(f"<li><code>{escape(key)}</code> {escape(c.get('title', ''))} "
                          f"<span class=muted>({escape(c.get('routed', ''))})</span></li>")
            continue
        r = rev.get(key, {})
        x, y, w, h = c["focus"]
        sc = " · ".join(f"{g} {r['scores'][g]}" for g in GATES) if r else "not reviewed"
        cards.append(f"""<article>
<h2>{escape(c['title'])}</h2>
<p class=meta><code>{escape(key)}</code> · {'new story' if c['new'] else 'existing story'} · scene
<b>{escape(c['scene'])}</b> ({escape(c['confidence'])}) · evidence status {escape(c['status'])} ·
source <a href="{escape(c['url'])}">{escape(c['source'])}</a></p>
<p class=excerpt>{escape(c['excerpt'])}</p>
<div class=imgs><img class=full src="{escape(c['file'])}" alt="{escape(c['alt'].get('en', ''))}">
<div><svg class="feed" viewBox="{x} {y} {w} {h}" width="176" height="99" preserveAspectRatio="xMidYMid slice"><image
href="{escape(c['file'])}" width="1600" height="900"/></svg><p class=muted>176 px feed crop</p>
<img class=og src="{escape(c['file'])}" alt=""><p class=muted>1200×630 card crop</p></div></div>
<p><b>Alt EN:</b> {escape(c['alt'].get('en', ''))}<br><b>Alt UA:</b> {escape(c['alt'].get('ua', ''))}</p>
<p class=muted>Labels: {escape(' | '.join(c['labels']))} · alt check:
{escape('; '.join(c['alt_problems']) or 'matches the drawn labels')}</p>
<p><b>Review:</b> {escape(r.get('verdict', 'pending'))} — {escape(sc)} {escape(r.get('notes', ''))}</p>
</article>""")
    html = f"""<!doctype html><meta charset=utf-8><title>V4.1 candidates</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;max-width:1180px;margin:24px auto;padding:0 16px;color:#16201f;
background:#f6f7f5}}article{{background:#fff;border:1px solid #d9dfdc;border-radius:8px;padding:16px;margin:18px 0}}
.imgs{{display:grid;grid-template-columns:3fr 1fr;gap:14px}}.full{{width:100%;border-radius:6px}}
.feed{{border:1px solid #ccc}}.og{{width:100%;aspect-ratio:1200/630;object-fit:cover;border-radius:4px}}
.muted{{color:#5a6866;font-size:13px}}.excerpt{{color:#33413f}}h2{{font-size:18px;margin:0 0 6px}}</style>
<h1>V4.1 candidates (quarantine, not published)</h1>
<p class=muted>Session created {escape(meta['created_at'])}, expires {escape(meta['expires_at'])};
image index sha256 at start {escape(meta['index_sha256'][:16])}… · release {escape(meta.get('release', ''))}</p>
{''.join(cards) or '<p>No candidates yet.</p>'}
<h2>Routed to V3 by the hybrid policy</h2><ul>{''.join(routed) or '<li>none</li>'}</ul>"""
    out = session / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


# ------------------------------------------------------------------ promote and cleanup

def promote(session: Path, keys: Sequence[str], *, items: Sequence[Any], store: MediaStore, sheets: Any = None,
            posts: Any = None, now: datetime | None = None, run_engine: Any = None) -> dict[str, Any]:
    """Publish the approved candidates `keys`, and only them."""
    from . import engine
    from .renderer import plan_for
    from .v4.render import render

    session = Path(session)
    manifest, rev = _read(session / MANIFEST, {}), _read(session / REVIEW, {})
    keys = list(dict.fromkeys(keys))
    if not keys:
        raise CandidateError("no stories given")
    for k in keys:
        c, r = manifest.get(k), rev.get(k)
        if not c or c.get("route") != V4:
            raise CandidateError(f"{k} is not a V4.1 candidate of this session")
        if not r or r.get("verdict") != "approved" or r.get("svg_sha256") != c["svg_sha256"]:
            raise CandidateError(f"{k} is not approved in review.json")
    run_engine = run_engine or engine.run
    from ..intel.engine import run as intel_run
    intel = intel_run(list(items), now=now or _now(), sheets=sheets, posts=posts, write=False)
    by_key = {s.key: s for s in intel.stories}
    for k in keys:
        story = by_key.get(k)
        if story is None:
            raise CandidateError(f"{k} is no longer in the story set")
        sha = hashlib.sha256(render(plan_for(story, V4).brief).encode("utf-8")).hexdigest()
        if sha != manifest[k]["svg_sha256"]:
            raise CandidateError(f"{k} no longer renders as the reviewed candidate (code or sources changed)")
    before = illustrations(store)
    prev_env = os.environ.get("CYBERALERTX_ILLUSTRATION_RENDERER")
    os.environ["CYBERALERTX_ILLUSTRATION_RENDERER"] = "editorial-4"
    try:
        res = run_engine(list(items), store=store, sheets=sheets, posts=posts, now=now or _now(),
                         max_calls=len(keys), upgrade_renderer=True, only=frozenset(keys))
    finally:
        if prev_env is None:
            os.environ.pop("CYBERALERTX_ILLUSTRATION_RENDERER", None)
        else:
            os.environ["CYBERALERTX_ILLUSTRATION_RENDERER"] = prev_env
    after = illustrations(store)
    changed = {a for a in set(before) | set(after) if before.get(a) != after.get(a)}
    wanted = {f"illus:{k}" for k in keys}
    if not changed <= wanted:
        raise CandidateError(f"unexpected index changes: {sorted(changed - wanted)}")
    done = []
    for k in keys:
        a = store.get(f"illus:{k}")
        if a is None or a.generation_model != V4 or not a.storage_key.startswith(manifest[k]["svg_sha256"]):
            raise CandidateError(f"{k} was not published as the reviewed candidate")
        done.append({"story": k, "asset_id": a.storage_key[:16], "previous": [p[:16] for p in a.previous_storage_keys],
                     "at": (now or _now()).isoformat()})
    log = _read(session / PROMOTED, [])
    _write(session / PROMOTED, log + done)
    return {"promoted": done, "failed": getattr(res, "failed", [])}


def cleanup(session: Path, *, store: MediaStore) -> str:
    """Delete a session's candidate files. Returns the (unchanged) index checksum."""
    session = Path(session)
    load(session)
    before = index_digest(store)
    shutil.rmtree(session)
    if index_digest(store) != before:
        raise CandidateError("the image index changed during cleanup")
    return before
