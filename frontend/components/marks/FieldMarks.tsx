import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import { TONE_CLASS, evidenceRows } from "@/lib/evidence";
import type { Locale, LocalizedThreatPost } from "@/lib/types";
import { SeverityMark } from "./SeverityMark";
import { TimeAgo } from "./TimeAgo";

interface Props {
  post: LocalizedThreatPost;
  lang: Locale;
  /**
   * `row`   — feed rows: inline on phones, stacked in the side-note column
   *           from `md` up.
   * `inline`— always one wrapping line (lead story, related rows).
   */
  variant?: "row" | "inline";
  className?: string;
}

/**
 * The field marks of a story: how severe, whether it is being exploited,
 * when, and who reported it. This is the side-note column of the feed —
 * the thing a reader scans before deciding to read a headline.
 */
export function FieldMarks({ post, lang, variant = "row", className }: Props) {
  const s = strings(lang);
  const outlets = post.story_source_count ?? (post.corroborating_sources?.length ?? 0) + 1;
  // The one status worth a feed reader's glance; muted states ("not
  // confirmed", "no exploitation reported") belong on the article page.
  const status = evidenceRows(post, lang).find((r) => r.tone !== "muted");
  // Who it hits: the pipeline's audiences, most specific first.
  const audience =
    (post.audience_targets[0] && s.audience[post.audience_targets[0]]) ||
    post.who_should_care?.[lang]?.trim() ||
    "";

  return (
    <div
      className={cn(
        "font-sans text-small text-ink-faint",
        "flex flex-wrap items-center gap-x-3 gap-y-1",
        variant === "row" && "md:flex-col md:items-start md:gap-y-0.5 md:leading-tight",
        className,
      )}
    >
      <span className="inline-flex flex-wrap items-center gap-x-2">
        <SeverityMark level={post.threat_level} lang={lang} />
        {status && (
          <span className={`${TONE_CLASS[status.tone]} font-medium`}>{status.value}</span>
        )}
      </span>
      <span>
        <TimeAgo iso={post.published_at} lang={lang} className="tnum whitespace-nowrap" />
        {"\u00a0· "}
        <span className="text-ink-muted whitespace-nowrap">{post.source}</span>
        {outlets > 1 && <span className="whitespace-nowrap"> {s.mark_more_outlets(outlets - 1)}</span>}
      </span>
      {audience && <span>{audience}</span>}
    </div>
  );
}
