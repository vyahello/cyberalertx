import Link from "next/link";
import { StoryVisual } from "@/components/media/StoryVisual";
import { ArrowUpRight } from "lucide-react";
import { FieldMarks } from "@/components/marks/FieldMarks";
import { TimeAgo } from "@/components/marks/TimeAgo";
import { strings } from "@/lib/i18n";
import { HTML_LANG, contentFor, type Locale, type LocalizedThreatPost } from "@/lib/types";

interface Props {
  lead: LocalizedThreatPost | null;
  total: number;
  lang: Locale;
  /** Server render time, so the edition date doesn't drift on hydrate. */
  now: number;
}

/**
 * The first screen. Left of the axis: the edition title and what this
 * publication is. On the axis: the most significant story right now, with
 * its field marks, the plain-language lead and the reason it is rated the
 * way it is. One primary action: read the brief.
 */
export function LeadStory({ lead, total, lang, now }: Props) {
  const s = strings(lang);
  const c = lead ? contentFor(lead, lang) : null;
  const plain = c ? c.plain_summary?.trim() || c.short_summary?.trim() || "" : "";
  const reason = c?.severity_reason?.trim();
  const firstStep = c?.what_to_do?.find((x) => x.trim())?.trim().replace(/`/g, "");

  return (
    <section aria-labelledby="hero-headline" className="page pt-8 sm:pt-12 lg:pt-16">
      <div className="axis gap-y-10">
        <div className="flex flex-col gap-5 lg:pr-6">
          <h1 id="hero-headline" className="t-display text-ink animate-rise break-words hyphens-auto">
            {s.edition_title}
          </h1>
          <p className="font-sans text-small text-ink-faint tnum animate-rise [animation-delay:80ms]">
            <span className="font-semibold text-ink-muted">{s.edition_date(new Date(now))}</span>
            {lead && (
              <>
                {" · "}
                {s.edition_count(total)} · {s.edition_latest.toLowerCase()}{" "}
                <TimeAgo iso={lead.published_at} lang={lang} />
              </>
            )}
          </p>
          <p className="font-serif text-body text-ink-muted max-w-[34ch] animate-rise [animation-delay:160ms]">
            {s.edition_standfirst}
          </p>
        </div>

        {lead && c ? (
          <article
            lang={HTML_LANG[lang]}
            aria-labelledby="lead-title"
            className="on-axis flex flex-col"
          >
            <figure className="mb-6">
              <StoryVisual post={lead} lang={lang} variant="og" eager />
              <figcaption className="sr-only">{s.illustration_caption}</figcaption>
            </figure>
            <h2
              id="lead-title"
              className="font-serif font-semibold text-ink tracking-[-0.015em] leading-[1.12]
                         text-[clamp(1.625rem,1.2rem+1.3vw,2.25rem)] animate-reveal [animation-delay:60ms]"
            >
              <Link
                href={`/${lang}/threat/${lead.id}`}
                prefetch={false}
                className="decoration-signal/60 decoration-2 underline-offset-[6px] hover:underline"
              >
                {c.title}
              </Link>
            </h2>
            {plain && (
              <p className="mt-5 font-serif text-lead text-ink max-w-measure animate-rise [animation-delay:240ms]">
                {plain}
              </p>
            )}
            <FieldMarks
              post={lead}
              lang={lang}
              variant="inline"
              className="mt-5 animate-rise [animation-delay:300ms]"
            />
            {reason && (
              <p className="mt-3 font-sans text-[1rem] leading-relaxed text-ink-muted max-w-measure animate-rise [animation-delay:320ms]">
                <span className="font-semibold text-ink">
                  {s.severity_reason(s.level[lead.threat_level])}.
                </span>{" "}
                {reason}
              </p>
            )}
            {firstStep && (
              <p className="mt-3 font-sans text-[1rem] leading-relaxed text-ink-muted max-w-measure animate-rise [animation-delay:340ms]">
                <span className="font-semibold text-ink">{s.detail_what_to_do}:</span> {firstStep}
              </p>
            )}
            <div className="mt-7 flex flex-wrap items-center gap-x-6 gap-y-4 animate-rise [animation-delay:400ms]">
              <Link href={`/${lang}/threat/${lead.id}`} prefetch={false} className="btn-primary">
                {s.lead_read}
              </Link>
              {lead.source_url && (
                <a
                  href={lead.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="link inline-flex items-center gap-1 font-sans text-[1rem]"
                >
                  {s.lead_original(lead.source)}
                  <ArrowUpRight className="h-4 w-4" aria-hidden />
                </a>
              )}
            </div>
          </article>
        ) : (
          <div role="status" className="on-axis self-end">
            <p className="font-serif text-lead text-ink">{s.empty_backend_updating}</p>
            <p className="mt-2 text-ink-muted">{s.empty_no_data_hint}</p>
          </div>
        )}
      </div>
    </section>
  );
}
