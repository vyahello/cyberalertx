"""`/admin/publishing` — every publication job, all six destinations.

Website EN/UA, Telegram EN/UA, Threads EN/UA: counts per destination, then
the jobs themselves with server-side filtering (destination, language,
status, story, priority, date) and pagination. Actions are the existing
Publication Engine operations — retry (failed/cancelled), cancel
(not delivered), reconcile (outcome_unknown: sent with an id / not sent) —
as POST forms with the admin CSRF token and an explicit confirmation box.
`outcome_unknown` jobs are never offered a plain retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Sequence
from urllib.parse import urlencode

from .ui import esc, num, page, panel, pill, tile

_TONE = {"published": "ok", "scheduled": "neutral", "processing": "accent", "retrying": "warn",
         "failed": "bad", "outcome_unknown": "bad", "cancelled": "neutral"}
DESTS = (("website", "en", "Website EN"), ("website", "ua", "Website UA"), ("telegram", "en", "Telegram EN"),
         ("telegram", "ua", "Telegram UA"), ("threads@en", "en", "Threads EN"), ("threads@ua", "ua", "Threads UA"))
_DEST_OPTIONS = (("", "all"), ("website", "Website"), ("telegram", "Telegram"),
                 ("threads@en", "Threads (EN account)"), ("threads@ua", "Threads (UA account)"))
STATUSES = ("scheduled", "processing", "retrying", "published", "failed", "outcome_unknown", "cancelled")
PAGE = 50


@dataclass
class JobQuery:
    destination: str = ""
    locale: str = ""
    status: str = ""
    q: str = ""
    min_priority: int | None = None
    since: date | None = None
    until: date | None = None
    page: int = 1

    @classmethod
    def from_params(cls, p: Mapping[str, str]) -> "JobQuery":
        dests = {d for d, _, _ in DESTS}
        def day(v: str) -> date | None:
            try:
                return date.fromisoformat(v) if v else None
            except ValueError:
                return None
        try:
            prio = int(p["min_priority"]) if p.get("min_priority", "").strip() else None
        except ValueError:
            prio = None
        try:
            pg = max(1, min(10_000, int(p.get("page", "1") or 1)))
        except ValueError:
            pg = 1
        return cls(destination=p.get("destination", "") if p.get("destination", "") in dests else "",
                   locale=p.get("locale", "") if p.get("locale", "") in ("en", "ua") else "",
                   status=p.get("status", "") if p.get("status", "") in STATUSES else "",
                   q=(p.get("q") or "").strip()[:120], min_priority=prio,
                   since=day(p.get("since", "")), until=day(p.get("until", "")), page=pg)

    def params(self) -> dict[str, Any]:
        return {"destination": self.destination, "locale": self.locale, "status": self.status, "q": self.q,
                "min_priority": "" if self.min_priority is None else self.min_priority,
                "since": self.since.isoformat() if self.since else "", "until": self.until.isoformat() if self.until else ""}


def filter_jobs(jobs: Sequence[Any], q: JobQuery) -> tuple[list[Any], int]:
    out = []
    for j in jobs:
        if q.destination and j.destination != q.destination or q.locale and j.locale != q.locale:
            continue
        if q.status and j.status != q.status:
            continue
        if q.q and q.q not in j.job_id and q.q != j.fingerprint and q.q not in j.members and q.q != j.external_id:
            continue
        if q.min_priority is not None and j.priority < q.min_priority:
            continue
        stamp = (j.completed_at or j.scheduled_at or j.created_at)[:10]
        if q.since and stamp < q.since.isoformat() or q.until and stamp > q.until.isoformat():
            continue
        out.append(j)
    out.sort(key=lambda j: (j.updated_at or j.created_at), reverse=True)
    start = (q.page - 1) * PAGE
    return out[start:start + PAGE], len(out)


def _actions(j: Any, csrf: str, back: str) -> str:
    def form(action: str, label: str, tone: str = "", extra: str = "") -> str:
        return (f'<form method="post" action="/admin/publishing/action" class="inline-form">'
                f'<input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="job" value="{esc(j.job_id)}">'
                f'<input type="hidden" name="action" value="{action}"><input type="hidden" name="back" value="{esc(back)}">'
                f'{extra}<label class="confirm"><input type="checkbox" name="confirm" value="yes" required> confirm</label>'
                f'<button class="btn {tone}" type="submit">{esc(label)}</button></form>')
    out = []
    if j.status in ("failed", "cancelled"):
        out.append(form("retry", "Retry", "ok"))
    if j.status in ("scheduled", "retrying", "failed"):
        out.append(form("cancel", "Cancel", "bad"))
    if j.status == "outcome_unknown":
        out.append(form("reconcile_sent", "Mark delivered",
                        extra='<input name="external_id" placeholder="post / message id" required maxlength="64" '
                              'pattern="[A-Za-z0-9_:.-]+" style="width:150px">'))
        out.append(form("reconcile_not_sent", "Not delivered → send again", "bad"))
    return "".join(out)


def render_publishing(jobs: Sequence[Any], *, now: datetime, query: JobQuery | None = None, csrf: str = "",
                      notice: str = "", error: str = "") -> str:
    query = query or JobQuery()
    counts: dict[tuple[str, str], dict[str, int]] = {(d, loc): {} for d, loc, _ in DESTS}
    for j in jobs:
        c = counts.setdefault((j.destination, j.locale), {})
        c[j.status] = c.get(j.status, 0) + 1

    def tone(c: Mapping[str, int]) -> str:
        return "bad" if c.get("outcome_unknown") else "warn" if c.get("failed") or c.get("retrying") else "ok" if c else ""

    label = {(d, loc): lbl for d, loc, lbl in DESTS}
    tiles = "".join(
        tile(label.get(k, f"{k[0]} {k[1].upper()}"), num(c.get("published", 0)),
             " · ".join(f"{esc(s.replace('_', ' '))} {v}" for s, v in sorted(c.items()) if s != "published")
             or ("no jobs" if not c else "nothing open"), tone=tone(c),
             href="/admin/publishing?" + urlencode({"destination": k[0], "locale": k[1]}))
        for k, c in counts.items())

    p = query.params()
    def opt(name: str, val: str, options: Sequence[tuple[str, str]]) -> str:
        return f'<select name="{name}">' + "".join(
            f'<option value="{esc(v)}"{" selected" if v == val else ""}>{esc(lbl)}</option>' for v, lbl in options) + "</select>"
    form = ('<form class="filters" method="get" action="/admin/publishing">'
            f'<label>Story / job / post id<input type="search" name="q" value="{esc(query.q)}"></label>'
            f'<label>Destination{opt("destination", query.destination, _DEST_OPTIONS)}</label>'
            f'<label>Language{opt("locale", query.locale, [("", "both"), ("en", "EN"), ("ua", "UA")])}</label>'
            f'<label>Status{opt("status", query.status, [("", "any")] + [(s, s.replace("_", " ")) for s in STATUSES])}</label>'
            f'<label>Min priority<input type="number" name="min_priority" style="width:80px" value="{esc(p["min_priority"])}"></label>'
            f'<label>From<input type="date" name="since" value="{esc(p["since"])}"></label>'
            f'<label>To<input type="date" name="until" value="{esc(p["until"])}"></label>'
            '<button class="btn" type="submit">Apply</button> <a href="/admin/publishing" style="padding:7px 4px">Reset</a></form>')

    rows, total = filter_jobs(jobs, query)
    back = "/admin/publishing?" + urlencode({k: v for k, v in {**p, "page": query.page}.items() if v not in ("", None)})
    trs = "".join(
        f"<tr><td><a href='/admin/stories/{esc(j.story_key)}'>{esc(j.story_key)}</a>"
        f"<div class=mono style='color:var(--faint);font-size:12px'>{esc(j.job_id)}</div>"
        + (f"<div style='font-size:12px;color:var(--bad)'>{esc(j.error_category)}: {esc(j.last_error[:160])}</div>" if j.last_error else "")
        + f"</td><td>{esc(label.get((j.destination, j.locale), j.destination))}<br><small style='color:var(--faint)'>{esc(j.publication_type)}</small></td>"
        f"<td>{pill(j.status.replace('_', ' '), _TONE.get(j.status, 'neutral'))}</td>"
        f"<td class=n>{esc(j.priority)}</td><td class=n><small>{esc((j.next_attempt_at if j.status == 'retrying' else j.scheduled_at)[:16])}</small></td>"
        f"<td class=n>{esc(j.attempts)}/{esc(j.max_attempts)}</td>"
        f"<td>{(f'<a href={chr(34)}{esc(j.published_url)}{chr(34)} rel={chr(34)}noopener noreferrer{chr(34)}>' + esc(j.external_id or 'open') + '</a>') if j.published_url else esc(j.external_id or '—')}</td>"
        f"<td class=n><small>{esc((j.updated_at or '')[:16])}</small></td>"
        f"<td>{_actions(j, csrf, back) if csrf else ''}</td></tr>" for j in rows)
    table = ('<div class="scroll"><table><thead><tr><th>Story / job</th><th>Destination</th><th>Status</th><th class=n>Prio</th>'
             '<th class=n>Scheduled / next</th><th class=n>Attempts</th><th>Result</th><th class=n>Updated (UTC)</th><th>Actions</th>'
             f'</tr></thead><tbody>{trs}</tbody></table></div>') if rows else \
        f'<p class="empty">{"No publication jobs yet: the job worker has not been switched on (see docs/publish/PUBLICATION_ENGINE.md)." if not jobs else "No job matches these filters."}</p>'
    pages = max(1, (total + PAGE - 1) // PAGE)
    nav = ""
    if pages > 1:
        def link(n: int, txt: str) -> str:
            return f'<a href="/admin/publishing?{esc(urlencode({**{k: v for k, v in p.items() if v not in ("", None)}, "page": n}))}">{txt}</a>'
        nav = (f'<div class="pager"><span>{num(total)} jobs · page {query.page} of {pages}</span><span>'
               f'{link(query.page - 1, "← Newer") if query.page > 1 else ""} {link(query.page + 1, "Older →") if query.page < pages else ""}</span></div>')
    banner = ""
    if notice:
        banner += f'<div class="banner"><span class="dot ok"></span><p>{esc(notice)}</p></div>'
    if error:
        banner += f'<div class="banner bad"><span class="dot bad"></span><p>{esc(error)}</p></div>'
    body = (banner + f'<div class="grid">{tiles}</div>' + f'<div class="full">{form}</div>'
            + panel("Jobs", table + nav, padded=False,
                    aside="unknown outcomes are never retried blindly — check the channel, then reconcile"))
    return page(active="publishing", title="Publications", body=body, now=now, json_href="/admin/publishing.json",
                query=query.q, subtitle="One job per story, edition and destination. A failure on one destination "
                                        "never holds back the others.")


__all__ = ["DESTS", "JobQuery", "filter_jobs", "render_publishing"]
