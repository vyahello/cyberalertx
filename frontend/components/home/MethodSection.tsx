import { strings } from "@/lib/i18n";
import type { Locale, LocalizedThreatPost, SourceTier } from "@/lib/types";

interface Props {
  posts: LocalizedThreatPost[];
  lang: Locale;
}

const TIER_RANK: Record<SourceTier, number> = { trusted: 0, verified: 1, unverified: 2 };

/**
 * How the publication works, with side facts taken from the edition itself:
 * which outlets the stories on this page came from, and how often the
 * pipeline really runs. No reader counts, no claims we can't show.
 */
export function MethodSection({ posts, lang }: Props) {
  const s = strings(lang);
  const outlets = new Map<string, { tier: SourceTier; count: number }>();
  for (const p of posts) {
    const prev = outlets.get(p.source);
    outlets.set(p.source, {
      tier: prev ? (TIER_RANK[p.source_tier] < TIER_RANK[prev.tier] ? p.source_tier : prev.tier) : p.source_tier,
      count: (prev?.count ?? 0) + 1,
    });
  }
  const list = Array.from(outlets.entries()).sort(
    (a, b) => b[1].count - a[1].count || a[0].localeCompare(b[0]),
  );

  return (
    <section aria-labelledby="method-heading" className="page mt-section enter">
      <div className="axis gap-y-10">
        <div className="lg:col-start-2 lg:row-start-1">
          <h2 id="method-heading" className="t-section text-ink">
            {s.method_heading}
          </h2>
          <p className="mt-5 font-serif text-lead text-ink max-w-[60ch]">{s.method_body}</p>
        </div>

        <dl className="lg:col-start-1 lg:row-start-1 grid grid-cols-2 gap-x-6 gap-y-5 font-sans text-small lg:grid-cols-1 lg:max-w-[16rem] lg:pt-2">
          <div>
            <dt className="text-ink-faint">{s.method_sources}</dt>
            <dd className="text-ink font-semibold tnum mt-0.5">{s.method_sources_value(list.length)}</dd>
          </div>
          <div>
            <dt className="text-ink-faint">{s.method_editions}</dt>
            <dd className="text-ink font-semibold mt-0.5">English · Українська</dd>
          </div>
          <div className="col-span-2 lg:col-span-1">
            <dt className="text-ink-faint">{s.method_cadence}</dt>
            <dd className="text-ink font-semibold mt-0.5">{s.method_cadence_value}</dd>
          </div>
        </dl>

        {list.length > 0 && (
          <>
            <h3 className="font-sans text-small font-semibold text-ink-muted lg:pt-1">
              {s.method_outlets_heading}
            </h3>
            <ul className="on-axis grid gap-x-16 gap-y-2.5 font-sans text-small sm:grid-cols-2 max-w-[44rem]">
              {list.map(([name, { tier, count }]) => (
                <li key={name} className="flex items-baseline justify-between gap-4">
                  <span className="text-ink">
                    {name}
                    <span className="sr-only">, {s.mark_trust[tier]}</span>
                  </span>
                  <span className="text-ink-faint tnum">{count}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
