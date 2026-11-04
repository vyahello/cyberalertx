import Link from "next/link";
import { SeverityMark } from "@/components/marks/SeverityMark";
import { TimeAgo } from "@/components/marks/TimeAgo";
import { strings } from "@/lib/i18n";
import { HTML_LANG, contentFor, type Locale, type LocalizedThreatPost } from "@/lib/types";
import { ThreatOverview, type OverviewCounts } from "./ThreatOverview";

interface Props {
  posts: LocalizedThreatPost[];
  lang: Locale;
  overview: OverviewCounts;
}

/**
 * The next most significant stories after the lead, as two-ended rows:
 * headline on the axis, severity and time at the far end. Headline-only on
 * purpose — this list exists to be scanned in five seconds.
 */
export function PriorityList({ posts, lang, overview }: Props) {
  const s = strings(lang);
  if (posts.length === 0) return null;

  return (
    <section aria-labelledby="priority-heading" className="page mt-16 lg:mt-24 enter">
      <div className="axis gap-y-4">
        <div className="lg:row-span-2 lg:pr-6">
          <h2 id="priority-heading" className="t-section text-ink lg:pt-3">
            {s.section_priority}
          </h2>
          <ThreatOverview counts={overview} lang={lang} className="mt-8 max-w-[22rem] hidden lg:block" />
        </div>
        <ol className="on-axis">
          {posts.map((post) => {
            const c = contentFor(post, lang);
            if (!c?.title) return null;
            const exploited = Boolean(post.signals?.active_exploitation);
            return (
              <li
                key={post.id}
                lang={HTML_LANG[lang]}
                className="group relative grid gap-x-8 gap-y-2 py-4 sm:grid-cols-[minmax(0,1fr)_auto]
                           has-[a:focus-visible]:outline has-[a:focus-visible]:outline-2
                           has-[a:focus-visible]:outline-signal has-[a:focus-visible]:outline-offset-4"
              >
                <h3 className="font-serif text-lead font-semibold text-ink">
                  <Link
                    href={`/${lang}/threat/${post.id}`}
                    prefetch={false}
                    className="stretched focus-visible:outline-none decoration-signal/60 decoration-1
                               underline-offset-[5px] group-hover:underline"
                  >
                    {c.title}
                  </Link>
                </h3>
                <div className="order-first sm:order-none flex flex-wrap items-center gap-x-3 gap-y-1
                                font-sans text-small text-ink-faint sm:flex-col sm:items-end sm:pt-1 sm:text-right">
                  <SeverityMark level={post.threat_level} lang={lang} />
                  {exploited && (
                    <span className="text-sev-critical font-medium">{s.mark_exploited}</span>
                  )}
                  <TimeAgo iso={post.published_at} lang={lang} className="tnum" />
                  {(post.audience_targets[0] && s.audience[post.audience_targets[0]]) ||
                    post.who_should_care?.[lang]}
                </div>
              </li>
            );
          })}
        </ol>
        <ThreatOverview counts={overview} lang={lang} className="mt-6 max-w-[26rem] lg:hidden" />
      </div>
    </section>
  );
}
