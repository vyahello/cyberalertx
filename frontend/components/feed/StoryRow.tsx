import Link from "next/link";
import { FieldMarks } from "@/components/marks/FieldMarks";
import { StoryVisual } from "@/components/media/StoryVisual";
import { HTML_LANG, contentFor, type Locale, type LocalizedThreatPost } from "@/lib/types";

interface Props {
  post: LocalizedThreatPost;
  lang: Locale;
  /** Heading level for the headline: 3 under a section h2, 4 under a day h3. */
  level?: 3 | 4;
}

/**
 * One entry in the feed. Field marks hang in the side-note column (from
 * `md`), the headline and plain-language lead sit on the axis. The whole
 * row is clickable through one stretched link, so there is exactly one tab
 * stop per story and no nested interactive elements.
 */
export function StoryRow({ post, lang, level = 4 }: Props) {
  const c = contentFor(post, lang);
  if (!c) return null;
  const title = c.title?.trim();
  if (!title) return null;
  const lead = c.plain_summary?.trim() || c.short_summary?.trim() || "";
  const Heading = level === 3 ? "h3" : "h4";

  return (
    <li className="feed-row">
      <article
        lang={HTML_LANG[lang]}
        className="feed-row__inner group relative
                   has-[a:focus-visible]:outline has-[a:focus-visible]:outline-2
                   has-[a:focus-visible]:outline-signal has-[a:focus-visible]:outline-offset-4"
      >
        <FieldMarks post={post} lang={lang} variant="row" className="md:pt-1.5" />
        <div className="min-w-0 flex items-start gap-5">
          <div className="min-w-0 flex-1">
          <Heading className="font-serif text-lead font-semibold text-ink break-words">
            <Link
              href={`/${lang}/threat/${post.id}`}
              prefetch={false}
              className="stretched focus-visible:outline-none
                         decoration-signal/60 decoration-1 underline-offset-[5px]
                         group-hover:underline"
            >
              {title}
            </Link>
          </Heading>
          {lead && (
            <p className="mt-1.5 font-serif text-body text-ink-muted max-w-measure line-clamp-2">
              {lead}
            </p>
          )}
          </div>
          {/* Decorative here: the headline is the link text; alt lives on the article page. */}
          <div className="hidden sm:block w-36 lg:w-44 shrink-0 mt-1" aria-hidden>
            <StoryVisual post={post} lang={lang} variant="preview" />
          </div>
        </div>
      </article>
    </li>
  );
}
