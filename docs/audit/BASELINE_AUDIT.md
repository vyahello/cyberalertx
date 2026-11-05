# CyberAlertX — Baseline audit (2 November 2026)

> **Status: historical record.** Paths such as `/home/cax/cax-redesign` and the deployment steps described here predate the release layout; see [docs/README.md](../README.md) for current documents.

Snapshot of the product before the redesign branch `redesign/cti-platform`.
Everything here was observed in the repository at `73257f0`, in the live site
(https://cyberalertx.com, read-only page loads), in the cached content
(`data/threat_posts.json`, 4,453 briefs) or in the running services. Where a
statement is an inference, it says so.

---

## 1. Architecture as found

| Layer | What it is | Notes |
|---|---|---|
| Ingest (`cyberalertx-run`) | APScheduler, RSS via `httpx` + `feedparser` | Deterministic: dedup → normalize → filter → categorize → platforms → audience → actionability → credibility → rank → persist. No AI. |
| AI render (`cyberalertx-generate`) | systemd timer, **hourly**, `generate --limit 1 --use-llm` | One Claude CLI call per `(story, locale)`; EN and UA are rendered **independently from the source** (UA is not a translation of EN). Rule-based fallback on any failure. |
| API (`cyberalertx-api`) | FastAPI, read-only | `/posts`, `/posts/{id}`, `/healthz`, `/feedback`, token-locked `/admin`. Never calls AI. |
| Website (`cyberalertx-frontend`) | Next.js 15.5 App Router, React 19, Tailwind 3 | `/{en,ua}` feed (ISR 60 s), `/{locale}/threat/{id}` (ISR 300 s), RSS per locale, sitemap, robots, JSON-LD. |
| Telegram (`cyberalertx-telegram`) | timer, 10×/day | Publishes cached High/Critical/urgent posts; JSONL ledger for idempotency. |
| Storage | JSON authoritative + Postgres (Supabase) dual-write | |
| Edge | nginx behind Cloudflare | |

**Operational risk found during the audit:** the production services run
directly out of the git checkout at `/home/cax/cax`. Editing Python there puts
the change live at the next hourly `generate`; running `npm run build` there
replaces the `.next` directory the live `next start` serves. All work on this
branch was therefore done in a separate worktree (`/home/cax/cax-redesign`)
with a copy of the data and no `.env` (JSON-only, no Postgres, no Telegram).

## 2. Existing functionality (preserved)

- Bilingual routing (`/en`, `/ua`, `/uk → /ua` redirect), locale-strict feeds
  (UA-sourced stories are UA-only by design).
- Client-side filters (severity, actionability, category, platform, audience,
  free-text search) and seven quick-view presets; mobile filter sheet.
- Trending strip, threat detail with severity rationale, "Am I affected?"
  checks, recovery steps, actions / anti-actions, quick facts, analysis,
  references (CVE → NVD), multi-outlet coverage, per-category background,
  share bar, 👍/👎 feedback with reasons, related stories.
- SEO: canonical + hreflang (`en-US`, `uk`, `x-default`), per-article OG,
  NewsArticle and ItemList JSON-LD, RSS autodiscovery, sitemap (297 URLs).
- Accessibility work already present: skip link, `lang="uk"` on `/ua`,
  reduced-motion handling, AA-tuned tertiary text colour.

## 3. Design weaknesses (measured)

Taste-skill inspector on the live homepage: **9 FAIL / 6 WARN**; on an article:
**11 FAIL / 6 WARN** (design-tool captures, kept locally, not in the repository).

1. **The first screen sells instead of informing.** The homepage opens on a
   slogan ("Cyber threats. Before they hit you."), an eyebrow, a gradient
   grid and a "3 active threats now" counter. No story headline is visible
   above the fold at 1440×900. The brief's first question, "what is
   happening?", is not answered on the first screen.
2. **Generic dark-dashboard vocabulary**: radial gradients, 1px grid
   texture, 25 outlined boxes, glass header (`backdrop-blur`), pill badges,
   coloured icon tiles, "live" pulse dots. Nothing in the look is specific to
   CyberAlertX except the glyph.
3. **Micro-typography**: 91 text blocks under 13px on the homepage; eight
   uppercase letter-spaced labels; article body set at 14px.
4. **Broken hyphens site-wide.** `font-feature-settings: "tnum"` is applied to
   the entire body. In Inter, `tnum` also swaps the hyphen for a tabular-width
   glyph, so every compound word renders as "real - world", "Iran - aligned".
5. **One typeface, one weight register.** Inter carries headlines, body and
   labels; there is no reading face for long text.

## 4. UX weaknesses

1. **Duplicate stories in the feed.** `story_source_count` is 1 for every one
   of the top 40 posts. EN shows Chainalysis twice (BleepingComputer and The
   Hacker News, same day); UA shows the «Повітряна тривога» incident five
   times (ain.ua, dev.ua ×2, itc.ua, dou.ua), with a conflicting date
   (1 vs 2 November) between versions. *Root cause is in ingest clustering,
   not in the UI.*
2. **Card overload.** Each card stacks a category icon tile, severity pill,
   actionability pill, timestamp, audience chip, title, lead, source badge,
   source count and up to two signal chips: three chip vocabularies before
   the reader reaches the headline.
3. **Low-information audience chip.** "Cybersecurity professionals" appears
   on most cards, including a consumer NAS story.
4. **Floating "Filters" button covers card text** on phones (visible in the
   390px screenshots) and the trending row scrolls sideways with clipped cards.
5. **Text touches the right screen edge at 768 and 390px** (inspector
   `edge-text`, `off-centre`).
6. **The article page is fragmented.** The same fact is restated in the plain
   summary, the "at a glance" summary, "why it matters", the severity reason
   and the snapshot box, in five differently styled containers.
7. **No category navigation.** Categories exist in the data but there is no
   way to browse vulnerabilities, ransomware or breaches as a section, and no
   indexable topic pages.

## 5. Editorial weaknesses (content audit summary)

Full detail and examples: `docs/editorial/CONTENT_AUDIT.md`.

- Recent Claude-CLI renders (≈94% of the archive) are concise and largely
  natural in both languages; the older Haiku renders read noticeably more
  generic.
- **Unattributed model knowledge in analysis paragraphs**: e.g. the Synology
  brief states that C3RB3R "encrypted Confluence servers within days of
  CVE-2023-22518" and that "no free decryptor exists" — neither is in the
  source. Possibly true, but presented as reporting.
- **Speculation stated as analysis** in older renders ("attackers … likely
  identified vulnerable instances within minutes").
- **Formulaic inline glosses** in EN plain summaries ("C3RB3R ransomware,
  software that locks your files, is hitting…").
- **Irrelevant advice**: a Russian MNS app hack carries advice for
  administrators of "your alert system"; a DOU weekly-news podcast became a
  "Binance breach" brief with account-security actions.
- **Ukrainian**: generally natural; recurring issues are calques
  («закрила вразливості», «перемкніть процедури»), colloquial register
  («гляньте»), inconsistent terms for the same thing (зловмисники /
  нападники / атакувальники), English terms left inline («як zero-day»),
  and the prompt itself recommending «шляхом» as the "canonical" form.
- Empty analysis on 12% of EN and 19% of UA briefs (honest when the source
  is a teaser, but UA is thinner than EN).

## 6. Content-generation weaknesses

- **Source starvation**: ingest stores the RSS teaser (median 175–400 chars)
  and never fetches the article; the model writes 300–600 words from it. This
  is the root of both thin briefs and model-knowledge padding.
- **No fact layer**: there is no structured record of what the source
  actually claims, so nothing can check a rendered CVE, version, date or
  number against the source, and EN and UA can drift apart factually.
- **Validation is linguistic, not factual**: banned phrases, Russism stems,
  near-copy ratio and script checks exist; protected technical tokens are
  only checked for references.
- **No review state**: a post is either cached (published) or not. There is
  no "needs human review" flag, and no way for the editor to approve a post.

## 7. SEO findings

- Good foundation: canonical, hreflang, OG per locale and per article,
  NewsArticle JSON-LD, RSS, sitemap.
- Home `<title>` is a slogan, not a description of the publication.
- No category/topic landing pages (lost long-tail entry points).
- No breadcrumbs (`BreadcrumbList`) on articles.
- Article `<meta description>` uses the plain summary; fine, but no length
  control (some exceed 160 characters).

## 8. Technical risks

- Production runs from the working tree (see §1).
- `react` / `react-dom` pinned to a 19 RC in `package.json` while installed
  versions are newer; the lockfile, not `package.json`, decides what ships.
- `ThreatFeed` and the homepage shell are one large client component; the
  whole feed hydrates even though only filtering is interactive.
- Card prefetch is disabled because of an unexplained navigation bug
  (documented in `ThreatCard.tsx`); not reproduced in this audit.

## 9. Opportunities (prioritised)

1. Lead with the news: the first screen shows the most significant current
   story and its severity rationale.
2. One reading face plus one interface face (both with Cyrillic), body text
   at 17–19px, no sub-13px text.
3. Feed as a dense, scannable list with a fixed metadata margin instead of
   chip-stacked cards.
4. Article page as one continuous brief, not five boxes.
5. Topic pages for the main threat families.
6. A shared fact sheet per story, factual validation of protected tokens,
   a quality scorecard and an editor review queue.
7. Ukrainian style guide and terminology glossary that the prompts and the
   validator both use.
8. Fix clustering so one incident is one story (recommended; see §4.1).
