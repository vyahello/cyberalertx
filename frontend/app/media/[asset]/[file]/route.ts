/**
 * GET /media/{asset_id}/{variant}.{png|webp|avif}
 *
 * Public, stable URL for an editorial illustration's platform variants. Every
 * variant is cut from the one stored source with an attention-based crop —
 * never stretched — so OG, Telegram and Threads share the same artwork.
 */
import sharp from "sharp";
import { ASSET_ID_RE, fetchIllustration } from "@/lib/media/illustration";

export const runtime = "nodejs";
// Short enough that a withdrawn illustration (status no longer validated)
// stops being served within the hour; the bytes themselves never change.
export const revalidate = 3600;

const SIZES: Record<string, { width: number; height: number }> = {
  article: { width: 1600, height: 900 },
  og: { width: 1200, height: 630 },
  telegram: { width: 1200, height: 675 },
  "threads-portrait": { width: 1080, height: 1350 },
  "threads-square": { width: 1080, height: 1080 },
  preview: { width: 640, height: 360 },
};
const TYPES = { png: "image/png", webp: "image/webp", avif: "image/avif" } as const;

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ asset: string; file: string }> },
): Promise<Response> {
  const { asset, file } = await params;
  const m = /^([a-z-]+)\.(png|webp|avif)$/.exec(file);
  if (!ASSET_ID_RE.test(asset) || !m || !Object.hasOwn(SIZES, m[1])) {
    return new Response("Not found", { status: 404 });
  }
  const src = await fetchIllustration(asset);
  if (!src) return new Response("Not found", { status: 404 });
  const { width, height } = SIZES[m[1]];
  const format = m[2] as keyof typeof TYPES;
  const pipeline = sharp(src).resize({ width, height, fit: "cover", position: sharp.strategy.attention });
  const body =
    format === "png"
      ? await pipeline.png().toBuffer()
      : format === "webp"
        ? await pipeline.webp({ quality: 86 }).toBuffer()
        : await pipeline.avif({ quality: 58 }).toBuffer();
  return new Response(new Uint8Array(body), {
    headers: {
      "Content-Type": TYPES[format],
      "Content-Length": String(body.length),
      // Asset ids are content hashes: a new image gets a new URL.
      "Cache-Control": "public, max-age=86400, s-maxage=86400",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
