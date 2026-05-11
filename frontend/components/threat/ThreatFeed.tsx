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
          {isEmptySource ? s.empty_no_data : s.empty_feed}
        </p>
        {isEmptySource && (
          <p className="text-sm text-text-secondary max-w-md mx-auto">
            {s.empty_no_data_hint}
          </p>
        )}
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
