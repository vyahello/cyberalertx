import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { ArticleMarks } from "@/components/article/ArticleMarks";
import { InlineText, RichText } from "@/components/article/RichText";
import { ShareBar } from "@/components/share/ShareBar";
import { FeedbackWidget } from "./FeedbackWidget";
import { strings } from "@/lib/i18n";
import { topicForCategory } from "@/lib/topics";
import {
  HTML_LANG,
  contentFor,
  type DetailContext,
  type Locale,
  type LocalizedContent,
  type LocalizedThreatPost,
  type ThreatReference,
} from "@/lib/types";

interface Props {
  post: LocalizedThreatPost;
  lang: Locale;
}

const H2 = "font-serif font-semibold text-ink text-[clamp(1.375rem,1.1rem+0.6vw,1.75rem)] leading-tight";
const H3 = "font-sans text-[1rem] font-semibold text-ink";
const SECTION = "mt-12 first:mt-0 scroll-mt-24 enter";

/** Words per minute for the reading-time estimate. */
const WPM: Record<Locale, number> = { en: 220, ua: 190 };

function words(c: LocalizedContent): number {
  return [
    c.title,
    c.plain_summary,
    c.short_summary,
    c.detail_body,
    c.why_it_matters,
    ...(c.affected_users ?? []),
    ...(c.am_i_affected ?? []),
    ...(c.if_already_affected ?? []),
    ...(c.what_to_do ?? []),
    ...(c.what_not_to_do ?? []),
    ...(c.quick_facts ?? []),
  ]
    .filter(Boolean)
    .join(" ")
    .split(/\s+/)
    .filter(Boolean).length;
}

/**
 * The brief as one continuous article. Field marks sit in the side-note
 * column (sticky on desktop); the text runs on the axis at a reading
 * measure. Each fact appears once: the plain summary is the standfirst,
 * the attributed summary opens "What happened", the severity reason lives
 * in the marks.
 */
export function ThreatDetail({ post, lang }: Props) {
  const s = strings(lang);
  const c = contentFor(post, lang);
  if (!c) return <NotAvailableInLocale lang={lang} post={post} />;

  const plain = c.plain_summary?.trim();
  const short = c.short_summary?.trim();
  const standfirst = plain || short;
  const opener = plain ? short : "";
  const checks = (c.am_i_affected ?? []).filter((x) => x.trim());
  const recovery = (c.if_already_affected ?? []).filter((x) => x.trim());
  const toDo = (c.what_to_do ?? []).filter((x) => x.trim());
  const avoid = (c.what_not_to_do ?? []).filter((x) => x.trim());
  const facts = (c.quick_facts ?? []).filter((x) => x.trim());
  const affected = (c.affected_users ?? []).filter((x) => x.trim());
  const topic = topicForCategory(post.category);
  const illustration = post.media?.illustration;
  const readingSeconds = Math.round((words(c) / WPM[lang]) * 60);

  return (
    <article lang={HTML_LANG[lang]} className="page pt-6 sm:pt-10">
      <nav aria-label={s.breadcrumb_label} className="axis">
        <ol className="on-axis flex flex-wrap items-center gap-x-2 font-sans text-small text-ink-faint">
          <li>
            <Link href={`/${lang}`} prefetch={false} className="hover:text-ink underline-offset-4 hover:underline">
              {s.edition_title}
            </Link>
          </li>
          {topic && (
            <>
              <li aria-hidden>/</li>
              <li>
                <Link
                  href={`/${lang}/topic/${topic}`}
                  prefetch={false}
                  className="hover:text-ink underline-offset-4 hover:underline"
                >
                  {s.topic[topic].name}
                </Link>
              </li>
            </>
          )}
        </ol>
      </nav>

      <div className="axis mt-5 gap-y-8">
        <header className="lg:col-start-2 lg:row-start-1">
          <h1 className="t-head text-ink break-words animate-reveal">{c.title}</h1>
          {standfirst && (
            <p className="mt-5 font-serif text-lead text-ink-muted max-w-measure animate-rise [animation-delay:160ms]">
              {standfirst}
            </p>
          )}
          {illustration && (
            <figure className="mt-8">
              {/* Explicit width/height + aspect ratio: no layout shift. */}
              <picture>
                <source type="image/avif" srcSet={`/media/${illustration.asset_id}/article.avif`} />
                <source type="image/webp" srcSet={`/media/${illustration.asset_id}/article.webp`} />
                <img
                  src={`/media/${illustration.asset_id}/article.png`}
                  width={1600}
                  height={900}
                  alt={illustration.alt[lang] ?? ""}
                  loading="eager"
                  decoding="async"
                  className="block h-auto w-full bg-ground-raised aspect-[16/9] object-cover"
                />
              </picture>
              <figcaption className="mt-2 font-sans text-small text-ink-faint">
                {s.illustration_caption}
              </figcaption>
            </figure>
          )}
        </header>

        <aside
          aria-label={s.mark_severity}
          className="lg:col-start-1 lg:row-start-1 lg:row-span-2 lg:justify-self-end lg:w-full lg:max-w-[18rem]"
        >
          <div className="lg:sticky lg:top-[calc(var(--header-h)+1.5rem)] bg-ground-raised p-5 lg:bg-transparent lg:p-0">
            <ArticleMarks
              post={post}
              content={c}
              lang={lang}
              readingSeconds={readingSeconds}
              hasActions={toDo.length > 0}
            />
          </div>
        </aside>

        <div className="lg:col-start-2 lg:row-start-2 min-w-0">
          <div className="prose-brief">
          {(opener || c.detail_body?.trim()) && (
            <section aria-labelledby="sec-what" className={SECTION}>
              <h2 id="sec-what" className={H2}>
                {s.detail_what_happened}
              </h2>
              <div className="mt-4">
                {opener && (
                  <p>
                    <InlineText text={opener} />
                  </p>
                )}
                <RichText text={c.detail_body} className="mt-4" />
              </div>
            </section>
          )}

          {c.why_it_matters?.trim() && (
            <section aria-labelledby="sec-why" className={SECTION}>
              <h2 id="sec-why" className={H2}>
                {s.detail_why}
              </h2>
              <p className="mt-4">
                <InlineText text={c.why_it_matters} />
              </p>
            </section>
          )}

          {(affected.length > 0 || checks.length > 0 || recovery.length > 0) && (
            <section aria-labelledby="sec-affected" className={SECTION}>
              <h2 id="sec-affected" className={H2}>
                {s.detail_affected}
              </h2>
              {affected.length > 0 && (
                <>
                  <h3 className={`${H3} mt-5`}>{s.detail_who_affected}</h3>
                  <ul className="mt-2 list-disc pl-5 space-y-1.5 marker:text-ink-faint">
                    {affected.map((u) => (
                      <li key={u}>{u}</li>
                    ))}
                  </ul>
                </>
              )}
              {checks.length > 0 && (
                <>
                  <p className="mt-5 font-sans text-small text-ink-faint">{s.detail_checks_hint}</p>
                  <ol className="mt-2 list-decimal pl-6 space-y-2 marker:font-sans marker:text-ink-faint">
                    {checks.map((step) => (
                      <li key={step} className="pl-1">
                        <InlineText text={step} />
                      </li>
                    ))}
                  </ol>
                </>
              )}
              {recovery.length > 0 && (
                <div className="mt-6 bg-ground-raised p-5">
                  <h3 className={`${H3} text-sev-critical`}>{s.detail_already}</h3>
                  <ul className="mt-2 list-disc pl-5 space-y-1.5 marker:text-ink-faint">
                    {recovery.map((step) => (
                      <li key={step}>
                        <InlineText text={step} />
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}

          {(toDo.length > 0 || avoid.length > 0) && (
            <section id="actions" aria-labelledby="sec-actions" className={SECTION}>
              <h2 id="sec-actions" className={H2}>
                {s.detail_what_to_do}
              </h2>
              {toDo.length > 0 && (
                <ol className="mt-4 list-decimal pl-6 space-y-2.5 marker:font-sans marker:font-semibold marker:text-signal">
                  {toDo.map((item) => (
                    <li key={item} className="pl-1">
                      <InlineText text={item} />
                    </li>
                  ))}
                </ol>
              )}
              {avoid.length > 0 && (
                <>
                  <h3 className={`${H3} mt-6`}>{s.detail_avoid}</h3>
                  <ul className="mt-2 list-disc pl-5 space-y-1.5 marker:text-sev-critical">
                    {avoid.map((item) => (
                      <li key={item}>
                        <InlineText text={item} />
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
          )}

          {facts.length > 0 && (
            <section aria-labelledby="sec-facts" className={SECTION}>
              <h2 id="sec-facts" className={H2}>
                {s.detail_key_facts}
              </h2>
              <KeyFacts facts={facts} />
            </section>
          )}

          <SourcesSection post={post} refs={c.references} lang={lang} />

          <BackgroundSection context={post.detail_context?.[lang]} lang={lang} />
          </div>

          <div className="mt-14 max-w-measure space-y-10 font-sans">
            <ShareBar title={c.title} lang={lang} />
            <FeedbackWidget postId={post.id} lang={lang} />
          </div>
        </div>
      </div>
    </article>
  );
}

// ---------------------------------------------------------------- parts

/** "Label: value" facts become a definition list; anything else a list. */
function KeyFacts({ facts }: { facts: string[] }) {
  const pairs = facts.map((f) => {
    const m = f.match(/^([^:]{2,40}):\s+(.+)$/);
    return m ? { label: m[1].trim(), value: m[2].trim() } : null;
  });
  if (pairs.every(Boolean)) {
    return (
      <dl className="mt-4 grid gap-x-6 gap-y-3 font-sans text-[1rem] sm:grid-cols-[minmax(8rem,auto)_minmax(0,1fr)]">
        {pairs.map((p) => (
          <div key={p!.label + p!.value} className="contents">
            <dt className="text-ink-faint">{p!.label}</dt>
            <dd className="text-ink">
              <InlineText text={p!.value} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return (
    <ul className="mt-4 list-disc pl-5 space-y-1.5 marker:text-ink-faint">
      {facts.map((f) => (
        <li key={f}>
          <InlineText text={f} />
        </li>
      ))}
    </ul>
  );
}

function SourcesSection({
  post,
  refs,
  lang,
}: {
  post: LocalizedThreatPost;
  refs: ThreatReference[] | undefined;
  lang: Locale;
}) {
  const s = strings(lang);
  const others = (post.story_coverage ?? []).filter(
    (c) => c.url && c.url !== post.source_url && c.source !== post.source,
  );
  const references = (refs ?? []).filter((r) => r.url && r.label);

  return (
    <section aria-labelledby="sec-sources" className={SECTION}>
      <h2 id="sec-sources" className={H2}>
        {s.detail_sources}
      </h2>
      <p className="mt-3 font-sans text-small text-ink-faint">{s.detail_provenance(post.source)}</p>

      {post.source_url && (
        <div className="mt-5">
          <h3 className={H3}>{s.detail_original}</h3>
          <a
            href={post.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 inline-flex items-start gap-1 font-sans text-[1rem] font-semibold"
          >
            <span>{post.source}</span>
            <ArrowUpRight className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden />
          </a>
        </div>
      )}

      {others.length > 0 && (
        <div className="mt-5">
          <h3 className={H3}>{s.detail_coverage}</h3>
          <ul className="mt-1 space-y-1.5 font-sans text-[1rem]">
            {others.map((o) => (
              <li key={o.url}>
                <a href={o.url} target="_blank" rel="noopener noreferrer">
                  {o.source}
                </a>
                {o.title && <span className="text-ink-faint"> — {o.title}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {references.length > 0 && (
        <div className="mt-5">
          <h3 className={H3}>{s.detail_references}</h3>
          <ul className="mt-1 flex flex-wrap gap-x-5 gap-y-1.5 font-sans text-[1rem]">
            {references.map((r, i) => (
              <li key={`${r.label}-${i}`}>
                <a href={r.url} target="_blank" rel="noopener noreferrer" className="whitespace-nowrap">
                  {r.label}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function BackgroundSection({
  context,
  lang,
}: {
  context: DetailContext | undefined;
  lang: Locale;
}) {
  if (!context) return null;
  const s = strings(lang);
  const blocks = [
    { label: s.context_how_it_works, body: context.how_it_works },
    { label: s.context_who_is_affected, body: context.who_is_affected },
    { label: s.context_attacker_motivation, body: context.attacker_motivation },
    { label: s.context_realistic_impact, body: context.realistic_impact },
  ].filter((b) => b.body?.trim());
  if (blocks.length === 0) return null;

  return (
    <section aria-labelledby="sec-context" className={`${SECTION} bg-ground-raised p-5 sm:p-7`}>
      <h2 id="sec-context" className={H2}>
        {s.context_heading}
      </h2>
      <div className="mt-4 space-y-5">
        {blocks.map((b) => (
          <div key={b.label}>
            <h3 className={H3}>{b.label}</h3>
            <p className="mt-1 text-ink-muted">{b.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

function NotAvailableInLocale({ lang, post }: { lang: Locale; post: LocalizedThreatPost }) {
  const s = strings(lang);
  const other = post.available_locales[0];
  return (
    <div className="page py-section">
      <div className="axis">
        <div className="on-axis">
          <h1 className="t-head text-ink">{s.detail_not_available_in_locale}</h1>
          <p className="mt-4 text-ink-muted max-w-measure">{s.detail_not_available_hint}</p>
          <div className="mt-8 flex flex-wrap gap-4">
            {other && (
              <Link href={`/${other}/threat/${post.id}`} prefetch={false} className="btn-primary">
                {other === "ua" ? "Українською" : "In English"}
              </Link>
            )}
            <Link href={`/${lang}`} prefetch={false} className="btn-quiet">
              {s.detail_back_home}
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
