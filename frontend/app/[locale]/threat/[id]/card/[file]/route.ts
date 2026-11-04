/**
 * GET /{locale}/threat/{id}/card/{variant}.{png|webp|avif}
 *
 * The branded card for one story edition, rendered on request and cached
 * (CDN + ISR). Stable, public HTTPS URL — usable for Open Graph, Telegram
 * and (later) Threads. 404 when the story has no text in this edition: a card
 * is never built from another language's headline.
 */
import sharp from "sharp";
import { fetchPost } from "@/lib/api";
import { isVariant, renderCard, type CardVariant } from "@/lib/media/card";
import { cardSpec, specHash } from "@/lib/media/spec";
import { illustrationDataUrl } from "@/lib/media/illustration";
import { isLocale } from "@/lib/types";

export const runtime = "nodejs";
export const revalidate = 300;

const ID_RE = /^[0-9a-f]{16}$/;
const FORMATS = { png: "image/png", webp: "image/webp", avif: "image/avif" } as const;
type Format = keyof typeof FORMATS;

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ locale: string; id: string; file: string }> },
): Promise<Response> {
  const { locale, id, file } = await params;
  const m = /^([a-z-]+)\.(png|webp|avif)$/.exec(file);
  if (!isLocale(locale) || !ID_RE.test(id) || !m || !isVariant(m[1])) {
    return new Response("Not found", { status: 404 });
  }
  const variant = m[1] as CardVariant;
  const format = m[2] as Format;

  const post = await fetchPost(id, { revalidate: 300 });
  const spec = post ? cardSpec(post, locale) : null;
  if (!post || !spec) return new Response("Not found", { status: 404 });

  // Optional editorial illustration (validated, served by the media store).
  const art = post.media?.illustration;
  if (art?.asset_id) {
    const dataUrl = await illustrationDataUrl(art.asset_id);
    if (dataUrl) spec.illustration = dataUrl;
  }

  let png: Buffer;
  try {
    png = await renderCard(spec, variant);
  } catch (err) {
    console.warn(`[card] render failed for ${locale}/${id}/${variant}: ${String(err)}`);
    return new Response("Card unavailable", { status: 503, headers: { "Cache-Control": "no-store" } });
  }
  const body =
    format === "png"
      ? png
      : format === "webp"
        ? await sharp(png).webp({ quality: 88 }).toBuffer()
        : await sharp(png).avif({ quality: 60 }).toBuffer();

  return new Response(new Uint8Array(body), {
    headers: {
      "Content-Type": FORMATS[format],
      "Content-Length": String(body.length),
      // A card is a pure function of its spec; the ETag is that hash.
      ETag: `"${specHash(spec)}-${variant}-${format}"`,
      "Cache-Control": "public, max-age=3600, s-maxage=86400, stale-while-revalidate=86400",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
