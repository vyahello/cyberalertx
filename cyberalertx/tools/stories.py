"""Story and relevance tools — dry-run reports and editor corrections.

    python -m cyberalertx.tools.stories cluster-report
    python -m cyberalertx.tools.stories relevance-report
    python -m cyberalertx.tools.stories relevance-override FP out_of_scope --reason "eSports"
    python -m cyberalertx.tools.stories split FP --reason "different victim"
    python -m cyberalertx.tools.stories merge FP_A FP_B --reason "same incident"

Nothing here rewrites `data/items.json` or `data/threat_posts.json`. The
reports write only `data/stories/*_report.json`; the correction commands
write only `data/stories/overrides.json` / `relevance_overrides.json`, which
the pipeline applies after matching (see docs/intel/STORIES_AND_EVIDENCE.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from ..models import NewsItem
from ..pipeline.dedup import (
    StoryCluster,
    StoryFeatures,
    cluster_items,
    independent_sources,
    load_story_overrides,
    match_story,
    name_statistics,
)
from ..pipeline.relevance import (
    RELEVANCE_STATUSES,
    apply_relevance_overrides,
    classify_scope,
    effective_relevance,
    load_relevance_overrides,
    save_relevance_override,
)
from ..storage.json_store import JsonNewsStore

# docs/editorial/CONTENT_AUDIT.md F1: UA briefs published although they are
# not security news. Fingerprints of the SOURCE items.
AUDIT_OFF_TOPIC: tuple[str, ...] = (
    "8f1d28b46a63775d", "883eb214111ce7d3", "c0f0a626c0d0a328", "3e659275d2c056b2",
    "037a9bae09febe7d", "82e7ac3eddc04a16", "2091b0f17e2cbc62", "fa849eb9421929f8",
    "13f9c1aa686f04a0", "c050f89a66ca62f0", "ff9b95fee00b5a5b", "27814544e0ba7af7",
    "0af8a563559912cd", "4a2b9668bebf6b9a", "6cfeddc8a98e866e", "1ef37aa9b444644a",
    "0ae1af88418f6bb6", "ed59ae1703be6ab2", "503728559f8b39b6", "76d31b2a3fa2b8d0",
    "9bdbaf0ff3a13ca5", "4dec087390da4de4", "65a32171ba5abfd1", "3a1ee0d3b835193a",
    "98b97728663ba724", "48868757f348f25e", "449181ad69e3a70a", "c6da58c9db09652c",
)


def _data_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    from ..config import DATA_DIR
    return DATA_DIR


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".json", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _brief(item: NewsItem) -> dict[str, str]:
    return {"fingerprint": item.fingerprint, "source": item.source, "title": item.title,
            "published_at": item.published_at.isoformat()}


# ---------------------------------------------------------------------------
# cluster-report
# ---------------------------------------------------------------------------

def build_cluster_report(items: Sequence[NewsItem], data_dir: Path) -> dict[str, Any]:
    """Stored `story_key` grouping vs what `cluster_items` assigns now. Pure
    apart from reading the overrides file."""
    overrides = load_story_overrides(data_dir / "stories" / "overrides.json")
    by_fp = {i.fingerprint: i for i in items}
    stored: dict[str, list[str]] = {}
    for i in items:
        stored.setdefault(i.story_key or f"fp:{i.fingerprint}", []).append(i.fingerprint)
    stored_of = {fp: k for k, fps in stored.items() for fp in fps}

    clusters = cluster_items(items, overrides=overrides)
    new_of: dict[str, StoryCluster] = {m.fingerprint: c for c in clusters for m in c.members}
    feats = {fp: StoryFeatures.from_item(i) for fp, i in by_fp.items()}
    stats = name_statistics(feats.values())

    def pair(a: str, b: str) -> dict[str, Any]:
        d = match_story(feats[a], feats[b], name_stats=stats)
        return {
            "a": _brief(by_fp[a]), "b": _brief(by_fp[b]),
            "rule": d.rule if d else "none",
            "confidence": d.confidence if d else "none",
            "reason": d.reason if d else "no rule matches (or a veto separates them)",
        }

    merges: list[dict[str, Any]] = []
    for c in clusters:
        groups = {stored_of[m.fingerprint] for m in c.members}
        if len(groups) < 2:
            continue
        decisions = {d.fingerprint: d for d in c.decisions}
        joined = []
        for m in c.members[1:]:
            if stored_of[m.fingerprint] == stored_of[c.anchor.fingerprint]:
                continue
            d = decisions.get(m.fingerprint)
            joined.append({
                **_brief(by_fp[m.fingerprint]),
                "rule": d.rule if d else "none",
                "confidence": d.confidence if d else "none",
                "reason": d.reason if d else "",
            })
        merges.append({"new_story_key": c.key, "anchor": _brief(by_fp[c.anchor.fingerprint]),
                       "stored_groups": sorted(groups), "joined": joined,
                       "independent_sources": independent_sources(c)})

    splits: list[dict[str, Any]] = []
    for key, fps in stored.items():
        new_keys = {new_of[fp].key for fp in fps}
        if len(new_keys) < 2:
            continue
        canonical = next((fp for fp in fps if not by_fp[fp].duplicate_of), fps[0])
        separated = [fp for fp in fps if new_of[fp].key != new_of[canonical].key]
        rows = []
        for fp in separated:
            row = pair(canonical, fp)
            home = new_of[fp]
            mine = next((d for d in home.decisions if d.fingerprint == fp), None)
            link = next((d for d in home.links if d.fingerprint == fp), None)
            row["now_in_story_of"] = _brief(by_fp[home.anchor.fingerprint])
            row["now_because"] = (
                f"{mine.confidence}/{mine.rule}: {mine.reason}" if mine
                else "anchor of its own story" + (f"; {link.reason}" if link else "")
            )
            rows.append(row)
        splits.append({"stored_story_key": key, "canonical": _brief(by_fp[canonical]),
                       "separated": rows})

    links = [d.to_dict() for c in clusters for d in c.links]
    multi = [c for c in clusters if len(c.members) > 1]
    return {
        "generated_at": _now(),
        "dry_run": True,
        "items": len(items),
        "stored_stories": len(stored),
        "stored_multi_article": sum(1 for v in stored.values() if len(v) > 1),
        "recomputed_stories": len(clusters),
        "recomputed_multi_article": len(multi),
        "overrides": {"split": sorted(overrides.split), "merge": [list(p) for p in overrides.merge]},
        "changed_merges": merges,
        "changed_splits": splits,
        "low_confidence_links": links,
        "decisions_by_confidence": dict(Counter(d.confidence for c in clusters for d in c.decisions)),
        "decisions_by_rule": dict(Counter(d.rule for c in clusters for d in c.decisions)),
        "note": ("Stored keys were assigned incrementally at ingest (each new article matched "
                 "against the stored story's canonical); the recomputation is one batch "
                 "pass. Some differences come from that alone. Nothing was written."),
    }


# ---------------------------------------------------------------------------
# relevance-report
# ---------------------------------------------------------------------------

def build_relevance_report(
    items: Sequence[NewsItem], data_dir: Path, posts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    overrides = load_relevance_overrides(data_dir / "stories" / "relevance_overrides.json")
    apply_relevance_overrides(items, overrides)
    rows: list[dict[str, Any]] = []
    for i in items:
        status, reason = classify_scope(i)
        rows.append({**_brief(i), "status": status, "reason": reason,
                     "effective": i.relevance_override or status,
                     "category": i.category})
    by_fp = {r["fingerprint"]: r for r in rows}

    audit: list[dict[str, Any]] = []
    for fp in AUDIT_OFF_TOPIC:
        if fp in by_fp:
            r = by_fp[fp]
            audit.append({"fingerprint": fp, "basis": "source item", "title": r["title"],
                          "status": r["status"], "reason": r["reason"]})
            continue
        post = (posts or {}).get(f"{fp}:ua") or (posts or {}).get(f"{fp}:en")
        if not post:
            audit.append({"fingerprint": fp, "basis": "missing", "status": "unknown",
                          "reason": "no source item and no post in the snapshot"})
            continue
        # The source item has aged out of items.json. Classify the published
        # brief's headline + summary as a proxy (the brief's own text, so a
        # line like «не стосується кібербезпеки» can push it to review).
        proxy = NewsItem(title=str(post.get("title") or ""), source="archive",
                         url=f"archive:{fp}", published_at=datetime.now(timezone.utc),
                         raw_content=str(post.get("short_summary") or post.get("plain_summary") or ""),
                         language="ua")
        status, reason = classify_scope(proxy)
        audit.append({"fingerprint": fp, "basis": "published brief (proxy)",
                      "title": proxy.title, "status": status, "reason": reason})

    security_categories = {"vulnerability", "exploit", "zero-day", "breach", "ransomware",
                           "malware", "botnet", "spyware", "data leak", "phishing", "scam",
                           "social engineering"}
    suspicious = [r for r in rows if r["status"] == "out_of_scope"
                  and (r["category"] in security_categories)]
    return {
        "generated_at": _now(),
        "dry_run": True,
        "items": len(items),
        "by_status": dict(Counter(r["status"] for r in rows)),
        "by_effective_status": dict(Counter(r["effective"] for r in rows)),
        "overrides": len(overrides),
        "out_of_scope": [r for r in rows if r["status"] == "out_of_scope"],
        "needs_review": [r for r in rows if r["status"] == "needs_review"],
        "audit_off_topic": {
            "total": len(audit),
            "by_status": dict(Counter(a["status"] for a in audit)),
            "items": audit,
        },
        # Items the category classifier calls security but scope calls
        # out_of_scope — the place to look for false rejections.
        "security_category_but_out_of_scope": suspicious,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_items(data_dir: Path) -> list[NewsItem]:
    # JsonNewsStore parses datetimes; NewsItem(**raw) would leave strings and
    # break the clustering windows. Constructing it never writes.
    return JsonNewsStore(data_dir / "items.json").all()


def _edit_story_overrides(path: Path, kind: str, entry: dict[str, Any]) -> None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault("version", 1)
    raw.setdefault("split", [])
    raw.setdefault("merge", [])
    raw[kind].append(entry)
    _write_json(path, raw)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m cyberalertx.tools.stories",
                                 description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", help="defaults to the project's data/")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cluster-report", help="dry-run: stored story keys vs current algorithm")
    sub.add_parser("relevance-report", help="dry-run: scope classification of the snapshot")
    ov = sub.add_parser("relevance-override", help="record a manual scope decision")
    ov.add_argument("fingerprint")
    ov.add_argument("status", choices=RELEVANCE_STATUSES)
    ov.add_argument("--reason", required=True)
    sp = sub.add_parser("split", help="force an article out of its story")
    sp.add_argument("fingerprint")
    sp.add_argument("--reason", required=True)
    mg = sub.add_parser("merge", help="force two articles into one story (B joins A)")
    mg.add_argument("a")
    mg.add_argument("b")
    mg.add_argument("--reason", required=True)
    args = ap.parse_args(argv)
    data_dir = _data_dir(args.data_dir)
    stories = data_dir / "stories"

    if args.cmd == "cluster-report":
        report = build_cluster_report(_load_items(data_dir), data_dir)
        out = stories / "cluster_report.json"
        _write_json(out, report)
        print(f"{report['items']} articles: stored {report['stored_stories']} stories "
              f"({report['stored_multi_article']} multi-article), recomputed "
              f"{report['recomputed_stories']} ({report['recomputed_multi_article']}); "
              f"{len(report['changed_merges'])} changed merges, "
              f"{len(report['changed_splits'])} changed splits, "
              f"{len(report['low_confidence_links'])} low-confidence links")
        for m in report["changed_merges"]:
            print(f"\nMERGE  {m['anchor']['source']}: {m['anchor']['title']}")
            for j in m["joined"]:
                print(f"   + [{j['confidence']}/{j['rule']}] {j['source']}: {j['title']}"
                      f"\n       {j['reason']}")
        for s in report["changed_splits"]:
            print(f"\nSPLIT  {s['canonical']['source']}: {s['canonical']['title']}")
            for p in s["separated"]:
                print(f"   - {p['b']['source']}: {p['b']['title']}"
                      f"\n       pair vs canonical: [{p['confidence']}/{p['rule']}] {p['reason']}"
                      f"\n       now with: {p['now_in_story_of']['title'][:70]} ({p['now_because']})")
        print(f"\nwrote {out} (dry run: nothing else changed)", file=sys.stderr)
        return 0

    if args.cmd == "relevance-report":
        posts: dict[str, Any] = {}
        try:
            posts = json.loads((data_dir / "threat_posts.json").read_text(encoding="utf-8"))["posts"]
        except (OSError, ValueError, KeyError):
            pass
        report = build_relevance_report(_load_items(data_dir), data_dir, posts)
        out = stories / "relevance_report.json"
        _write_json(out, report)
        print(f"{report['items']} items: {report['by_status']}")
        print(f"audit off-topic set ({report['audit_off_topic']['total']}): "
              f"{report['audit_off_topic']['by_status']}")
        for r in report["out_of_scope"]:
            print(f"  out_of_scope  {r['fingerprint']} {r['source']}: {r['title'][:80]}  ({r['reason']})")
        for r in report["needs_review"]:
            print(f"  needs_review  {r['fingerprint']} {r['source']}: {r['title'][:80]}  ({r['reason']})")
        print(f"security-category items classified out_of_scope: "
              f"{len(report['security_category_but_out_of_scope'])}")
        print(f"wrote {out} (dry run: nothing else changed)", file=sys.stderr)
        return 0

    if args.cmd == "relevance-override":
        save_relevance_override(stories / "relevance_overrides.json",
                                args.fingerprint, args.status, args.reason)
        print(f"{args.fingerprint}: relevance_override = {args.status}")
        return 0

    path = stories / "overrides.json"
    if args.cmd == "split":
        _edit_story_overrides(path, "split", {"fingerprint": args.fingerprint,
                                              "reason": args.reason, "at": _now()})
        print(f"{args.fingerprint}: split recorded in {path}")
        return 0
    if args.cmd == "merge":
        _edit_story_overrides(path, "merge", {"fingerprints": [args.a, args.b],
                                              "reason": args.reason, "at": _now()})
        print(f"{args.b} joins {args.a}: merge recorded in {path}")
        return 0
    return 2  # pragma: no cover - argparse enforces the choices


__all__ = ["AUDIT_OFF_TOPIC", "build_cluster_report", "build_relevance_report",
           "effective_relevance", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
