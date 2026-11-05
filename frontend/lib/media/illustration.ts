/**
 * Editorial illustrations, read from the backend's media store.
 *
 * The Python pipeline owns generation, validation and storage
 * (`cyberalertx/media/`); the API serves the stored source file internally at
 * `/media/{asset_id}`. The site re-validates what it receives (type, size,
 * decodable dimensions) before embedding or re-encoding it, so a bad file can
 * never reach a reader or a social network.
 */
import sharp from "sharp";
import { API_BASE } from "@/lib/api";

export const ASSET_ID_RE = /^[0-9a-f]{16,64}$/;
// SVG sources come only from the server-side renderer and are sanitized by
// the backend (cyberalertx/media/svg_art.py) before storage; sharp rasterizes
// them here, so the browser and social networks only ever receive PNG/WebP/AVIF.
const ALLOWED = new Set(["image/png", "image/jpeg", "image/webp", "image/svg+xml"]);
const MAX_BYTES = 8 * 1024 * 1024;

/** Validated source bytes, or null. */
export async function fetchIllustration(assetId: string): Promise<Buffer | null> {
  if (!ASSET_ID_RE.test(assetId)) return null;
  try {
    const res = await fetch(`${API_BASE}/media/${assetId}`, {
      next: { revalidate: 3600 },
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    const type = (res.headers.get("content-type") || "").split(";")[0].trim();
    if (!ALLOWED.has(type)) return null;
    const buf = Buffer.from(await res.arrayBuffer());
    if (buf.length === 0 || buf.length > MAX_BYTES) return null;
    if (type === "image/svg+xml" && !/^<svg[\s>]/.test(buf.subarray(0, 8).toString("utf8"))) return null;
    const meta = await sharp(buf).metadata();
    if (!meta.width || !meta.height || meta.width < 512 || meta.height < 512) return null;
    return buf;
  } catch {
    return null;
  }
}

/** PNG data URL for embedding in a card (Satori reads PNG/JPEG only). */
export async function illustrationDataUrl(assetId: string): Promise<string | null> {
  const src = await fetchIllustration(assetId);
  if (!src) return null;
  const png = await sharp(src).resize({ width: 1200, height: 1200, fit: "inside" }).png().toBuffer();
  return `data:image/png;base64,${png.toString("base64")}`;
}
