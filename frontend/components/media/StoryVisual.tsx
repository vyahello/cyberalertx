import type { Locale, LocalizedThreatPost } from "@/lib/types";

type Variant = "preview" | "og" | "article";
const SIZE: Record<Variant, { width: number; height: number; aspect: string }> = {
  preview: { width: 640, height: 360, aspect: "aspect-[16/9]" },
  og: { width: 1200, height: 630, aspect: "aspect-[40/21]" },
  article: { width: 1600, height: 900, aspect: "aspect-[16/9]" },
};

interface Props {
  post: LocalizedThreatPost;
  lang: Locale;
  variant: Variant;
  eager?: boolean;
  className?: string;
}

/**
 * The story's canonical illustration (the same asset Telegram attaches), or
 * the branded pending visual while it is being rendered. Explicit width,
 * height and aspect ratio: no layout shift either way. Never a publisher's
 * image.
 */
export function StoryVisual({ post, lang, variant, eager = false, className = "" }: Props) {
  const { width, height, aspect } = SIZE[variant];
  const ill = post.media?.illustration;
  const cls = `block h-auto w-full bg-ground-raised object-cover ${aspect} ${className}`;
  if (!ill) {
    return (
      <img
        src="/brand/visual-pending.svg"
        width={width}
        height={height}
        alt=""
        aria-hidden
        loading={eager ? "eager" : "lazy"}
        decoding="async"
        className={cls}
      />
    );
  }
  const base = `/media/${ill.asset_id}/${variant}`;
  return (
    <picture>
      <source type="image/avif" srcSet={`${base}.avif`} />
      <source type="image/webp" srcSet={`${base}.webp`} />
      <img
        src={`${base}.png`}
        width={width}
        height={height}
        alt={ill.alt[lang] ?? ""}
        loading={eager ? "eager" : "lazy"}
        decoding="async"
        className={cls}
      />
    </picture>
  );
}
