import Link from "next/link";
import { strings } from "@/lib/i18n";
import { contentFor, type Locale, type LocalizedThreatPost } from "@/lib/types";
import { ThreatBadge } from "./ThreatBadge";

interface Props {
  /** All posts available (already filtered to the current locale). */
  pool: LocalizedThreatPost[];
  /** The post we're rendering the detail page for — excluded from the list. */
  current: LocalizedThreatPost;
  lang: Locale;
}

/**
 * Related threats — chosen by a simple, deterministic relevance scoring:
 *
 *   * same category    → +3
 *   * shared platform  → +2 (per overlap, capped)
 *   * shared audience  → +1 (per overlap, capped)
 *   * matching locale  → mandatory (the pool is already filtered)
 *
 * We deliberately avoid embedding-based similarity in v1 — keeps the
 * detail page a pure server render with no extra request.
 */
export function RelatedThreats({ pool, current, lang }: Props) {
  const s = strings(lang);

  const scored = pool
    .filter((p) => p.id !== current.id)
    .map((p) => ({
      post: p,
      score:
        (p.category === current.category ? 3 : 0) +
        Math.min(2, p.affected_platforms.filter((x) => current.affected_platforms.includes(x)).length) +
        Math.min(2, p.audience_targets.filter((a) => current.audience_targets.includes(a)).length),
    }))
    .filter((x) => x.score > 0)
    .sort(
      (a, b) =>
        b.score - a.score ||
        new Date(b.post.published_at).getTime() - new Date(a.post.published_at).getTime(),
    )
    .slice(0, 4);

  if (scored.length === 0) return null;

  return (
    <section aria-labelledby="related-heading" className="mt-12 sm:mt-16">
      <header className="mb-5">
        <h2
          id="related-heading"
          className="text-lg sm:text-xl font-semibold text-text-primary tracking-tight"
        >
          {s.detail_related}
        </h2>
        <p className="text-sm text-text-secondary mt-1">{s.detail_related_caption}</p>
      </header>
      <ul className="grid gap-3 sm:grid-cols-2">
        {scored.map(({ post }) => {
          const c = contentFor(post, lang);
          if (!c) return null;
          return (
            <li key={post.id}>
              <Link
                href={`/${lang}/threat/${post.id}`}
                prefetch={false}
                className="block surface-card surface-card-hover p-4 h-full
                           focus-visible:ring-2 focus-visible:ring-accent-ring"
              >
                <div className="flex items-center gap-2 mb-2">
                  <ThreatBadge level={post.threat_level} lang={lang} />
                  <span className="text-xs text-text-tertiary">{post.source}</span>
                </div>
                <h3 className="text-sm font-semibold text-text-primary leading-snug line-clamp-2">
                  {c.title}
                </h3>
                <p className="text-xs text-text-secondary mt-1.5 line-clamp-2">
                  {c.short_summary}
                </p>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
