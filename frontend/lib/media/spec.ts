/**
 * Story → card spec. Pure: the same post and locale always give the same
 * spec, and the spec's hash changes only when something visible changes.
 */
import { createHash } from "node:crypto";
import { strings } from "@/lib/i18n";
import { contentFor, type Locale, type LocalizedThreatPost } from "@/lib/types";
import type { CardSpec, CardVariant } from "./card";

/** Bump when the card layout changes, so cached URLs refresh. */
export const CARD_VERSION = "card-1";

const CVE_RE = /\bCVE-\d{4}-\d{4,7}\b/i;

function cardDate(iso: string, lang: Locale): string | undefined {
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return undefined;
  return new Intl.DateTimeFormat(lang === "ua" ? "uk-UA" : "en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: lang === "ua" ? "Europe/Kyiv" : "UTC",
  }).format(d);
}

/** Null when the story has no text in this edition — a card is never made
 *  from another edition's headline. */
export function cardSpec(post: LocalizedThreatPost, lang: Locale): CardSpec | null {
  const c = contentFor(post, lang);
  const title = c?.title?.trim();
  if (!c || !title) return null;
  const s = strings(lang);
  const identifier =
    (c.references ?? []).map((r) => r.label).find((l) => CVE_RE.test(l))?.match(CVE_RE)?.[0] ??
    title.match(CVE_RE)?.[0];
  return {
    locale: lang,
    title,
    // "Other" says nothing a reader can use; leave the slot empty instead.
    categoryLabel: post.category && post.category !== "other" ? s.category[post.category] ?? "" : "",
    severity: post.threat_level
      ? { level: post.threat_level, label: s.level[post.threat_level] }
      : undefined,
    contextLabel: post.signals?.active_exploitation ? s.mark_exploited : undefined,
    date: cardDate(post.published_at, lang),
    identifier: identifier?.toUpperCase(),
  };
}

export function specHash(spec: CardSpec): string {
  const { illustration, ...visible } = spec;
  return createHash("sha256")
    .update(JSON.stringify({ v: CARD_VERSION, ...visible, art: illustration ? createHash("sha256").update(illustration).digest("hex") : "" }))
    .digest("hex")
    .slice(0, 16);
}

/** Public path of a card variant. `v` is cache-busting only. */
export function cardPath(lang: Locale, id: string, variant: CardVariant, format: "png" | "webp" | "avif" = "png", v?: string): string {
  return `/${lang}/threat/${id}/card/${variant}.${format}${v ? `?v=${v}` : ""}`;
}
