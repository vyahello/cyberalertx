import { Inbox } from "lucide-react";
import { strings } from "@/lib/i18n";
import type { Locale, LocalizedThreatPost } from "@/lib/types";
import { ThreatCard } from "./ThreatCard";

interface Props {
  posts: LocalizedThreatPost[];
  lang: Locale;
  /** Total posts available before filtering — lets us distinguish "filter
   *  too restrictive" from "backend is empty or down". */
  totalAvailable?: number;
}

/**
 * Vertical feed. Pure presentational — filtering happens in the parent
 * (homepage shell) so this can stay a server component and ship zero JS.
 *
 * The visible "ranking" is the order we receive. The backend already
 * sorts by threat_score, so we trust it here.
 *
 * Empty states are split into two messages:
 *   * `totalAvailable === 0` — no posts in the source at all (backend down
 *     OR pipeline hasn't run yet). We show the empty inbox + a hint.
 *   * `totalAvailable > 0`   — filters are too narrow. We show the
 *     filter-specific message.
 */
export function ThreatFeed({ posts, lang, totalAvailable }: Props) {
  if (!posts.length) {
    const s = strings(lang);
    const isEmptySource = totalAvailable === 0;
    // Three distinct empty states, each with calm, non-alarmist copy:
    //   * totalAvailable === 0 → "Threat feed is updating" (backend up but
    //     no posts yet, or backend unreachable — we collapse both because
    //     the user's correct action is the same: wait, refresh later).
    //   * totalAvailable > 0  → "No threats match this filter" + hint to
    //     try a preset. Filters are usually too narrow on purpose; we
    //     point the reader at the quick-views row.
    return (
      <div
        role="status"
        className="text-center py-16 px-6 border border-dashed border-border-subtle rounded-lg"
      >
        <Inbox
          className="w-8 h-8 mx-auto text-text-tertiary mb-3"
          strokeWidth={1.75}
          aria-hidden
        />
        <p className="text-text-primary font-medium mb-1">
          {isEmptySource ? s.empty_backend_updating : s.empty_feed}
        </p>
        <p className="text-sm text-text-secondary max-w-md mx-auto">
          {isEmptySource ? s.empty_no_data_hint : s.empty_filter_hint}
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {posts.map((post, i) => (
        <ThreatCard key={post.id} post={post} lang={lang} index={i} />
      ))}
    </div>
  );
}
