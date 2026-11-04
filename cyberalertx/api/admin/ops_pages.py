"""Control-room pages: overview sections, Stories, Usage, System health, Search.

All data comes from `cyberalertx.ops` read models over the existing stores.
Every number says what it counts (articles vs stories), over what period
(Kyiv day, since metrics start, last shadow run) and from where. Empty
sources render as "no record", never as zero activity or as healthy.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

from .ui import esc, num, page, panel, pill, tile

_TONE = {"healthy": "ok", "warning": "warn", "critical": "bad", "unknown": "neutral",
         "not_configured": "neutral", "manual": "accent"}
_LABEL = {"healthy": "healthy", "warning": "warning", "critical": "critical", "unknown": "no record",
          "not_configured": "not configured", "manual": "manual"}
_JOB_TONE = {"published": "ok", "scheduled": "neutral", "processing": "accent", "retrying": "warn",
             "failed": "bad", "outcome_unknown": "bad", "cancelled": "neutral"}


def status_pill(status: str) -> str:
    return pill(_LABEL.get(status, status), _TONE.get(status, "neutral"))


def when(dt: datetime | None, now: datetime) -> str:
    if dt is None:
        return '<span style="color:var(--faint)">—</span>'
    secs = (now - dt).total_seconds()
    rel = ("just now" if secs < 60 else f"{int(secs // 60)} min ago" if secs < 3600 else
           f"{int(secs // 3600)} h ago" if secs < 86400 else f"{int(secs // 86400)} d ago") if secs >= 0 else "scheduled"
    return f'<time datetime="{dt.isoformat()}" title="{dt.astimezone(timezone.utc):%Y-%m-%d %H:%M UTC}">{rel}</time>'


def _opt(name: str, value: str, options: Sequence[tuple[str, str]]) -> str:
    return (f'<select name="{name}">' + "".join(
        f'<option value="{esc(v)}"{" selected" if v == value else ""}>{esc(lbl)}</option>' for v, lbl in options)
        + "</select>")


def _pager(base: str, params: Mapping[str, Any], page_no: int, total: int, size: int) -> str:
    pages = max(1, (total + size - 1) // size)
    def link(n: int, label: str) -> str:
        q = urlencode({**{k: v for k, v in params.items() if v not in ("", None)}, "page": n})
        return f'<a href="{esc(base)}?{esc(q)}">{label}</a>'
    prev = link(page_no - 1, "← Newer") if page_no > 1 else ""
    nxt = link(page_no + 1, "Older →") if page_no < pages else ""
    return f'<div class="pager"><span>{num(total)} total · page {page_no} of {pages}</span><span>{prev} {nxt}</span></div>'


# ---------------------------------------------------------------- overview sections

def overview_sections(*, m: Mapping[str, Any], stages: Sequence[Any], dests: Sequence[Any], res: Any,
                      rows: Sequence[Any], events: Sequence[Any], now: datetime) -> str:
    day = m["day"].strftime("%d %b")
    jobs = m["jobs"]
    tiles = "".join([
        tile(f"Stories · {day}", num(m["stories_today"]),
             f"{num(m['in_scope_today'])} in scope · from {num(m['articles_today'])} articles fetched", href="/admin/stories"),
        tile("Awaiting review", num(m["pending_stories"]),
             f"stories · {num(m['pending_editions'])} editions pending", tone="warn" if m["pending_editions"] else "",
             href="/admin/review"),
        tile(f"Delivered · {day}", num(m["jobs_published_today"] + m["telegram_sent_today"]),
             f"{num(m['telegram_sent_today'])} Telegram (ledger) · {num(m['jobs_published_today'])} via jobs",
             href="/admin/publishing"),
        tile("Delivery problems", num(jobs["failed"] + jobs["outcome_unknown"]),
             (f"{num(jobs['failed'])} failed · {num(jobs['outcome_unknown'])} unknown · "
              f"{num(jobs['scheduled'] + jobs['retrying'])} waiting") if m["jobs_active"] else "job worker not active",
             tone="bad" if jobs["outcome_unknown"] else "warn" if jobs["failed"] else "", href="/admin/publishing"),
        tile("Daily Top 10", "—" if m["top10"] is None else num(m["top10"]),
             (f"edition {esc(m['edition'])} · {num(m['breaking'] or 0)} breaking · {num(m['trending'] or 0)} trending")
             if m["top10"] is not None else "intelligence view unavailable", href="/admin/intel"),
    ])
    note = (f'<footer style="margin-top:8px">Stories are Intelligence Core clusters; articles are source items. '
            f'Days are Kyiv editorial days ({day}). Selection counts are the live view (not published).</footer>')

    flow = '<div class="flow">' + "".join(
        f'<div class="st"><h4>{esc(s.name)}</h4><p>{status_pill(s.status)} {esc(s.last_label)} {when(s.last, now)}</p>'
        f'<dl>' + "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in s.counts) + "</dl>"
        + (f'<p style="margin-top:6px;font-size:12px;color:var(--faint)">{esc(s.note)}</p>' if s.note else "")
        + (f'<p style="margin-top:4px"><a href="{esc(s.href)}">Open →</a></p>' if s.href else "")
        + "</div>" for s in stages) + "</div>"

    drows = "".join(
        f"<tr><td><b>{esc(d.label)}</b></td><td>{pill(d.configured, d.configured_tone)}"
        + (f" {pill(d.connected, 'ok' if d.connected.startswith('connected') else 'bad' if 'reconnect' in d.connected else 'neutral')}"
           if d.connected else "")
        + "</td>" + "".join(f"<td class=n>{num(d.counts.get(s, 0))}</td>" for s in
                            ("published", "scheduled", "retrying", "failed", "outcome_unknown"))
        + f"<td class=n>{when(d.last_published, now)}</td></tr>" for d in dests)
    dest_table = ('<div class="scroll"><table><thead><tr><th>Destination</th><th>State</th><th class=n>Published</th>'
                  '<th class=n>Waiting</th><th class=n>Retrying</th><th class=n>Failed</th><th class=n>Unknown</th>'
                  f'<th class=n>Last delivery</th></tr></thead><tbody>{drows}</tbody></table></div>')

    def story_list(items: Sequence[Any], empty: str) -> str:
        if not items:
            return f'<p class="empty">{esc(empty)}</p>'
        return "<ul class=events>" + "".join(
            f'<li><span>{pill(f"{r.score:.0f}" if r.score is not None else "—", "accent")}</span>'
            f'<span class=k>{esc(r.confidence or "")}</span>'
            f'<span class=t><a href="/admin/stories/{esc(r.key)}">{esc(r.title)}</a></span></li>' for r in items) + "</ul>"
    top = sorted((r for r in rows if r.top_rank), key=lambda r: r.top_rank or 99)[:10]
    brk = [r for r in rows if r.breaking][:6]
    trend = [r for r in rows if r.trending][:6]
    lowc = sorted((r for r in rows if r.confidence == "low" and r.relevance != "out_of_scope"),
                  key=lambda r: -(r.score or 0))[:6]
    intel = ('<div class="cols" style="margin-top:0">'
             + panel("Daily Top 10 (live, not published)", story_list(top, "No story clears the threshold."),
                     padded=False, aside='<a href="/admin/stories?flag=top">All</a>')
             + panel("Breaking candidates", story_list(brk, "No story meets the evidence rules."), padded=False,
                     aside="never auto-published")
             + panel("Trending", story_list(trend, "Nothing trending."), padded=False)
             + panel("Low confidence, in scope", story_list(lowc, "None."), padded=False,
                     aside='<a href="/admin/stories?flag=low_confidence">All</a>')
             + "</div>")

    ev_html = ("<ul class=events>" + "".join(
        f'<li><span>{pill(e.kind, e.tone)}</span><span class=k>{when(e.at, now)}</span>'
        f'<span class=t>{f"<a href={chr(34)}{esc(e.href)}{chr(34)}>{esc(e.text)}</a>" if e.href else esc(e.text)}</span></li>'
        for e in events) + "</ul>") if events else '<p class="empty">No recorded events yet.</p>'

    return (f'<div class="grid full">{tiles}</div>{note}'
            + f'<div class="full">{panel("Pipeline", flow, padded=False, aside="from execution records; no record = no record")}</div>'
            + f'<div class="full">{panel("Destinations", dest_table, padded=False, aside="jobs + legacy Telegram ledger")}</div>'
            + f'<div class="full">{intel}</div>'
            + f'<div class="full">{panel("Recent activity", ev_html, padded=False, aside="recorded events only")}</div>')


# ---------------------------------------------------------------- stories

def render_stories(rows: Sequence[Any], total: int, q: Any, *, categories: Sequence[str], available: bool,
                   now: datetime) -> str:
    params = {"q": q.q, "min_score": "" if q.min_score is None else q.min_score, "confidence": q.confidence,
              "verification": q.verification, "exploitation": q.exploitation, "category": q.category,
              "relevance": q.relevance, "editorial": q.editorial, "flag": q.flag,
              "since": q.since.isoformat() if q.since else "", "until": q.until.isoformat() if q.until else "",
              "sort": q.sort}
    form = (
        '<form class="filters" method="get" action="/admin/stories">'
        f'<label>Search<input type="search" name="q" value="{esc(q.q)}" placeholder="headline or ID"></label>'
        f'<label>Min score<input type="number" name="min_score" min="0" max="100" step="1" style="width:80px" '
        f'value="{esc(params["min_score"])}"></label>'
        f'<label>Confidence{_opt("confidence", q.confidence, [("", "any"), ("high", "high"), ("medium", "medium"), ("low", "low")])}</label>'
        f'<label>Verification{_opt("verification", q.verification, [("", "any"), ("verified", "verified"), ("partially_verified", "partial"), ("unverified", "unverified")])}</label>'
        f'<label>Exploitation{_opt("exploitation", q.exploitation, [("", "any"), ("confirmed", "confirmed"), ("reported", "reported"), ("poc_available", "PoC"), ("unknown", "unknown")])}</label>'
        f'<label>Category{_opt("category", q.category, [("", "any")] + [(c, c.replace("_", " ")) for c in categories])}</label>'
        f'<label>Relevance{_opt("relevance", q.relevance, [("", "any"), ("in_scope", "in scope"), ("borderline", "borderline"), ("out_of_scope", "out of scope")])}</label>'
        f'<label>Editorial{_opt("editorial", q.editorial, [("", "any"), ("pending", "pending"), ("approved", "approved"), ("rejected", "rejected"), ("auto", "unreviewed"), ("missing", "no brief")])}</label>'
        f'<label>Selection{_opt("flag", q.flag, [("", "any"), ("top", "Daily Top 10"), ("trending", "trending"), ("breaking", "breaking"), ("low_confidence", "low confidence")])}</label>'
        f'<label>From<input type="date" name="since" value="{esc(params["since"])}"></label>'
        f'<label>To<input type="date" name="until" value="{esc(params["until"])}"></label>'
        f'<label>Sort{_opt("sort", q.sort, [("score", "importance"), ("latest", "newest"), ("articles", "most articles")])}</label>'
        '<button class="btn" type="submit">Apply</button> <a href="/admin/stories" style="padding:7px 4px">Reset</a></form>')
    if not available:
        body = form + panel("Stories", '<p class="empty">The Intelligence Core view could not be computed. '
                            'See System health.</p>', padded=False)
        return page(active="stories", title="Stories", subtitle="", body=body, now=now)

    def ed(e: Mapping[str, str]) -> str:
        tone = {"pending": "warn", "approved": "ok", "rejected": "bad", "auto": "neutral", "missing": "neutral"}
        return " ".join(pill(f"{loc.upper()} {s if s != 'auto' else 'live'}", tone.get(s, "neutral"))
                        for loc, s in e.items())
    trs = "".join(
        f"<tr><td><a href='/admin/stories/{esc(r.key)}'><b>{esc(r.title)}</b></a>"
        f"<div style='color:var(--faint);font-size:12px' class=mono>{esc(r.key)} · {r.articles} article"
        f"{'s' if r.articles != 1 else ''} · {esc(', '.join(r.sources[:3]))}</div></td>"
        f"<td class=n>{'—' if r.score is None else f'{r.score:.0f}'}</td>"
        f"<td>{esc(r.confidence)}<br><small style='color:var(--faint)'>{esc(r.verification.replace('_', ' '))}</small></td>"
        f"<td class=hide-xs>{esc(r.exploitation)}</td><td class=hide-xs>{esc(r.category.replace('_', ' '))}<br>"
        f"<small style='color:var(--faint)'>{esc(r.relevance.replace('_', ' '))}</small></td>"
        f"<td>{(pill(f'Top {r.top_rank}', 'accent') + ' ') if r.top_rank else ''}"
        f"{(pill('breaking', 'bad') + ' ') if r.breaking else ''}{pill('trending', 'warn') if r.trending else ''}"
        f"{'' if r.fact_sheet else pill('no fact sheet', 'neutral')}</td>"
        f"<td>{ed(r.editions)}</td><td class=n>{when(r.latest, now)}</td></tr>" for r in rows)
    table = ('<div class="scroll"><table><thead><tr><th>Story</th><th class=n>Score</th><th>Confidence</th>'
             '<th class=hide-xs>Exploitation</th><th class=hide-xs>Category</th><th>Selection</th><th>Editions</th>'
             f'<th class=n>Latest</th></tr></thead><tbody>{trs}</tbody></table></div>') if rows else \
        '<p class="empty">No story matches these filters.</p>'
    body = form + panel("Stories", table + _pager("/admin/stories", params, q.page, total, 50), padded=False,
                        aside="Intelligence Core clusters · live view, cached 10 min")
    return page(active="stories", title="Stories",
                subtitle="Every story the Intelligence Core knows: score, confidence, verification, exploitation, "
                         "selection and editorial state per edition.", body=body, now=now, query=q.q)


def render_story(d: Mapping[str, Any], *, jobs: Sequence[Any], assets: Sequence[Mapping[str, Any]],
                 now: datetime) -> str:
    s, ev = d["story"], d["evaluation"]
    title = (getattr(s.posts.get("en"), "title", "") or getattr(s.posts.get("ua"), "title", "") or s.anchor.title)
    dims = ev.dimensions if ev else {}
    summary = (
        '<dl class="kv">'
        f"<dt>Story key</dt><dd class=mono>{esc(s.key)}</dd>"
        f"<dt>Relevance</dt><dd>{esc(s.relevance.replace('_', ' '))}</dd>"
        f"<dt>Importance</dt><dd>{'—' if ev is None else f'{ev.score:.1f} / 100'} "
        f"<small style='color:var(--faint)'>calculation {esc(ev.calculation_version) if ev else ''}</small></dd>"
        + "".join(f"<dt>{esc(k.replace('_', ' '))}</dt><dd>{pill(str(v.get('value', '—')), 'neutral')} "
                  f"<small style='color:var(--muted)'>{esc('; '.join(v.get('reasons', [])))}</small></dd>"
                  for k, v in dims.items())
        + f"<dt>Selection</dt><dd>{('Daily Top 10 #' + str(d['top']['rank'])) if d['top'] else 'not in the Top 10'}"
        + (" · trending" if d["trending"] else "") + (" · <b>breaking candidate</b>" if d["breaking"] else "") + "</dd>"
        + f"<dt>Independent sources</dt><dd>{esc(', '.join(s.independent_sources) or '—')}</dd>"
        + f"<dt>Fact sheets</dt><dd>{d['sheets']} of {len(s.members)} articles"
        + ("" if d["has_evidence"] else " · <span style='color:var(--warn)'>no cluster evidence</span>") + "</dd></dl>")
    comps = ""
    if ev:
        comps = ("<table><thead><tr><th>Component</th><th class=n>Points</th><th>Why</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{esc(k.replace('_', ' '))}</td><td class=n>{v:.1f}</td><td>{esc('; '.join(ev.reasons.get(k, [])))}</td></tr>"
            for k, v in sorted(ev.components.items(), key=lambda kv: -kv[1])) + "</tbody></table>")
    members = "<table><thead><tr><th>Article</th><th>Source</th><th class=n>Published</th></tr></thead><tbody>" + "".join(
        f"<tr><td><a href='{esc(m.url)}' rel='noopener noreferrer'>{esc(m.title)}</a>"
        f"<div class=mono style='color:var(--faint);font-size:12px'>{esc(m.fingerprint)}"
        f"{' · anchor' if m.fingerprint == s.anchor.fingerprint else ''}</div></td>"
        f"<td>{esc(m.source)}</td><td class=n>{when(m.published_at, now)}</td></tr>" for m in s.members) + "</tbody></table>"

    def facts(items: Sequence[Any], empty: str) -> str:
        if not items:
            return f'<p class="empty" style="padding:12px 0">{esc(empty)}</p>'
        return "<ul class=findings>" + "".join(
            f"<li>{pill(getattr(f, 'kind', ''), 'neutral')} <span>{esc(getattr(f, 'value', ''))} "
            f"<small style='color:var(--faint)'>— {esc(', '.join(getattr(f, 'sources', []) or []))}</small></span></li>"
            for f in items) + "</ul>"
    evidence = (
        "<h3>Confirmed (two independent origins or a primary source)</h3>" + facts(d["confirmed"], "None confirmed.")
        + "<h3>Reported, not confirmed</h3>" + facts(d["reported"], "None.")
        + "<h3>Claims as attributed by the articles</h3>"
        + ("<ul class=findings>" + "".join(f"<li>{pill(c['status'], 'neutral')} <span>{esc(c['statement'])} "
                                           f"<small style='color:var(--faint)'>— {esc(c['attribution'])}</small></span></li>"
                                           for c in d["claims"][:20]) + "</ul>" if d["claims"] else "<p class=empty style='padding:12px 0'>None.</p>")
        + "<h3>Contradictions</h3>"
        + ("<ul class=findings>" + "".join(f"<li>{pill('disputed', 'warn')} <span>{esc(c.statement)} "
                                           f"<small style='color:var(--faint)'>— {esc(', '.join(c.sources))}</small></span></li>"
                                           for c in d["contradictions"]) + "</ul>" if d["contradictions"] else "<p class=empty style='padding:12px 0'>None recorded.</p>")
        + "<h3>Unknowns</h3>"
        + ("<ul>" + "".join(f"<li>{esc(u)}</li>" for u in d["unknowns"]) + "</ul>" if d["unknowns"] else "<p class=empty style='padding:12px 0'>None recorded.</p>")
        + "<h3>Identifiers and affected products</h3>"
        + ("<dl class=kv>" + "".join(f"<dt>{esc(k)}</dt><dd class=mono>{esc(', '.join(v))}</dd>" for k, v in d["identifiers"].items())
           + "</dl>" if d["identifiers"] else "<p class=empty style='padding:12px 0'>None extracted.</p>"))
    if not d["has_evidence"] and not d["sheets"]:
        evidence = ('<p class="empty">No fact sheet has been extracted for this story, so there is no verified '
                    "evidence to show. Nothing is inferred in its place.</p>")
    def dec_row(x: Any) -> str:
        x = x if isinstance(x, Mapping) else {"reason": str(x)}
        tone = {"high": "ok", "medium": "warn", "low": "bad"}.get(str(x.get("confidence", "")), "neutral")
        return (f"<tr><td class=mono>{esc(x.get('fingerprint', ''))}</td><td class=mono>{esc(x.get('rule', ''))}</td>"
                f"<td>{pill(str(x.get('confidence', '—')), tone)}</td><td>{esc(x.get('reason', ''))}</td></tr>")
    decisions = ("<div class=scroll><table><thead><tr><th>Article joined</th><th>Rule</th><th>Confidence</th><th>Reason</th>"
                 "</tr></thead><tbody>" + "".join(dec_row(x) for x in s.decisions[:30]) + "</tbody></table></div>"
                 ) if s.decisions else '<p class="empty" style="padding:12px 0">No matching decisions recorded for this story.</p>'
    eds = "".join(
        f"<tr><td>{loc.upper()}</td><td>{esc(getattr(p, 'title', ''))}</td>"
        f"<td>{pill(getattr(p, 'review_status', 'auto') or 'auto', 'neutral')}</td>"
        f"<td><a href='/{'ua' if loc == 'ua' else 'en'}/threat/{esc(s.anchor.fingerprint)}' target=_blank rel='noopener noreferrer'>site ↗</a> · "
        f"<a href='/admin/review?status={esc(getattr(p, 'review_status', 'auto') or 'auto')}'>review</a></td></tr>"
        for loc, p in sorted(s.posts.items()))
    job_rows = "".join(
        f"<tr><td>{esc(j.destination)} {esc(j.locale.upper())}</td><td>{pill(j.status, _JOB_TONE.get(j.status, 'neutral'))}</td>"
        f"<td class=mono>{esc(j.job_id)}</td><td>{esc(j.external_id or '—')}</td></tr>" for j in jobs)
    media_rows = "".join(f"<tr><td>{esc(a.get('asset_type', ''))} {esc(a.get('locale', ''))}</td>"
                         f"<td>{pill(str(a.get('status', '')), 'neutral')}</td>"
                         f"<td class=mono style='overflow-wrap:anywhere'>{esc(a.get('asset_id', ''))}</td></tr>" for a in assets)
    body = (
        '<div class="cols" style="margin-top:0">'
        + panel("Intelligence", summary)
        + panel("Score breakdown", comps or '<p class="empty">Not scored.</p>', padded=False)
        + "</div>"
        + f'<div class="full">{panel(f"Source articles ({len(s.members)})", members, padded=False)}</div>'
        + f'<div class="full">{panel("Evidence", evidence)}</div>'
        + '<div class="cols">'
        + panel("Editions", f"<table><tbody>{eds}</tbody></table>" if eds else '<p class="empty">No brief yet.</p>', padded=False)
        + panel("Publication jobs", f"<table><tbody>{job_rows}</tbody></table>" if job_rows else
                '<p class="empty">No publication jobs.</p>', padded=False)
        + panel("Media", f"<table><tbody>{media_rows}</tbody></table>" if media_rows else '<p class="empty">No media records.</p>', padded=False)
        + "</div>"
        + f'<div class="full">{panel("Clustering decisions", decisions, padded=not s.decisions, aside="corrections: python -m cyberalertx.tools.stories split / merge (existing overrides)")}</div>'
    )
    return page(active="stories", title=title, body=body, now=now, crumbs=[("Stories", "/admin/stories"), ("@key:" + s.key, "")],
                subtitle="Confirmed facts, reported claims, contradictions and unknowns are kept apart exactly as "
                         "the evidence records them.")


# ---------------------------------------------------------------- usage

def render_usage(*, counters: Mapping[str, Any], first_seen: str, daily: Mapping[str, Any], monthly: Mapping[str, Any],
                 ledger_start: str, media_usage: Sequence[Mapping[str, Any]], controls: Sequence[tuple[str, str, str]],
                 rates_configured: bool, period: str, now: datetime) -> str:
    def cum(provider: str) -> str:
        def c(k: str) -> int:
            return int(counters.get(f"{provider}_{k}") or 0)
        return (f"<tr><td><b>{esc(provider)}</b></td><td class=n>{num(c('calls'))}</td><td class=n>{num(c('input_tokens'))}</td>"
                f"<td class=n>{num(c('output_tokens'))}</td><td class=n>{num(c('cache_read_tokens'))}</td>"
                f"<td class=n>{num(c('cache_write_tokens'))}</td><td>{pill('unavailable', 'neutral')}</td></tr>")
    cumulative = ('<div class="scroll"><table><thead><tr><th>Provider</th><th class=n>Calls</th><th class=n>Input</th>'
                  '<th class=n>Output</th><th class=n>Cache read</th><th class=n>Cache write</th><th>Cost</th></tr></thead>'
                  f'<tbody>{cum("anthropic")}{cum("claude_cli")}</tbody></table></div>')
    data = daily if period == "day" else monthly
    rows = ""
    for label, buckets in list(data.items())[:62]:
        for (prov, model, stage), b in sorted(buckets.items()):
            if b.estimated_calls == b.calls:
                cost = f"${b.estimated_usd:.2f} {pill('estimated', 'warn')}"
            elif b.estimated_calls:
                cost = (f"${b.estimated_usd:.2f} {pill('partial estimate', 'warn')} "
                        f"<small style='color:var(--faint)'>{b.unavailable_calls} calls unpriced</small>")
            else:
                cost = pill("unavailable", "neutral")
            rows += (f"<tr><td>{esc(label)}</td><td>{esc(prov)}</td><td class=mono>{esc(model or '—')}</td><td>{esc(stage)}</td>"
                     f"<td class=n>{num(b.calls)}</td><td class=n>{num(b.input_tokens)}</td><td class=n>{num(b.output_tokens)}</td>"
                     f"<td class=n>{num(b.cache_read_tokens + b.cache_write_tokens)}</td><td>{cost}"
                     + (f" <small style='color:var(--faint)'>{esc(', '.join(sorted(b.sources)))}</small>" if b.sources else "")
                     + "</td></tr>")
    tabs = (f'<div class="tabs"><a href="/admin/usage?period=day"{" aria-current=page" if period == "day" else ""}>Daily (Kyiv)</a>'
            f'<a href="/admin/usage?period=month"{" aria-current=page" if period != "day" else ""}>Monthly</a></div>')
    ledger = (tabs + '<div class="scroll"><table><thead><tr><th>Period</th><th>Provider</th><th>Model</th><th>Stage</th>'
              '<th class=n>Calls</th><th class=n>Input</th><th class=n>Output</th><th class=n>Cache</th><th>Cost</th></tr></thead>'
              f'<tbody>{rows}</tbody></table></div>') if rows else (
        tabs + '<p class="empty">No calls recorded in the usage ledger yet. It starts with this release; '
               "earlier usage exists only as the cumulative counters above.</p>")
    img_ok = sum(1 for u in media_usage if u.get("ok"))
    img_cost = [float(u["cost_usd"]) for u in media_usage if u.get("cost_usd") not in (None, "")]
    images = (f"<dl class=kv><dt>Calls recorded</dt><dd>{num(len(media_usage))} ({num(img_ok)} ok)</dd>"
              f"<dt>Cost reported by provider</dt><dd>{f'${sum(img_cost):.2f}' if img_cost else pill('none recorded', 'neutral')}</dd></dl>")
    ctrl = "<table><tbody>" + "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td><td><small style='color:var(--faint)'>{esc(n)}</small></td></tr>"
                                      for k, v, n in controls) + "</tbody></table>"
    body = (
        '<div class="banner"><span class="dot accent"></span><p><b>How cost is shown.</b> No provider here returns a '
        "billed amount, so nothing is <i>measured</i>. <i>Estimated</i> means the Claude CLI's own cost figure "
        "(notional on a subscription login) or token counts × rates you configured in "
        "<span class=mono>CYBERALERTX_AI_PRICES</span>"
        + (" (configured)." if rates_configured else " (not configured).")
        + " Everything else is <i>unavailable</i> — never shown as $0. Opening this page makes no AI call.</p></div>"
        + panel("Totals since metrics start", cumulative, padded=False,
                aside=f"cumulative counters since {esc(first_seen[:10] or '—')} · no dates, no cost")
        + f'<div class="full">{panel("Per call ledger", ledger, padded=False, aside=f"recorded since {esc(ledger_start[:10] or chr(8212))}")}</div>'
        + '<div class="cols">' + panel("Image generation", images) + panel("Cost controls (current settings)", ctrl, padded=False)
        + "</div>")
    return page(active="usage", title="AI usage", body=body, now=now,
                subtitle="Recorded provider calls and tokens, by day or month, model and pipeline stage.")


# ---------------------------------------------------------------- system

def render_system(report: Any, audit: Sequence[Mapping[str, Any]], *, now: datetime) -> str:
    groups: dict[str, list[Any]] = {}
    for c in report.checks:
        groups.setdefault(c.group, []).append(c)
    counts = {s: sum(1 for c in report.checks if c.status == s) for s in _LABEL}
    tiles = "".join([
        tile("Overall", _LABEL.get(report.overall, report.overall), "worst required check",
             tone={"healthy": "ok", "warning": "warn", "critical": "bad"}.get(report.overall, "")),
        tile("Healthy", num(counts["healthy"]), "checks"),
        tile("Warnings", num(counts["warning"]), "checks", tone="warn" if counts["warning"] else ""),
        tile("Critical", num(counts["critical"]), "checks", tone="bad" if counts["critical"] else ""),
        tile("Not configured", num(counts["not_configured"]), "optional — not failures"),
    ])
    sections = ""
    for g, cs in groups.items():
        trs = "".join(f"<tr><td><b>{esc(c.name)}</b></td><td>{status_pill(c.status)}</td><td>{esc(c.detail)}</td>"
                      f"<td class=n>{when(c.last, now)}</td><td>{f'<a href={chr(34)}{esc(c.href)}{chr(34)}>open</a>' if c.href else ''}</td></tr>"
                      for c in cs)
        sections += f'<div class="full">{panel(g, f"<div class=scroll><table><tbody>{trs}</tbody></table></div>", padded=False)}</div>'
    fails = "".join(
        f"<tr><td class=n>{esc(str(f.get('at') or '')[:16])}</td><td>{esc(f.get('where'))}</td>"
        f"<td class=mono>{esc(f.get('what'))}</td><td>{esc(f.get('error'))}</td>"
        f"<td>{pill('persistent', 'bad') if f.get('persistent') else pill('temporary', 'warn')}</td></tr>"
        for f in report.failures)
    fail_html = (f"<div class=scroll><table><thead><tr><th class=n>At</th><th>Where</th><th>What</th><th>Error</th>"
                 f"<th>Kind</th></tr></thead><tbody>{fails}</tbody></table></div>") if fails else \
        '<p class="empty">No recorded failures.</p>'
    aud = "".join(
        f"<tr><td class=n>{esc(str(a.get('at', ''))[:19])}</td><td>{esc(a.get('actor'))} "
        f"<small style='color:var(--faint)'>{esc(a.get('address'))}</small></td><td>{esc(a.get('action'))}</td>"
        f"<td class=mono>{esc(a.get('target'))}</td><td>{pill(str(a.get('result')), 'ok' if a.get('result') == 'ok' else 'bad')}</td></tr>"
        for a in audit)
    aud_html = (f"<div class=scroll><table><thead><tr><th class=n>At (UTC)</th><th>Actor</th><th>Action</th><th>Target</th>"
                f"<th>Result</th></tr></thead><tbody>{aud}</tbody></table></div>") if aud else \
        '<p class="empty">No administrative actions recorded yet.</p>'
    body = (f'<div class="grid">{tiles}</div>' + sections
            + f'<div class="full">{panel("Recorded failures", fail_html, padded=False, aside="persistent = failed / retries exhausted / needs an operator")}</div>'
            + f'<div class="full">{panel("Admin audit log (latest 50)", aud_html, padded=False, aside="data/admin_audit.jsonl")}</div>')
    return page(active="system", title="System health", body=body, now=now, json_href="/admin/system.json",
                subtitle="Real checks and records only. Probes are cached for a minute; no secret, connection "
                         "string or path is shown.")


# ---------------------------------------------------------------- search

def render_search(q: str, found: Mapping[str, Sequence[Any]], *, now: datetime) -> str:
    stories = "".join(f"<tr><td><a href='/admin/stories/{esc(r.key)}'>{esc(r.title)}</a></td>"
                      f"<td class=mono>{esc(r.key)}</td><td class=n>{'—' if r.score is None else f'{r.score:.0f}'}</td></tr>"
                      for r in found.get("stories", []))
    jobs = "".join(f"<tr><td class=mono><a href='/admin/publishing?q={esc(j.job_id)}'>{esc(j.job_id)}</a></td>"
                   f"<td>{pill(j.status, _JOB_TONE.get(j.status, 'neutral'))}</td><td>{esc(j.external_id or '—')}</td></tr>"
                   for j in found.get("jobs", []))
    body = (panel("Stories", f"<table><tbody>{stories}</tbody></table>" if stories else '<p class="empty">No story matches.</p>',
                  padded=False)
            + f'<div class="full">{panel("Publication jobs", f"<table><tbody>{jobs}</tbody></table>" if jobs else chr(60) + "p class=empty>No job matches." + chr(60) + "/p>", padded=False)}</div>')
    return page(active="", title=f"Search: {q}" if q else "Search", body=body, now=now, query=q,
                subtitle="Matches story keys, article fingerprints, headlines, job IDs and external post IDs.")


__all__ = ["overview_sections", "render_search", "render_stories", "render_story", "render_system", "render_usage",
           "status_pill", "when"]
