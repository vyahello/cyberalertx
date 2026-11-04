"""`review score-archive`: score every cached post, change nothing.

Reads the post cache, the news store and (if present) the fact-sheet cache,
runs the same fact check, cross-locale check and scorecard the generator now
runs on new posts, and returns a report. The CLI writes it to
`data/editorial/archive_scores.json` and prints `format_summary`.

The cache is the only input that is never re-derived: nothing here calls a
model, writes a post, or touches review state.

Two caveats the summary prints, because they change how to read it:

  * Posts whose source article has aged out of the news store (the store
    keeps ~200 items; the cache keeps every render ever made) cannot be fact-
    checked. Their accuracy dimension is skipped and the total rescaled.
  * Every archived post was written by an OLDER prompt, without a fact
    sheet. The flag rate measures the back catalogue, not what the new
    pipeline will produce.
"""
from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from .fact_check import check_cross_locale, check_item
from .models import ThreatPost
from .review import post_key
from .scorecard import score_post

SWEEP: tuple[int, ...] = (50, 60, 70, 75, 80, 85, 88, 90, 92, 95)


def score_archive(
    posts: Iterable[ThreatPost],
    items: Mapping[str, Any],
    *,
    threshold: int,
    sheet_for: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    by_key: dict[str, ThreatPost] = {}
    for post in posts:
        if post.source_fingerprint:
            by_key[post_key(post)] = post

    rows: list[dict[str, Any]] = []
    for key in sorted(by_key):
        post = by_key[key]
        fp, locale = key.rsplit(":", 1)
        item = items.get(fp)
        sheet = sheet_for(fp) if sheet_for else None
        report = check_item(post, item, sheet) if item is not None else None
        cross = []
        # Live, the cross-locale check runs when the SECOND locale is written,
        # which is UA for an English-source story. Mirror that here so a
        # disagreement flags one post, not both.
        if locale == "ua" and f"{fp}:en" in by_key:
            other = by_key[f"{fp}:en"]
            if other.generated_by != "rule_based" and post.generated_by != "rule_based":
                cross = check_cross_locale(other, post, locale_a="en", locale_b="ua")
        card = score_post(post, language=locale, item=item, sheet=sheet,
                          fact_report=report, cross_locale=cross, threshold=threshold)
        forced = any(i.severity == "hard" or i.code == "cross_locale_conflict"
                     for i in card.issues)
        rows.append({
            "key": key,
            "locale": locale,
            "title": post.title,
            "generated_by": post.generated_by,
            "review_status": post.review_status,
            "in_store": item is not None,
            "in_feed_pool": bool(item is not None and not getattr(item, "duplicate_of", "")
                                 and _feed_locale_ok(item, locale)),
            "score": card.score,
            "needs_review": card.needs_review,
            "forced": forced,
            "review_reasons": card.review_reasons,
            "dimensions": {k: round(v, 1) for k, v in card.dimensions.items()},
            "issues": [i.to_dict() for i in card.issues if i.severity != "info"],
            "fact_check": report.to_dict() if report is not None else None,
        })
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "threshold": threshold,
        "note": ("Internal editorial indicator, not an objective quality measure. "
                 "Archived posts predate the fact-sheet stage and the current prompts."),
        "summary": summarize(rows, threshold),
        "posts": rows,
    }


def _feed_locale_ok(item: Any, locale: str) -> bool:
    """Mirrors /posts: the EN page shows EN-source items only; UA shows both."""
    lang = getattr(item, "language", "en") or "en"
    return lang == "en" if locale == "en" else lang in ("en", "ua")


def _flagged(row: Mapping[str, Any], threshold: int) -> bool:
    return bool(row["forced"]) or int(row["score"]) < threshold


def summarize(rows: list[dict[str, Any]], threshold: int) -> dict[str, Any]:
    out: dict[str, Any] = {"locales": {}, "sweep": {}, "top_issues": {}, "hard_kinds": {}}
    for locale in sorted({r["locale"] for r in rows}):
        sub = [r for r in rows if r["locale"] == locale]
        scores = [int(r["score"]) for r in sub]
        checked = [r for r in sub if r["in_store"]]
        hist = Counter(min(s // 10, 9) for s in scores)
        out["locales"][locale] = {
            "posts": len(sub),
            "source_checked": len(checked),
            "mean": round(statistics.mean(scores), 1) if scores else None,
            "median": statistics.median(scores) if scores else None,
            "p10": _pct(scores, 10), "p25": _pct(scores, 25), "p75": _pct(scores, 75),
            "histogram": {f"{b * 10}-{b * 10 + 9 if b < 9 else 100}": hist.get(b, 0)
                          for b in range(10)},
            "flagged": sum(1 for r in sub if _flagged(r, threshold)),
            "flagged_pct": _rate(sum(1 for r in sub if _flagged(r, threshold)), len(sub)),
            "flagged_pct_source_checked": _rate(
                sum(1 for r in checked if _flagged(r, threshold)), len(checked)),
            "forced_by_fact_or_cross_locale": sum(1 for r in sub if r["forced"]),
            "feed_pool": sum(1 for r in sub if r["in_feed_pool"]),
            "feed_pool_visible_in_hold": sum(
                1 for r in sub if r["in_feed_pool"] and not _flagged(r, threshold)),
        }
        out["sweep"][locale] = {
            str(t): {
                "flagged_pct": _rate(sum(1 for r in sub if _flagged(r, t)), len(sub)),
                "flagged_pct_source_checked": _rate(
                    sum(1 for r in checked if _flagged(r, t)), len(checked)),
                "feed_pool_visible_in_hold": sum(
                    1 for r in sub if r["in_feed_pool"] and not _flagged(r, t)),
            }
            for t in SWEEP
        }
        codes: Counter[str] = Counter()
        hard: Counter[str] = Counter()
        for r in sub:
            codes.update({i["code"] for i in r["issues"]})
            hard.update({i["code"] for i in r["issues"] if i["severity"] == "hard"})
        out["top_issues"][locale] = dict(codes.most_common(15))
        out["hard_kinds"][locale] = dict(hard.most_common())
    return out


def _pct(values: list[int], q: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q / 100 * (len(ordered) - 1))))
    return float(ordered[idx])


def _rate(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def format_summary(report: Mapping[str, Any]) -> str:
    s = report["summary"]
    t = report["threshold"]
    lines = [f"Archive scorecard (threshold {t}; internal indicator, not a truth measure)"]
    for locale, d in s["locales"].items():
        lines.append(
            f"\n[{locale.upper()}] {d['posts']} posts, {d['source_checked']} fact-checked "
            f"(source still stored) | mean {d['mean']} median {d['median']} "
            f"p10 {d['p10']} p25 {d['p25']} p75 {d['p75']}"
        )
        lines.append("  histogram: " + "  ".join(f"{k}:{v}" for k, v in d["histogram"].items()))
        lines.append(
            f"  flagged: {d['flagged']} ({d['flagged_pct']}%) — of fact-checked posts "
            f"{d['flagged_pct_source_checked']}%; forced by a hard fact or EN/UA conflict: "
            f"{d['forced_by_fact_or_cross_locale']}"
        )
        lines.append(f"  feed pool (stored, canonical): {d['feed_pool']} posts, "
                     f"{d['feed_pool_visible_in_hold']} would stay visible in hold mode")
        sweep = s["sweep"][locale]
        lines.append("  threshold sweep — t: flagged% all / flagged% fact-checked / "
                     "feed pool visible in hold:")
        lines.append("    " + "  ".join(
            f"{k}: {v['flagged_pct']}%/{v['flagged_pct_source_checked']}%/"
            f"{v['feed_pool_visible_in_hold']}" for k, v in sweep.items()))
        lines.append("  top issues: " + ", ".join(f"{k} {v}" for k, v in s["top_issues"][locale].items()))
        if s["hard_kinds"][locale]:
            lines.append("  hard: " + ", ".join(f"{k} {v}" for k, v in s["hard_kinds"][locale].items()))
    return "\n".join(lines)


__all__ = ["SWEEP", "format_summary", "score_archive", "summarize"]
