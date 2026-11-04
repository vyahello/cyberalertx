import { ArrowUpRight } from "lucide-react";
import { SeverityMark } from "@/components/marks/SeverityMark";
import { TimeAgo } from "@/components/marks/TimeAgo";
import { strings } from "@/lib/i18n";
import { TONE_CLASS, evidenceRows } from "@/lib/evidence";
import type { LocalizedContent, Locale, LocalizedThreatPost } from "@/lib/types";

interface Props {
  post: LocalizedThreatPost;
  content: LocalizedContent;
  lang: Locale;
  readingSeconds: number;
  hasActions: boolean;
}

/**
 * The entry's field marks as a definition list: severity and why, status,
 * what it affects, who should care, who reported it, when, and how long it
 * takes to read. Every value comes from the post; rows without data are
 * left out rather than filled with "unknown".
 */
export function ArticleMarks({ post, content, lang, readingSeconds, hasActions }: Props) {
  const s = strings(lang);
  const evidence = evidenceRows(post, lang);
  const outlets = post.story_source_count ?? (post.corroborating_sources?.length ?? 0) + 1;
  const whoShouldCare =
    post.who_should_care?.[lang]?.trim() ||
    post.audience_targets.map((a) => s.audience[a]).filter(Boolean).join(", ");
  const reason = content.severity_reason?.trim();

  return (
    <div className="font-sans text-small">
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-3 lg:grid-cols-1 lg:gap-y-5">
        <Row label={s.mark_severity}>
          <SeverityMark level={post.threat_level} lang={lang} />
          {reason && <p className="mt-1.5 text-ink-muted leading-relaxed">{reason}</p>}
        </Row>
        {evidence.map((r) => (
          <Row key={r.key} label={r.label}>
            <span className={`font-semibold ${TONE_CLASS[r.tone]}`}>{r.value}</span>
          </Row>
        ))}
        {post.affected_platforms.length > 0 && (
          <Row label={s.mark_affects}>
            <span className="text-ink">{post.affected_platforms.join(", ")}</span>
          </Row>
        )}
        {whoShouldCare && (
          <Row label={s.mark_for}>
            <span className="text-ink">{whoShouldCare}</span>
          </Row>
        )}
        <Row label={s.mark_source}>
          {post.source_url ? (
            <a
              href={post.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="link inline-flex items-center gap-0.5 font-semibold"
            >
              {post.source}
              <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
            </a>
          ) : (
            <span className="text-ink font-semibold">{post.source}</span>
          )}
          <span className="block text-ink-faint">
            {s.mark_trust[post.source_tier]}
            {outlets > 1 && ` · ${s.mark_more_outlets(outlets - 1)}`}
          </span>
        </Row>
        <Row label={s.mark_published}>
          <span className="block text-ink tnum">{s.published_absolute(post.published_at)}</span>
          <TimeAgo iso={post.published_at} lang={lang} className="text-ink-faint" />
        </Row>
        <Row label={s.mark_reading}>
          <span className="text-ink">{s.reading_time(readingSeconds)}</span>
        </Row>
      </dl>
      {/* The "What to do" anchor sits under the standfirst (all widths). */}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="contents lg:block">
      <dt className="text-ink-faint lg:mb-1">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}
