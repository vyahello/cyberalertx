"""The /admin pages: overview, feedback, content quality, sources.

Each renderer is a pure function of plain data, so the pages are tested by
calling them, not by standing up the pipeline. Everything printed that came
from outside — post ids from the public feedback POST, headlines, feed names,
validator messages — goes through `esc`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from ...feedback import FeedbackSummary
from .guard import GuardStats
from .ui import (
    Segment, ago, bar_rows, dot, esc, meter, num, page, panel, parse_time, pct,
    pill, ring, stack, tile, tone_for_rate,
)

TitleLookup = Callable[[str, str], str]

REASON_LABELS: dict[str, str] = {
    "too_vague": "Too vague",
    "too_technical": "Too technical",
    "incorrect": "Inaccurate",
    "not_relevant": "Not relevant to them",
}

#: Validator rejections, in the reader's terms rather than the counter's.
REJECT_LABELS: dict[str, str] = {
    "empty_field_rejects": "A required field came back empty",
    "cliche_rejects": "Used a banned AI cliché",
    "plagiarism_rejects": "Too close to the source text",
    "dup_rec_rejects": "Repeated the same recommendation",
    "title_echo_rejects": "Summary repeated the headline",
    "hallucinated_threat_level": "Invented a threat level",
}

# Freshness and health thresholds. Ingest runs every 30 minutes.
_INGEST_STOPPED = timedelta(hours=2)
_SOURCE_FAILING = timedelta(hours=6)
_SOURCE_QUIET = timedelta(hours=72)
_FEED_FRESH = timedelta(hours=12)
_FEED_STALE = timedelta(hours=48)
_LOGIN_NOISE = 10


@dataclass(frozen=True)
class FeedStatus:
    stored_items: int
    latest_published_at: datetime | None
    latest_urgent_at: datetime | None


@dataclass(frozen=True)
class SourceRow:
    name: str
    status: str          # "failing" | "quiet" | "healthy" | "new"
    reason: str
    stats: Mapping[str, Any]


# --------------------------------------------------------------------------
# Classification shared by the overview and the sources page
# --------------------------------------------------------------------------

def classify_sources(health: Mapping[str, Any], now: datetime) -> tuple[list[SourceRow], bool]:
    """Status per source, plus whether the ingest loop itself has stopped.

    A source is judged against the last ingest CYCLE, not the wall clock, so
    a stopped ingest shows up once as a banner instead of turning every feed
    red at the same moment.
    """
    last_cycle = parse_time(health.get("last_cycle_utc"))
    stopped = last_cycle is None or now - last_cycle > _INGEST_STOPPED
    reference = last_cycle or now
    rows: list[SourceRow] = []
    for name, stats in (health.get("sources") or {}).items():
        fetched_at = parse_time(stats.get("last_successful_ingest_utc"))
        published_at = parse_time(stats.get("last_published_at_utc"))
        if fetched_at is None:
            if int(stats.get("cycles_seen") or 0) >= 3:
                rows.append(SourceRow(name, "failing", "Has never returned an item", stats))
            else:
                rows.append(SourceRow(name, "new", "Not enough cycles yet", stats))
            continue
        gap = reference - fetched_at
        if gap > _SOURCE_FAILING:
            rows.append(SourceRow(name, "failing", f"No items fetched for {_span(gap)}", stats))
        elif published_at is not None and now - published_at > _SOURCE_QUIET:
            rows.append(SourceRow(name, "quiet", f"No new article for {_span(now - published_at)}", stats))
        else:
            rows.append(SourceRow(name, "healthy", "Fetching and publishing", stats))
    order = {"failing": 0, "quiet": 1, "new": 2, "healthy": 3}
    rows.sort(key=lambda r: (order[r.status], r.name.lower()))
    return rows, stopped


def _span(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    return f"{int(hours)} h" if hours < 48 else f"{int(hours // 24)} days"


_PROVIDER_NAMES = {"claude_cli": "Claude CLI", "anthropic": "Anthropic API"}

_STATUS_TONE = {"failing": "bad", "quiet": "warn", "healthy": "ok", "new": "neutral"}
_STATUS_LABEL = {"failing": "Failing", "quiet": "Quiet", "healthy": "Healthy", "new": "New"}


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _post_link(post_id: str, locale: str, title_for: TitleLookup) -> str:
    title = title_for(post_id, locale) or post_id
    return (f'<a href="/{esc(locale)}/threat/{esc(post_id)}" target="_blank" '
            f'rel="noopener noreferrer" class="trunc" title="{esc(title)}">{esc(title)}</a>')


# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------

def render_overview(
    *,
    feed: FeedStatus,
    metrics: Mapping[str, Any],
    health: Mapping[str, Any],
    feedback: FeedbackSummary,
    logins: GuardStats,
    title_for: TitleLookup,
    now: datetime,
) -> str:
    counters = metrics.get("counters") or {}
    sources, ingest_stopped = classify_sources(health, now)
    failing = [s for s in sources if s.status == "failing"]
    quiet = [s for s in sources if s.status == "quiet"]
    healthy = [s for s in sources if s.status == "healthy"]

    age = now - feed.latest_published_at if feed.latest_published_at else None
    feed_tone = ("bad" if age is None or age > _FEED_STALE else
                 "warn" if age > _FEED_FRESH else "ok")
    ai_rate = _rate(int(counters.get("ai_renders_success") or 0),
                    int(counters.get("ai_renders_attempted") or 0))
    ai_tone = tone_for_rate(ai_rate, good=0.8, fair=0.6)
    fb_tone = tone_for_rate(feedback.helpful_rate, good=0.7, fair=0.5)
    src_tone = "bad" if failing else "warn" if quiet else "ok" if sources else "neutral"
    login_tone = "warn" if logins.failed_24h >= _LOGIN_NOISE else "ok"
    since = parse_time(metrics.get("first_seen_utc"))

    tiles = "".join([
        tile("Latest article", ago(feed.latest_published_at, now, missing="none yet"),
             f"{num(feed.stored_items)} posts stored · last urgent "
             f"{ago(feed.latest_urgent_at, now, missing='none')}",
             tone=feed_tone, href="/admin/sources"),
        tile("Reader feedback", pct(feedback.helpful_rate),
             f"helpful · 👍 {num(feedback.up)} · 👎 {num(feedback.down)} · "
             f"{num(feedback.votes_last_7d)} votes this week",
             tone=fb_tone, href="/admin/feedback", visual=ring(feedback.helpful_rate, fb_tone)),
        tile("AI rendering", pct(ai_rate),
             f"accepted · {num(int(counters.get('ai_fallback_count') or 0))} fell back to "
             f"templates{' since ' + since.strftime('%d %b') if since else ''}",
             tone=ai_tone, href="/admin/metrics", visual=ring(ai_rate, ai_tone)),
        tile("Sources", f"{len(healthy)}<span style=\"color:var(--faint);font-size:18px\">"
             f" / {len(sources)}</span>",
             f"healthy · {len(failing)} failing · {len(quiet)} quiet",
             tone=src_tone, href="/admin/sources"),
        tile("Failed admin logins", num(logins.failed_24h),
             (f"in 24 h · from {logins.addresses_24h} "
              f"address{'es' if logins.addresses_24h != 1 else ''}"
              + (f" · {logins.locked_now} locked out now" if logins.locked_now else ""))
             if logins.failed_24h else "None in the last 24 h",
             tone=login_tone),
    ])

    alerts: list[tuple[str, str, str]] = []
    if ingest_stopped:
        alerts.append(("bad", "Ingest has stopped",
                       f"The last fetch cycle ran {ago(health.get('last_cycle_utc'), now)}. "
                       "Check <span class=mono>cyberalertx-run.service</span>."))
    if age is None or age > _FEED_STALE:
        alerts.append(("bad", "No new articles",
                       f"The newest stored article is {ago(feed.latest_published_at, now)}."))
    elif age > _FEED_FRESH:
        alerts.append(("warn", "The feed is slowing down",
                       f"The newest stored article is {ago(feed.latest_published_at, now)}."))
    if failing and not ingest_stopped:
        names = ", ".join(esc(s.name) for s in failing[:4])
        more = f" and {len(failing) - 4} more" if len(failing) > 4 else ""
        alerts.append(("bad", f"{len(failing)} source{'s' if len(failing) != 1 else ''} failing",
                       f'{names}{more}. <a href="/admin/sources">See sources</a>'))
    unhelpful = [p for p in feedback.posts if p.down >= 2 and p.down > p.up]
    if unhelpful:
        alerts.append(("warn", f"{len(unhelpful)} post{'s' if len(unhelpful) != 1 else ''} "
                       "readers found unhelpful",
                       f'Most 👎: {_post_link(unhelpful[0].id, unhelpful[0].locale, title_for)}'))
    if logins.failed_24h >= _LOGIN_NOISE:
        top = ", ".join(f"<span class=mono>{esc(a)}</span> ×{n}" for a, n in logins.top_addresses[:3])
        alerts.append(("warn", "Someone is trying admin passwords",
                       f"{num(logins.failed_24h)} failed attempts in 24 h. Most from {top}. "
                       "Each address is locked out after 5 wrong tries."))

    if alerts:
        attention = '<ul class="alerts">' + "".join(
            f"<li>{dot(t)}<div><p>{esc(h)}</p><small>{d}</small></div></li>"
            for t, h, d in alerts
        ) + "</ul>"
    else:
        attention = (f'<p class="empty">{dot("ok")} &nbsp;Nothing needs attention. '
                     "Ingest is running, sources are fetching and readers are happy.</p>")

    recent_html = _recent_down_list(feedback.recent_down[:6], title_for=title_for, now=now)

    body = (
        f'<div class="grid">{tiles}</div><div class="cols">'
        + panel("Needs attention", attention, padded=False)
        + panel("Recent 👎", recent_html, padded=False,
                aside='<a href="/admin/feedback">All feedback</a>')
        + "</div>"
    )
    return page(active="overview", title="Overview",
                subtitle="How the site is doing right now, and what needs a look.",
                body=body, now=now)


# --------------------------------------------------------------------------
# Feedback
# --------------------------------------------------------------------------

def render_feedback(summary: FeedbackSummary, *, title_for: TitleLookup, now: datetime) -> str:
    subtitle = "Answers to “Was this helpful?” under every post. Most 👎 first."
    if not summary.posts:
        body = panel("Posts", '<p class="empty">No feedback yet. Votes appear here as soon as '
                     "readers use the 👍 / 👎 buttons under a post.</p>", padded=False)
        return page(active="feedback", title="Reader feedback", subtitle=subtitle,
                    body=body, now=now, json_href="/admin/feedback.json")

    tone = tone_for_rate(summary.helpful_rate, good=0.7, fair=0.5)
    channels = " · ".join(
        f"{esc(loc.upper())} 👍 {u} 👎 {d}" for loc, (u, d) in sorted(summary.by_locale.items())
    )
    tiles = "".join([
        tile("Helpful", num(summary.up), "👍 votes standing", tone="ok"),
        tile("Not helpful", num(summary.down), "👎 votes standing", tone="bad" if summary.down else ""),
        tile("Helpful rate", pct(summary.helpful_rate), channels or "—", tone=tone,
             visual=ring(summary.helpful_rate, tone)),
        tile("This week", num(summary.votes_last_7d), "votes cast in the last 7 days"),
    ])

    reasons = bar_rows(
        ((REASON_LABELS.get(r, r), n) for r, n in summary.reasons.most_common()), tone="bad",
    ) if summary.reasons else '<p class="empty">No reasons given yet.</p>'

    rows = "".join(
        f"<tr><td>{_post_link(p.id, p.locale, title_for)}</td><td class=hide-sm>{esc(p.locale.upper())}</td>"
        f"<td class=n>{p.up}</td><td class=n>{p.down}</td>"
        f"<td class=cell-meter style='min-width:110px'>{meter(p.helpful_rate, tone_for_rate(p.helpful_rate, good=.7, fair=.5))}"
        f"<span style='color:var(--muted);font-size:12px'>{pct(p.helpful_rate)}</span></td>"
        f"<td class=hide-sm>{_top_reason(p.reasons)}</td><td class='n hide-sm'>{ago(p.last_at, now)}</td></tr>"
        for p in summary.posts
    )
    table = ('<div class="scroll"><table><thead><tr><th>Post</th><th class=hide-sm>Lang</th><th class=n>👍</th>'
             '<th class=n>👎</th><th>Helpful</th><th class=hide-sm>Top reason</th>'
             '<th class="n hide-sm">Last vote</th></tr>'
             f"</thead><tbody>{rows}</tbody></table></div>")

    recent_table = _recent_down_list(summary.recent_down, title_for=title_for, now=now)

    body = (
        f'<div class="grid">{tiles}</div>'
        f'<div class="cols">{panel("Why readers said no", reasons)}'
        f'{panel("Recent 👎", recent_table, padded=False)}</div>'
        f'<div class="full">{panel("Posts", table, padded=False, aside=f"{len(summary.posts)} with votes")}</div>'
    )
    return page(active="feedback", title="Reader feedback", subtitle=subtitle, body=body,
                now=now, json_href="/admin/feedback.json")


def _recent_down_list(
    records: list[dict[str, Any]], *, title_for: TitleLookup, now: datetime,
) -> str:
    """Recent 👎 as a wrapping list. A table put four columns in half a page
    and overflowed on every screen narrower than a desktop."""
    if not records:
        return '<p class="empty">No 👎 yet.</p>'
    return '<ul class="alerts">' + "".join(
        f"<li>{dot('bad')}<div><p>{_post_link(str(r.get('id', '')), str(r.get('locale', '')), title_for)}</p>"
        f"<small>{esc(REASON_LABELS.get(str(r.get('reason') or ''), 'No reason given'))} · "
        f"{esc(str(r.get('locale', '')).upper())} · {ago(r.get('timestamp'), now)}</small></div></li>"
        for r in records
    ) + "</ul>"


def _top_reason(reasons: Any) -> str:
    top = reasons.most_common(1)
    if not top:
        return ""
    reason, count = top[0]
    return pill(f"{REASON_LABELS.get(reason, reason)} · {count}", "bad")


# --------------------------------------------------------------------------
# Content quality (/admin/metrics)
# --------------------------------------------------------------------------

def render_quality(metrics: Mapping[str, Any], *, now: datetime) -> str:
    c = {k: v for k, v in (metrics.get("counters") or {}).items() if isinstance(v, (int, float))}
    attempted = int(c.get("ai_renders_attempted", 0))
    accepted = int(c.get("ai_renders_success", 0))
    rejected = int(c.get("ai_validation_rejects", 0))
    errors = int(c.get("ai_provider_errors", 0))
    rate = _rate(accepted, attempted)
    tone = tone_for_rate(rate, good=0.8, fair=0.6)
    since = parse_time(metrics.get("first_seen_utc"))

    tiles = "".join([
        tile("Posts rendered", num(int(c.get("total_renders", 0))), "including cache hits"),
        tile("AI accepted", pct(rate), f"{num(accepted)} of {num(attempted)} attempts",
             tone=tone, visual=ring(rate, tone)),
        tile("Fell back to template", num(int(c.get("ai_fallback_count", 0))),
             "the reader got the simpler version"),
        tile("Provider errors", num(errors), "the AI call itself failed",
             tone="warn" if attempted and errors / attempted > 0.1 else ""),
    ])

    outcome = stack([
        Segment("Accepted", accepted, "var(--ok)"),
        Segment("Rejected by quality checks", rejected, "var(--warn)"),
        Segment("Provider error", errors, "var(--bad)"),
    ]) if attempted else '<p class="empty">No AI renders yet.</p>'

    reject_rows = sorted(((REJECT_LABELS[k], int(c.get(k, 0))) for k in REJECT_LABELS if c.get(k)),
                         key=lambda r: -r[1])
    reasons = bar_rows(reject_rows, tone="warn") if reject_rows else (
        '<p class="empty">No output rejected by the quality checks.</p>')

    rules_acc, rules_rej = int(c.get("relevance_rules_acc", 0)), int(c.get("relevance_rules_rej", 0))
    ai_acc, ai_rej = int(c.get("relevance_ai_acc", 0)), int(c.get("relevance_ai_rej", 0))
    relevance = (
        '<p style="margin:0 0 8px;color:var(--muted)">Keyword rules</p>'
        + stack([Segment("Kept", rules_acc, "var(--accent)"), Segment("Dropped", rules_rej, "var(--faint)")])
        + '<p style="margin:18px 0 8px;color:var(--muted)">AI second opinion on borderline items</p>'
        + stack([Segment("Kept", ai_acc, "var(--accent)"), Segment("Dropped", ai_rej, "var(--faint)"),
                 Segment("Errors", int(c.get("relevance_ai_errors", 0)), "var(--bad)")])
        + f'<p style="margin:14px 0 0;color:var(--muted)">Dropped for wrong language: '
          f"<b style='color:var(--text)'>{num(int(c.get('language_rejected', 0)))}</b></p>"
    )

    messages = metrics.get("top_failure_messages") or {}
    msg_rows = "".join(
        f'<tr><td><span class="mono trunc" title="{esc(m)}">{esc(m)}</span></td><td class=n>{num(int(n))}</td></tr>'
        for m, n in sorted(messages.items(), key=lambda kv: -int(kv[1]))
    )
    msg_table = ('<div class="scroll"><table><thead><tr><th>Message</th><th class=n>Times</th></tr></thead>'
                 f"<tbody>{msg_rows}</tbody></table></div>") if msg_rows else (
        '<p class="empty">No rejection messages recorded.</p>')

    usage_rows = ""
    for provider in sorted({k.rsplit("_calls", 1)[0] for k in c if k.endswith("_calls")}):
        calls = int(c.get(f"{provider}_calls", 0))
        if not calls:
            continue
        usage_rows += (
            f"<tr><td>{esc(_PROVIDER_NAMES.get(provider, provider.replace('_', ' ').title()))}</td>"
            f"<td class=n>{num(calls)}</td>"
            f"<td class=n>{num(int(c.get(f'{provider}_input_tokens', 0)))}</td>"
            f"<td class=n>{num(int(c.get(f'{provider}_output_tokens', 0)))}</td>"
            f"<td class='n hide-sm'>{num(int(c.get(f'{provider}_cache_read_tokens', 0)))}</td></tr>"
        )
    usage = ('<div class="scroll"><table><thead><tr><th>Provider</th><th class=n>Calls</th>'
             '<th class=n>Input tokens</th><th class=n>Output tokens</th><th class="n hide-sm">Cache reads</th>'
             f"</tr></thead><tbody>{usage_rows}</tbody></table></div>") if usage_rows else (
        '<p class="empty">No provider calls recorded.</p>')

    since_txt = since.strftime("%d %B %Y") if since else "the first run"
    body = (
        f'<div class="grid">{tiles}</div>'
        f'<div class="full">{panel("What happened to each AI render", outcome)}</div>'
        f'<div class="cols">{panel("Why output was rejected", reasons)}'
        f'{panel("Relevance filter", relevance)}</div>'
        f'<div class="full">{panel("Most frequent rejection messages", msg_table, padded=False)}</div>'
        f'<div class="full">{panel("AI provider usage", usage, padded=False)}</div>'
        f"<footer>Counters are cumulative since {esc(since_txt)} and never reset. "
        f"Last updated {ago(metrics.get('last_updated_utc'), now)}.</footer>"
    )
    return page(active="quality", title="Content quality",
                subtitle="How often the AI writes a post we publish, and why it doesn't.",
                body=body, now=now, json_href="/admin/metrics.json")


# --------------------------------------------------------------------------
# Sources (/admin/sources)
# --------------------------------------------------------------------------

def render_sources(health: Mapping[str, Any], *, now: datetime) -> str:
    rows, stopped = classify_sources(health, now)
    counts = {k: sum(1 for r in rows if r.status == k) for k in _STATUS_LABEL}

    banner = ""
    if stopped:
        banner = (f'<div class="banner bad">{dot("bad")}<p><b>Ingest has stopped.</b> The last fetch '
                  f"cycle ran {ago(health.get('last_cycle_utc'), now)}, so every source below is "
                  "frozen at that moment. Check <span class=mono>cyberalertx-run.service</span>.</p></div>")

    tiles = "".join([
        tile("Sources", num(len(rows)), f"last cycle {ago(health.get('last_cycle_utc'), now)}",
             tone="bad" if stopped else "ok"),
        tile("Healthy", num(counts["healthy"]), "fetching and publishing", tone="ok"),
        tile("Quiet", num(counts["quiet"]), "fetching, but no new article for 3 days",
             tone="warn" if counts["quiet"] else ""),
        tile("Failing", num(counts["failing"]), "no items fetched for 6 h or more",
             tone="bad" if counts["failing"] else ""),
    ])

    body_rows = ""
    for r in rows:
        s = r.stats
        relevance = s.get("relevance_rate")
        empty_rate = s.get("empty_rate")
        if empty_rate is None and s.get("cycles_seen"):
            empty_rate = int(s.get("cycles_empty") or 0) / int(s["cycles_seen"])
        cred = s.get("avg_credibility")
        body_rows += (
            f"<tr><td><b>{esc(r.name)}</b><div style='color:var(--faint);font-size:12px'>{esc(r.reason)}</div></td>"
            f"<td>{pill(_STATUS_LABEL[r.status], _STATUS_TONE[r.status])}</td>"
            f"<td class=n>{ago(s.get('last_published_at_utc'), now)}</td>"
            f"<td class='n hide-sm'>{ago(s.get('last_successful_ingest_utc'), now)}</td>"
            f"<td class='n hide-sm'>{num(int(s.get('total_fetched') or 0))}</td>"
            f"<td class='n hide-sm'>{num(int(s.get('total_relevant') or 0))}</td>"
            f"<td class='cell-meter hide-xs' style='min-width:120px'>{meter(relevance)}"
            f"<span style='color:var(--muted);font-size:12px'>{pct(relevance)}</span></td>"
            f"<td class='n hide-sm'>{'—' if cred is None else f'{float(cred):.2f}'}</td>"
            f"<td class='n hide-sm'>{pct(empty_rate)}</td></tr>"
        )
    table = ('<div class="scroll"><table><thead><tr><th>Source</th><th>Status</th><th class=n>Last article</th>'
             '<th class="n hide-sm">Last fetch</th><th class="n hide-sm">Fetched</th>'
             '<th class="n hide-sm">Relevant</th><th class=hide-xs>Relevance</th><th class="n hide-sm">Credibility</th>'
             f'<th class="n hide-sm">Empty fetches</th></tr></thead><tbody>{body_rows}</tbody>'
             "</table></div>") if body_rows else '<p class="empty">No ingest cycle has run yet.</p>'

    body = (
        banner + f'<div class="grid">{tiles}</div>'
        f'<div class="full">{panel("Feeds", table, padded=False)}</div>'
        "<footer>Failing: no item fetched for 6 h, measured against the last ingest cycle. "
        "Quiet: the feed answers but its newest article is over 3 days old. Relevance is the share "
        "of fetched items kept as security news. Credibility is the source score from 0 to 1.</footer>"
    )
    return page(active="sources", title="Sources",
                subtitle="Every feed the site ingests, worst first.",
                body=body, now=now, json_href="/admin/sources.json")


# --------------------------------------------------------------------------
# Not found (only ever shown after authentication)
# --------------------------------------------------------------------------

def render_not_found(*, now: datetime) -> str:
    body = panel("Not found", '<p class="empty">There is no admin page here. '
                 '<a href="/admin/">Back to the overview</a></p>', padded=False)
    return page(active="", title="Not found", subtitle="", body=body, now=now)


__all__ = [
    "FeedStatus", "REASON_LABELS", "classify_sources", "render_feedback", "render_not_found",
    "render_overview", "render_quality", "render_sources",
]
