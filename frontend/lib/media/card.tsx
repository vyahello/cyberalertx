/**
 * Branded story cards — deterministic, no AI.
 *
 * Rendered with `next/og` (Satori → SVG → PNG via resvg), so the same input
 * always produces the same pixels. Converted to WebP / AVIF with sharp, which
 * already ships with Next. Fonts are the site's own faces as static TTFs
 * (Satori cannot read the variable WOFF2 files the site loads):
 *   Literata SemiBold (headline), Fira Sans Condensed (marks, labels),
 *   Space Grotesk SemiBold (the "cyberalert" logotype). All OFL.
 *
 * Every field on a card comes from the story's own edition (EN or UA). Fields
 * the story doesn't have are left out — never filled with placeholders.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";
import { ImageResponse } from "next/og";
import type { ReactElement } from "react";

export type CardVariant = "og" | "telegram" | "threads-portrait" | "threads-square" | "preview";

export const VARIANTS: Record<CardVariant, { width: number; height: number }> = {
  og: { width: 1200, height: 630 },
  telegram: { width: 1200, height: 675 },
  "threads-portrait": { width: 1080, height: 1350 },
  "threads-square": { width: 1080, height: 1080 },
  preview: { width: 640, height: 360 },
};

export function isVariant(x: string): x is CardVariant {
  return Object.hasOwn(VARIANTS, x);
}

/** What a card may show. Only `title` and `locale` are required; an empty
 *  `categoryLabel` (category "other") is simply not drawn. */
export interface CardSpec {
  locale: "en" | "ua";
  title: string;
  categoryLabel: string;
  /** Severity word, e.g. "Critical" / "Критичний" — only when the story has one. */
  severity?: { level: "Critical" | "High" | "Medium" | "Low"; label: string };
  /** e.g. "Exploited in attacks" — only when the pipeline flagged it. */
  contextLabel?: string;
  /** Formatted publication date in the edition's language. */
  date?: string;
  /** One technical identifier the story itself names (a CVE). */
  identifier?: string;
  /** Data URL or absolute URL of a validated editorial illustration. */
  illustration?: string;
}

// Design tokens (mirrors tailwind.config.ts / docs/design/DESIGN_SYSTEM.md).
const T = {
  ground: "#0E1116",
  raised: "#161B22",
  high: "#1E242D",
  ink: "#ECEEF1",
  muted: "#A6AEBA",
  faint: "#8C95A3",
  signal: "#06B6D4",
  ping: "#00E5FF",
  sev: { Critical: "#FF5C6C", High: "#FF9F43", Medium: "#EDE58A", Low: "#8C95A3" },
  segments: { Critical: 4, High: 3, Medium: 2, Low: 1 },
} as const;

const FONT_DIR = path.join(process.cwd(), "assets", "fonts");
let fontCache: Promise<{ name: string; data: Buffer; weight: 500 | 600; style: "normal" }[]> | null = null;

function fonts() {
  fontCache ??= Promise.all([
    readFile(path.join(FONT_DIR, "Literata-SemiBold.ttf")).then((data) => ({ name: "Literata", data, weight: 600 as const, style: "normal" as const })),
    readFile(path.join(FONT_DIR, "FiraSansCondensed-Medium.ttf")).then((data) => ({ name: "Fira", data, weight: 500 as const, style: "normal" as const })),
    readFile(path.join(FONT_DIR, "FiraSansCondensed-SemiBold.ttf")).then((data) => ({ name: "Fira", data, weight: 600 as const, style: "normal" as const })),
    readFile(path.join(FONT_DIR, "SpaceGrotesk-SemiBold.ttf")).then((data) => ({ name: "Grotesk", data, weight: 600 as const, style: "normal" as const })),
  ]);
  return fontCache;
}

/**
 * Largest headline size that fits `maxLines` at this text width, never below
 * `floor` (readable when Telegram shows the card at half size). If even the
 * floor needs more lines, the headline is clamped with an ellipsis rather
 * than shrunk further.
 */
export function headlineSize(
  title: string,
  textWidth: number,
  maxLines: number,
  sizes: number[],
  floor: number,
): { size: number; clamped: boolean } {
  // Average advance of Literata SemiBold ≈ 0.53 em (Latin), ≈ 0.56 em (Cyrillic).
  const cyr = /[Ѐ-ӿ]/.test(title);
  const em = cyr ? 0.56 : 0.53;
  for (const size of sizes) {
    if (size < floor) break;
    const perLine = Math.floor(textWidth / (size * em));
    if (lines(title, perLine) <= maxLines) return { size, clamped: false };
  }
  return { size: floor, clamped: true };
}

/** Greedy word wrap — counts lines the way a browser would, roughly. */
function lines(text: string, perLine: number): number {
  let n = 1;
  let used = 0;
  for (const word of text.split(/\s+/)) {
    const w = word.length;
    if (used === 0) used = w;
    else if (used + 1 + w <= perLine) used += 1 + w;
    else {
      n += 1;
      used = w;
    }
  }
  return n;
}

function Glyph({ size, ring }: { size: number; ring: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100">
      <g fill="none" stroke={ring} strokeWidth="3.5">
        <circle cx="50" cy="50" r="42" opacity="0.22" />
        <circle cx="50" cy="50" r="30" opacity="0.45" />
        <circle cx="50" cy="50" r="18" opacity="0.7" />
      </g>
      <circle cx="50" cy="50" r="5" fill={ring} />
      <circle cx="76" cy="24" r="14" fill="none" stroke={T.ping} strokeWidth="2" opacity="0.35" />
      <circle cx="76" cy="24" r="9" fill={T.ping} />
    </svg>
  );
}

function Severity({ sev, scale }: { sev: NonNullable<CardSpec["severity"]>; scale: number }) {
  const n = T.segments[sev.level];
  const colour = T.sev[sev.level];
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 10 * scale }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 4 * scale }}>
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            style={{
              width: 7 * scale,
              height: (9 + i * 4) * scale,
              background: i <= n ? colour : T.high,
            }}
          />
        ))}
      </div>
      <div style={{ color: colour, fontFamily: "Fira", fontWeight: 600, fontSize: 26 * scale, lineHeight: 1 }}>
        {sev.label}
      </div>
    </div>
  );
}

/** The card. One layout, three orientations; the illustration (when present)
 *  takes the right third (landscape) or the top half (portrait/square). */
export function Card({ spec, variant }: { spec: CardSpec; variant: CardVariant }): ReactElement {
  const { width, height } = VARIANTS[variant];
  const scale = width / 1200;
  const portrait = height >= width;
  const pad = Math.round((portrait ? 72 : 64) * (portrait ? width / 1080 : scale));
  const s = portrait ? width / 1080 : scale;
  const art = spec.illustration;
  const textWidth = portrait || !art ? width - 2 * pad : Math.round(width * 0.6) - 2 * pad;
  const maxLines = portrait ? (art ? 4 : 6) : variant === "preview" ? 3 : 3;
  const sizes = (portrait ? [84, 76, 68, 60, 54, 48] : [68, 62, 56, 50, 46, 42]).map((x) => Math.round(x * s));
  const { size, clamped } = headlineSize(spec.title, textWidth, maxLines, sizes, Math.round((portrait ? 48 : 42) * s));
  const edition = spec.locale === "ua" ? "UA" : "EN";

  const marks = (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: 22 * s }}>
      {spec.severity && <Severity sev={spec.severity} scale={s} />}
      {spec.categoryLabel && (
        <div style={{ color: T.muted, fontFamily: "Fira", fontWeight: 600, fontSize: 26 * s, lineHeight: 1 }}>
          {spec.categoryLabel}
        </div>
      )}
      {spec.contextLabel && (
        <div style={{ color: T.sev.Critical, fontFamily: "Fira", fontWeight: 600, fontSize: 26 * s, lineHeight: 1 }}>
          {spec.contextLabel}
        </div>
      )}
    </div>
  );

  const footer = (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
      <div style={{ display: "flex", gap: 18 * s, color: T.faint, fontFamily: "Fira", fontWeight: 500, fontSize: 24 * s }}>
        {spec.date && <div>{spec.date}</div>}
        {spec.identifier && <div style={{ color: T.muted }}>{spec.identifier}</div>}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 * s }}>
        <div style={{ color: T.ink, fontFamily: "Grotesk", fontWeight: 600, fontSize: 30 * s, letterSpacing: -0.9 * s }}>
          cyberalert
        </div>
        <Glyph size={Math.round(26 * s)} ring={T.muted} />
        <div style={{ marginLeft: 8 * s, color: T.faint, fontFamily: "Fira", fontWeight: 600, fontSize: 22 * s }}>
          {edition}
        </div>
      </div>
    </div>
  );

  const text = (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        flex: 1,
        padding: pad,
        gap: 24 * s,
      }}
    >
      {marks}
      <div
        style={{
          display: "block",
          // Portrait without art: the headline sits low, above the footer,
          // instead of floating between two voids.
          ...(portrait && !art ? { marginTop: "auto" } : {}),
          color: T.ink,
          fontFamily: "Literata",
          fontWeight: 600,
          fontSize: size,
          lineHeight: 1.12,
          letterSpacing: -0.01 * size,
          ...(clamped ? { lineClamp: maxLines } : {}),
        }}
      >
        {spec.title}
      </div>
      {footer}
    </div>
  );

  if (!art) {
    return (
      <div style={{ display: "flex", width, height, background: T.ground }}>
        {text}
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: portrait ? "column" : "row-reverse", width, height, background: T.ground }}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={art}
        alt=""
        width={portrait ? width : Math.round(width * 0.4)}
        height={portrait ? Math.round(height * 0.46) : height}
        style={{ objectFit: "cover" }}
      />
      {text}
    </div>
  );
}

export async function renderCard(spec: CardSpec, variant: CardVariant): Promise<Buffer> {
  const { width, height } = VARIANTS[variant];
  const res = new ImageResponse(<Card spec={spec} variant={variant} />, {
    width,
    height,
    fonts: await fonts(),
  });
  return Buffer.from(await res.arrayBuffer());
}
