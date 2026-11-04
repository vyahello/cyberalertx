"use client";

import { useEffect, useMemo, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import {
  applyFilters,
  countActiveFilters,
  dayKey,
  dayLabel,
} from "@/lib/filters";
import {
  EMPTY_FILTERS,
  type Audience,
  type Category,
  type FilterState,
  type Locale,
  type LocalizedThreatPost,
  type ThreatLevel,
} from "@/lib/types";
import { FilterPanel, SearchField, type FilterOptions } from "./FilterPanel";
import { FilterSheet } from "./FilterSheet";
import { StoryRow } from "./StoryRow";

interface Props {
  /** Posts already restricted to this locale, newest first. */
  posts: LocalizedThreatPost[];
  lang: Locale;
  heading: string;
  /** Rendered as the section's h2 unless the page supplies its own h1. */
  headingLevel?: 1 | 2;
  /** Optional sentence under the heading (topic pages). */
  description?: string;
  className?: string;
}

const AUDIENCE_ORDER: Audience[] = [
  "normal_users",
  "mobile_users",
  "crypto_users",
  "developers",
  "sysadmins",
  "enterprise",
];

export function FeedSection({
  posts,
  lang,
  heading,
  headingLevel = 2,
  description,
  className,
}: Props) {
  const s = strings(lang);
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [sheetOpen, setSheetOpen] = useState(false);

  // Deep links from the overview and elsewhere: ?level=Critical,
  // ?exploited=1, ?q=ivanti. Read after hydration so the server-rendered
  // feed (what crawlers and no-JS readers get) stays the full list.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const levels = params
      .getAll("level")
      .flatMap((v) => v.split(","))
      .filter((v): v is ThreatLevel => ["Critical", "High", "Medium", "Low"].includes(v));
    const exploited = params.get("exploited") === "1";
    const q = params.get("q")?.slice(0, 80) ?? "";
    if (levels.length || exploited || q) {
      setFilters({ ...EMPTY_FILTERS, threat_levels: levels, exploited_only: exploited, query: q });
    }
  }, []);

  const options: FilterOptions = useMemo(() => {
    const cats = new Set<Category>();
    const plats = new Map<string, number>();
    const auds = new Set<Audience>();
    for (const p of posts) {
      cats.add(p.category);
      p.affected_platforms.forEach((x) => plats.set(x, (plats.get(x) ?? 0) + 1));
      p.audience_targets.forEach((x) => auds.add(x));
    }
    return {
      categories: Array.from(cats).filter((c) => c !== "other"),
      // Most-covered platforms first; a long tail of one-off names is noise.
      platforms: Array.from(plats.entries())
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .slice(0, 10)
        .map(([p]) => p),
      audiences: AUDIENCE_ORDER.filter((a) => auds.has(a)),
    };
  }, [posts]);

  const filtered = useMemo(() => applyFilters(posts, filters, lang), [posts, filters, lang]);
  const active = countActiveFilters(filters);

  const groups = useMemo(() => {
    const out: { key: string; posts: LocalizedThreatPost[] }[] = [];
    for (const p of filtered) {
      const key = dayKey(p.published_at, lang);
      const last = out[out.length - 1];
      if (last && last.key === key) last.posts.push(p);
      else out.push({ key, posts: [p] });
    }
    return out;
  }, [filtered, lang]);

  const Heading = headingLevel === 1 ? "h1" : "h2";
  // Keep the outline unbroken: day headings sit one level under the
  // section heading, story headlines one level under the day.
  const DayHeading = headingLevel === 1 ? "h2" : "h3";
  const rowLevel = headingLevel === 1 ? 3 : 4;

  return (
    <section
      id="feed"
      aria-labelledby="feed-heading"
      className={cn("page scroll-mt-20", className)}
    >
      <header className="axis gap-y-3 mb-8 sm:mb-10">
        <Heading
          id="feed-heading"
          className={cn(
            "text-ink",
            headingLevel === 1 ? "t-head" : "t-section",
            "lg:col-span-2",
          )}
        >
          {heading}
        </Heading>
        {description && (
          <p className="font-serif text-lead text-ink-muted max-w-measure lg:col-span-2">
            {description}
          </p>
        )}
      </header>

      <div className="feed-grid">
        <aside className="feed-rail" aria-label={s.filters_title}>
          <FilterPanel state={filters} onChange={setFilters} lang={lang} options={options} />
        </aside>

        {/* Phones and tablets: search stays in reach, the rest opens in a sheet. */}
        <div className="lg:hidden col-span-full mb-4 flex gap-2">
          <div className="flex-1">
            <SearchField
              value={filters.query}
              placeholder={s.filter_search_placeholder}
              label={s.filter_search}
              onChange={(query) => setFilters({ ...filters, query })}
            />
          </div>
          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            className="btn-quiet px-4"
            aria-haspopup="dialog"
          >
            <SlidersHorizontal className="h-4 w-4" aria-hidden />
            {s.filters_button}
            {active > 0 && <span className="tnum text-signal">{active}</span>}
          </button>
        </div>

        <div className="feed-list">
          <p
            className="col-span-full t-small text-ink-faint tnum pb-1 md:col-start-2"
            aria-live="polite"
          >
            {s.feed_count(filtered.length, posts.length)}
            {active > 0 && <span className="text-signal"> · {s.filters_active(active)}</span>}
          </p>

          {filtered.length === 0 ? (
            <div role="status" className="col-span-full md:col-start-2 py-12">
              <p className="font-serif text-lead text-ink">
                {posts.length === 0 ? s.empty_backend_updating : s.empty_feed}
              </p>
              <p className="mt-2 text-ink-muted">
                {posts.length === 0 ? s.empty_no_data_hint : s.empty_filter_hint}
              </p>
            </div>
          ) : (
            groups.map((g) => (
              <div key={g.key} className="feed-day-group enter">
                <DayHeading
                  id={`day-${g.key}`}
                  className="feed-day font-sans text-small font-semibold text-ink-muted"
                  suppressHydrationWarning
                >
                  {dayLabel(g.key, lang)}
                </DayHeading>
                <ol className="feed-day-list" aria-labelledby={`day-${g.key}`}>
                  {g.posts.map((post) => (
                    <StoryRow key={post.id} post={post} lang={lang} level={rowLevel} />
                  ))}
                </ol>
              </div>
            ))
          )}
        </div>
      </div>

      <FilterSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        state={filters}
        onChange={setFilters}
        lang={lang}
        options={options}
        resultCount={filtered.length}
      />
    </section>
  );
}
