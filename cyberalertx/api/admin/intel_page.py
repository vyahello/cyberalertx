"""`/admin/intel` — read-only view of the shadow intelligence run.

Shows what `python -m cyberalertx.tools.intel evaluate` last computed
(data/intel/latest.json + scores.json): Daily Top 10 candidates, Trending,
Breaking, relevance counts, processing failures, and per story the score,
its components and reasons, confidence / verification / exploitation, the
independent sources and the clustering decisions. Token-locked by the same
admin gate as every /admin path; never linked from the public site.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .ui import esc, page, panel, pill

_TONE = {"verified": "ok", "partially_verified": "warn", "unverified": "bad",
         "high": "ok", "medium": "warn", "low": "bad",
         "confirmed": "bad", "reported": "warn", "poc_available": "warn", "unknown": "neutral"}


def _dims(d: Mapping[str, Any]) -> str:
    out = []
    for key, label in (("verification_status", "verification"), ("confidence", "confidence"),
                       ("exploitation_status", "exploitation")):
        v = str(d.get(key, {}).get("value", "—"))
        out.append(pill(f"{label}: {v}", _TONE.get(v, "neutral")))
    return " ".join(out)


def _story(key: str, rec: Mapping[str, Any]) -> str:
    cur = rec.get("current", {})
    comps = cur.get("components", {})
    reasons = cur.get("reasons", {})
    rows = "".join(
        f"<tr><td>{esc(k.replace('_', ' '))}</td><td class=num>{v:.1f}</td>"
        f"<td>{esc('; '.join(reasons.get(k, [])))}</td></tr>"
        for k, v in sorted(comps.items(), key=lambda kv: -kv[1])
    )
    dim_reasons = "".join(
        f"<li><b>{esc(k)}</b>: {esc('; '.join(v.get('reasons', [])))}</li>"
        for k, v in cur.get("dimensions", {}).items()
    )
    history = "".join(
        f"<li>{esc(h.get('evaluated_at', ''))} — {esc(h.get('score', ''))} "
        f"({esc('; '.join(h.get('changes', [])))})</li>" for h in rec.get("history", [])[:5]
    )
    return (
        f"<details><summary><b>{esc(cur.get('score', '—'))}</b> · {esc(key)} {_dims(cur.get('dimensions', {}))}"
        f"</summary><table><thead><tr><th>component</th><th>points</th><th>why</th></tr></thead>"
        f"<tbody>{rows}</tbody></table><ul>{dim_reasons}</ul>"
        f"<p><small>calculation {esc(cur.get('calculation_version', ''))} · evaluated "
        f"{esc(cur.get('evaluated_at', ''))} · changes: {esc('; '.join(cur.get('changes', [])))}</small></p>"
        + (f"<p><small>history</small></p><ul>{history}</ul>" if history else "")
        + "</details>"
    )


def render_intel(latest: Mapping[str, Any], scores: Mapping[str, Any], *, now: datetime) -> str:
    if not latest:
        body = panel("No run yet", '<p class="empty">Run <code>python -m cyberalertx.tools.intel '
                     'evaluate</code> to compute the shadow intelligence view.</p>', padded=False)
        return page(active="intel", title="Intelligence (shadow)", subtitle="", body=body, now=now,
                    json_href="/admin/intel.json")

    def pick_row(p: Mapping[str, Any]) -> str:
        return (f"<tr><td class=num>{esc(p.get('rank'))}</td><td>{esc(p.get('title'))}<br>"
                f"<small>{esc(' · '.join(p.get('why', [])))}</small></td>"
                f"<td class=num>{esc(p.get('selection_score'))}</td>"
                f"<td>{esc(p.get('verification'))} / {esc(p.get('confidence'))} / {esc(p.get('exploitation'))}</td>"
                f"<td>{esc(', '.join(p.get('sources', [])))}</td></tr>")

    top = "".join(pick_row(p) for p in latest.get("top", []))
    top_html = (f"<table><thead><tr><th>#</th><th>story</th><th>selection</th>"
                f"<th>verification / confidence / exploitation</th><th>independent sources</th></tr></thead>"
                f"<tbody>{top}</tbody></table>") if top else '<p class="empty">No story cleared the threshold.</p>'
    rejected = "".join(f"<li>{esc(r.get('title'))} — {esc(r.get('reason'))} ({esc(r.get('selection_score'))})</li>"
                       for r in latest.get("rejected", [])[:20])
    trend = "".join(f"<li><b>{esc(t.get('trend_score'))}</b> {esc(t.get('title'))} "
                    f"<small>({esc(', '.join(t.get('signals', [])))})</small></li>"
                    for t in latest.get("trending", []))
    brk = "".join(f"<li>{pill(str(b.get('alert')), 'bad')} {esc(', '.join(b.get('rules', [])))}: "
                  f"{esc(b.get('title'))}<br><small>{esc('; '.join(b.get('evidence', [])))}</small></li>"
                  for b in latest.get("breaking", []))
    fails = "".join(f"<li>{esc(f.get('story_key'))} [{esc(f.get('stage'))}]: {esc(f.get('error'))}</li>"
                    for f in latest.get("failures", []))
    rel = " · ".join(f"{esc(k)} {esc(v)}" for k, v in latest.get("relevance", {}).items())
    ranked = sorted(scores.items(), key=lambda kv: -float(kv[1].get("current", {}).get("score", 0)))[:60]
    stories = "".join(_story(k, v) for k, v in ranked)

    body = (
        panel(f"Daily Top 10 — edition {latest.get('edition', '')}", top_html, padded=False,
              aside="shadow only — not published")
        + panel("Left out", f"<ul>{rejected}</ul>" if rejected else '<p class="empty">None.</p>')
        + panel("Trending", f"<ul>{trend}</ul>" if trend else '<p class="empty">Nothing trending.</p>')
        + panel("Breaking candidates", f"<ul>{brk}</ul>" if brk else
                '<p class="empty">No story meets the evidence rules.</p>', aside="never auto-published")
        + panel("Stories by importance", stories or '<p class="empty">No scores.</p>',
                aside=f"{esc(latest.get('stories', 0))} stories · relevance {rel}")
        + panel("Processing failures", f"<ul>{fails}</ul>" if fails else '<p class="empty">None.</p>')
    )
    return page(active="intel", title="Intelligence (shadow)",
                subtitle=f"Evaluated {esc(latest.get('evaluated_at', ''))}. Shadow results only: "
                         "nothing here changes the feed, the API or Telegram.",
                body=body, now=now, json_href="/admin/intel.json")


__all__ = ["render_intel"]
