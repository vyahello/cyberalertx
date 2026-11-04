import { StoryRow } from "@/components/feed/StoryRow";
import { strings } from "@/lib/i18n";
import { topicForCategory } from "@/lib/topics";
import type { Locale, LocalizedThreatPost } from "@/lib/types";

interface Props {
  pool: LocalizedThreatPost[];
  current: LocalizedThreatPost;
  lang: Locale;
}

/**
 * "More on this topic": up to four entries that share the category, a
 * platform or an audience with the current story, closest first. Same row
 * anatomy as the feed, so the reader already knows how to scan it.
 */
export function RelatedThreats({ pool, current, lang }: Props) {
  const s = strings(lang);
  const related = pool
    .filter((p) => p.id !== current.id)
    .map((p) => ({
      post: p,
      score:
        (p.category === current.category ? 3 : 0) +
        Math.min(2, p.affected_platforms.filter((x) => current.affected_platforms.includes(x)).length) +
        Math.min(2, p.audience_targets.filter((a) => current.audience_targets.includes(a)).length),
    }))
    .map((x) => ({
      ...x,
      score:
        x.score +
        (topicForCategory(x.post.category) &&
        topicForCategory(x.post.category) === topicForCategory(current.category)
          ? 2
          : 0),
    }))
    .sort(
      (a, b) =>
        b.score - a.score ||
        new Date(b.post.published_at).getTime() - new Date(a.post.published_at).getTime(),
    )
    .slice(0, 4)
    .map((x) => x.post);

  if (related.length === 0) return null;

  return (
    <section aria-labelledby="related-heading" className="page mt-section enter">
      <h2 id="related-heading" className="t-section text-ink mb-6">
        {s.detail_related}
      </h2>
      <div className="feed-grid">
        <div className="hidden lg:block" aria-hidden />
        <ol className="feed-list">
          {related.map((post) => (
            <StoryRow key={post.id} post={post} lang={lang} level={3} />
          ))}
        </ol>
      </div>
    </section>
  );
}
