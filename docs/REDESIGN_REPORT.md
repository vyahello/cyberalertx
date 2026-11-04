# CyberAlertX transformation — report (3 November 2026)

Branch `redesign/cti-platform`, worktree `/home/cax/cax-redesign`, **uncommitted**.
Production (`/home/cax/cax`, services on :3000/:8000, its data, Postgres,
Telegram) was **not modified**; nothing was deployed or published.

Legend: ✅ done and verified · 🟡 done, not verified in production conditions · 📋 recommendation only.

---

## Product and architecture

**1. Original architecture.** Batch pipeline: RSS ingest every 30 min →
dedup/rank → hourly Claude CLI render (one call per story×locale, EN and UA
rendered independently) → JSON (+ Postgres dual-write) → read-only FastAPI →
Next.js 15 site (ISR) and Telegram. Details: `docs/audit/BASELINE_AUDIT.md`.

**2. Architectural findings.** Production runs from the git working tree
(editing in place = deploying); sources are RSS teasers (175–400 chars), so the
model pads with background knowledge; no fact layer; validation is linguistic
only; no review state; clustering missed Ukrainian inflection and
differently-worded cross-outlet stories.

**3. Main technical problems.** Duplicate stories in the feed (0 merged in the
top 40); global `tnum` turned hyphens into "real - world"; 91 sub-13px text
blocks; fragmented article page; no topic pages; mobile edge overflow; floating
filter button covering text.

**4. Improvements implemented.** ✅ New design system and every public page
rebuilt (§5–13); ✅ topic sections; ✅ fact sheet, protected-token
fact-checking, EN↔UA consistency check, scorecard, review state/queue with
admin page and CLI; ✅ prompt revisions (both languages); ✅ clustering fix;
✅ editorial standards documents; ✅ benchmark tool.

**5. Components refactored or created.** New: `marks/{SeverityMark,FieldMarks,TimeAgo}`,
`feed/{FeedSection,StoryRow,FilterPanel,FilterSheet}`,
`home/{LeadStory,PriorityList,ThreatOverview,MethodSection}`,
`article/{ArticleMarks,RichText}`, `layout/{SiteNav,MobileMenu,Wordmark}`,
`app/[locale]/topic/[slug]`, `lib/{topics,significance,filters,feed}.ts`.
Rewritten: Header, Footer, LanguageSwitcher, ThreatDetail, RelatedThreats,
ShareBar, FeedbackWidget, loading skeletons, i18n. Removed 28 superseded
components (cards, chips, badges, hero, trending, old filters).

## UI/UX

**6. Design system.** `docs/design/DESIGN_SYSTEM.md` (+ `DESIGN.md` from
Impeccable). Graphite ground with two tone steps, near-white ink, cyan as the
single signal colour, severity colours re-stepped and validated for colour-blind
separation; Literata (reading) + Fira Sans Condensed (interface), both with
Cyrillic; five type steps, nothing below 14px; one vertical axis at 42%.

**7. Visual direction.** "Field guide on the axis": each story's field marks
(severity + why, exploitation, time, outlet + count, who it hits) hang left of
the axis, text right. No gradients, glows, glass, outlined boxes, pill badges or
tiny uppercase labels. How the three skills were combined, and every deliberate
deviation from the dealt direction: DESIGN_SYSTEM.md §2.

**8. Navigation.** Topics: Latest · Vulnerabilities · Malware · Breaches ·
Scams (each with indexable page); language and Telegram always on the bar;
phone menu as a disclosure; current section marked (`aria-current`).

**9. Homepage.** First screen = the most significant story now (ranked by
severity, exploitation, urgency, corroboration, age — all real fields) with its
severity reason; "Also significant now" rows; a 7-day overview from real counts
whose rows open the matching feed slice; full feed; "How CyberAlertX works" with
outlets taken from the edition. The slogan, fake-feeling counter and gradient
hero are gone.

**10. Intelligence feed.** Day-grouped, newest first; marks column + headline +
two-line plain summary; filter rail (search incl. CVE/outlet/platform, quick
views incl. "Under active attack", severity, topic, audience, platform, action);
`aria-live` result count; deep links `?level=`, `?exploited=1`, `?q=`.

**11. Article page.** One continuous brief: standfirst → What happened →
Why it matters → Are you affected? → What to do / avoid → Key facts → Sources
(original report, other coverage, advisories, provenance note) → background →
share/feedback → related. Field marks in a sticky side column. ~70-character
measure; inline code, code blocks and CVE→NVD links supported.

**12. Responsive.** ✅ 0px horizontal overflow at 375/390/768/1440/1920; feed
reflows rail+marks+text → marks+text → single column.

**13. Accessibility.** ✅ All text tokens ≥5.1:1; severity = word + segment
count + colour; visible focus ring everywhere; one tab stop per story; native
`<dialog>` filter sheet; heading outline without gaps (checked by Impeccable's
detector); `lang="uk"`; 44px targets on phones; reduced motion honoured.

## Content and editorial quality

**14. Content audit.** `docs/editorial/CONTENT_AUDIT.md` (19 findings with
counts). Headlines: 29 UA-only non-security items rendered as threats; 12 of
285 checkable briefs state background as reporting; EN/UA severity disagree in
11.2% of current bilingual stories; UA analysis empty in 24.1% (EN 13.9%).

**15. English improvements.** Fact-discipline and attribution rules, ban on
unattributed background, varied plain-summary construction, backticks for
technical tokens (prompt); scorecard checks. `ENGLISH_STYLE_GUIDE.md`.

**16. Ukrainian improvements.** Prompt: «шляхом» no longer "canonical";
terminology block; calque block. Detection: calques and term deviations incl.
the audit's real top problems («закрити вразливість» 141, «у дикій природі» 104,
«адміни» 1,213, «вендор» 215, «на предмет» 47). UI copy rewritten natively
(the old slogan «Перш ніж вони дісталися до вас» was ungrammatical). Interface
font switched after the review found Sofia Sans draws Bulgarian letterforms.

**17. Style guides.** `docs/editorial/UKRAINIAN_STYLE_GUIDE.md`,
`ENGLISH_STYLE_GUIDE.md`. Orthography status verified: 2019 norms, annulled by
court in 2021, re-established as a state-language standard in force from
28.03.2026 (sources in the guide).

**18. Glossary.** `docs/editorial/UKRAINIAN_CYBERSECURITY_GLOSSARY.md`
(~140 terms), explicitly a house standard — no official cybersecurity
terminology standard exists.

**19. Pipeline changes.** One fact sheet per story (+1 call, cached, never
retried automatically) shared by both renders; protected-token fact check (hard
reject for invented CVE/hash/IP/CVSS); EN↔UA consistency; scorecard;
`review_status` with modes `off|flag|hold`; `/admin/review` (CSRF-protected) and
`review` CLI; Telegram renders backticks as code. On the archive it caught the
known invented CVE in the Synology brief.

**20. Before/after examples.** `docs/editorial/BENCHMARK_EXAMPLES.md` —
hand-edited by Claude, **not** pipeline output, awaiting your review. The real
pipeline benchmark is ready but **not run** (cost, see §30).

**21. Fact validation.** `ai/fact_check.py` (§19) + tests.

**22. Review process.** `docs/editorial/EDITORIAL_REVIEW_PROCESS.md`.

## SEO and engineering

**23. SEO.** Descriptive titles/descriptions per edition; topic pages with
canonical + hreflang, in the sitemap; `BreadcrumbList` JSON-LD on topics and
articles; NewsArticle gains `isAccessibleForFree`, `wordCount`,
`publishedTime`; meta descriptions cut at ~158 chars at a word boundary.
Existing URLs, `/uk→/ua`, RSS and hreflang preserved.

**24. Performance.** ✅ Homepage 32 KB gzip vs 66 KB live, while showing twice
as many stories (client feed payload slimmed); article 17 KB vs 20 KB; first
load JS 123–125 KB; mono font not preloaded.

**25. Security findings.** Admin POSTs had no CSRF protection → HMAC form
token + Sec-Fetch-Site/Origin checks added. Model text is rendered as React
text only (no HTML injection). Production running from the git tree is an
operational risk (📋 deploy from a separate release directory).

**26. Files changed.** 69 tracked files changed (+3,696 / −4,306), 28
removed, ~40 added; list: `git status` in the worktree.

**27. Dependencies.** None added or removed (fonts via the existing
`next/font`). Tooling installed outside the repo for QA only: Playwright's
Chromium in `~/.cache/ms-playwright`, NSS libs unpacked in
`~/.cache/cax-chrome-libs` (no system packages).

**28. Tests executed.** ✅ pytest 1104 passed, 3 skipped; ✅ mypy strict clean
(80 files); ✅ `tsc --noEmit`; ✅ Playwright e2e 31 passed, 1 skipped, 2 failed
(`/healthz` — served by nginx→FastAPI in production, not by a bare
`next start`); ✅ Impeccable detector 0 findings (source + rendered, 1440/390,
home/article/topic, EN/UA); Taste inspector home: 9 FAIL/6 WARN → 2 FAIL/3 WARN
(remaining: no imagery — deliberate; real headlines wrapping to 3 lines on
phones). ESLint is not configured in the project, so no lint run.

**29. Build.** ✅ `next build` succeeds (15 static pages + ISR routes).

**30. Remaining problems and recommendations.**
- 🟡 Small gaps after «д»/"t" in 14px interface text were seen in headless
  Chromium at 1× and 2×; not reproduced in a real browser — check on a device.
- 🟡 Impeccable finish review ended at "fix" with partials: feed rows ~150px
  (target ~110), who-it-hits only where data provides it. Accepted decline: the
  7-day overview.
- 📋 Run `python -m cyberalertx.tools.benchmark` (~40 CLI calls) when the
  subscription has headroom; then calibrate the review threshold.
- 📋 Decide on the UA normaliser forcing «вразлив-» (breaks у/в euphony).
- 📋 Add a relevance gate before rendering (UA digests, game/monitor news).
- 📋 Cross-source date reconciliation inside a cluster.
- 📋 Deploy: build in a separate directory; before enabling `hold`, confirm
  the Postgres `threat_posts` dual-write keeps the new `review_status` /
  `quality` fields (not verified — the worktree ran JSON-only); start with
  `CYBERALERTX_REVIEW_MODE=flag`.
