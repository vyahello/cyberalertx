"use client";

import { useMemo, useState } from "react";
import { ListFilter } from "lucide-react";
import { strings } from "@/lib/i18n";
import {
  EMPTY_FILTERS,
  postsAvailableIn,
  type Audience,
  type Category,
  type FilterState,
  type Locale,
  type LocalizedThreatPost,
} from "@/lib/types";
import { Hero } from "../hero/Hero";
import { ThreatFeed } from "../threat/ThreatFeed";
import { TrendingSection } from "../trending/TrendingSection";
import { FilterPanel, countActiveFilters } from "../filters/FilterPanel";
import { FilterPresets } from "../filters/FilterPresets";
import { MobileFilterDrawer } from "../filters/MobileFilterDrawer";
import { Header } from "./Header";

interface Props {
  /** The locale the URL says we're in. The shell does NOT own locale state
   *  anymore — switching languages navigates to a different URL path, so
   *  refreshes and bookmarks always land on the correct locale. */
  lang: Locale;
  /** Posts hydrated from the server fetch in `app/[locale]/page.tsx`. */
  initialPosts: LocalizedThreatPost[];
}

/**
 * Page-level shell. Owns two things and only two things:
 *   1. Filter state (client-side, in-memory).
 *   2. Mobile drawer open/closed state.
 *
 * Locale is in the URL — the Header / LanguageSwitcher use `<Link>` to
 * navigate, not setState.
 *
 * Posts that don't have content in the active locale are filtered out
 * before they reach the feed. This is what enforces the "no mixed-language
 * content" rule the data design relies on.
 */
export function HomeShell({ lang, initialPosts }: Props) {
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const s = strings(lang);
  // Step 1: drop posts that don't have content in this locale. This is the
  //         single line that enforces no-mixed-language UX.
  const localePosts = useMemo(() => postsAvailableIn(initialPosts, lang), [initialPosts, lang]);

  // Step 2: filter options come from the locale-filtered set, so the panel
  //         never shows a category that has no items in the active language.
  const { availableCategories, availablePlatforms, availableAudiences } = useMemo(() => {
    const cats = new Set<Category>();
    const plats = new Set<string>();
    const auds = new Set<Audience>();
    for (const p of localePosts) {
      cats.add(p.category);
      p.affected_platforms.forEach((x) => plats.add(x));
      p.audience_targets.forEach((x) => auds.add(x));
    }
    return {
      availableCategories: Array.from(cats),
      availablePlatforms: Array.from(plats).sort(),
      availableAudiences: Array.from(auds),
    };
  }, [localePosts]);

  const filtered = useMemo(
    () => applyFilters(localePosts, filters, lang),
    [localePosts, filters, lang],
  );
  const activeCount = countActiveFilters(filters);

  // "Active threats now" — anything in the feed where the reader actually
  // has something to do. That's `actionability_level !== "informational"`
  // (i.e. urgent_action + recommended_action). We deliberately drop the
  // earlier "urgent_action OR recent Critical/High" rule: it produced
  // confusing zeros ("20 stories in feed but 0 active threats?") whenever
  // the locale's pool didn't include a fresh urgent item. The counter now
  // reflects "items asking for an action", which is what the hero copy
  // actually means.
  const activeThreats = useMemo(
    () => localePosts.filter((p) => p.actionability_level !== "informational").length,
    [localePosts],
  );

  return (
    <>
      <Header lang={lang} />

      <main>
        <Hero lang={lang} activeThreats={activeThreats} />
        <TrendingSection posts={localePosts} lang={lang} />

        <section
          id="feed"
          aria-labelledby="feed-heading"
          className="mx-auto max-w-6xl px-5 sm:px-8 pb-24"
        >
          <header className="mb-6 sm:mb-8 flex items-end justify-between flex-wrap gap-3">
            <div>
              <h2
                id="feed-heading"
                className="text-xl sm:text-2xl font-semibold text-text-primary tracking-tight"
              >
                {s.section_feed}
              </h2>
              <p className="text-sm text-text-secondary mt-1.5">
                {s.section_feed_caption}
              </p>
            </div>
            <div className="text-xs text-text-tertiary tabular-nums">
              <span className="text-text-primary font-medium">{filtered.length}</span>
              {" / "}
              {localePosts.length}
              {activeCount > 0 && (
                <span className="ml-3 inline-flex items-center gap-1 text-accent">
                  <ListFilter className="w-3 h-3" />
                  {s.filters_active(activeCount)}
                </span>
              )}
            </div>
          </header>

          {/* Quick-view presets — sit above the filter+feed grid so a
              first-time visitor reaches a useful slice of the feed
              without engaging with the filter chips at all. */}
          <FilterPresets state={filters} onChange={setFilters} lang={lang} />

          <div className="grid gap-8 lg:gap-10 lg:grid-cols-[260px_minmax(0,1fr)]">
            <aside className="hidden lg:block">
              <div className="sticky top-20">
                <FilterPanel
                  state={filters}
                  onChange={setFilters}
                  onReset={() => setFilters(EMPTY_FILTERS)}
                  lang={lang}
                  availableCategories={availableCategories}
                  availablePlatforms={availablePlatforms}
                  availableAudiences={availableAudiences}
                />
              </div>
            </aside>

            <ThreatFeed posts={filtered} lang={lang} totalAvailable={localePosts.length} />
          </div>
        </section>
      </main>

      <MobileFilterDrawer
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        state={filters}
        onChange={setFilters}
        onReset={() => setFilters(EMPTY_FILTERS)}
        lang={lang}
        availableCategories={availableCategories}
        availablePlatforms={availablePlatforms}
        availableAudiences={availableAudiences}
      />
    </>
  );
}

/**
 * Apply user filters. The query matches against the localized title and
 * summary only — not raw_content (we don't surface it, so matching on
 * hidden text would surprise the user).
 */
function applyFilters(
  posts: LocalizedThreatPost[],
  f: FilterState,
  lang: Locale,
): LocalizedThreatPost[] {
  const q = f.query.trim().toLowerCase();
  return posts.filter((p) => {
    if (f.threat_levels.length && !f.threat_levels.includes(p.threat_level)) return false;
    if (f.categories.length && !f.categories.includes(p.category)) return false;
    if (f.actionability.length && !f.actionability.includes(p.actionability_level)) return false;
    if (f.platforms.length && !f.platforms.some((x) => p.affected_platforms.includes(x))) return false;
    if (f.audiences.length && !f.audiences.some((a) => p.audience_targets.includes(a))) return false;
    if (q) {
      const content = p.translations[lang];
      if (!content) return false;
      const hay = `${content.title}\n${content.short_summary}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}
