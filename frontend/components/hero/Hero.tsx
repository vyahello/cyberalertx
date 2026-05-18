import { ArrowDown } from "lucide-react";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";
import { LivePulse } from "./LivePulse";

interface Props {
  lang: Locale;
  activeThreats: number;
}

/**
 * Hero — first impression. Three jobs:
 *   1. Tell a new visitor what the product is (eyebrow + headline + subhead).
 *   2. Prove the product is alive (live pulse + active threat count).
 *   3. Provide a single, scroll-anchored CTA into the live feed.
 *
 * Visual treatment is deliberately quiet — no full-bleed photography, no
 * heavy motion. The animated background is a subtle radial drift; the
 * eye is meant to land on the headline, not the decoration.
 */
export function Hero({ lang, activeThreats }: Props) {
  const s = strings(lang);
  return (
    <section
      className="relative isolate overflow-hidden border-b border-border-subtle"
      aria-labelledby="hero-headline"
    >
      {/* Layered ambient background — radial color washes that drift slowly. */}
      <div
        aria-hidden
        className="absolute inset-0 hero-gradient animate-bg-drift will-change-transform"
      />
      {/* Faint grid texture for the "feels like a product, not a marketing page" feel. */}
      <div
        aria-hidden
        className="absolute inset-0 opacity-[0.04]"
        style={{
          backgroundImage:
            "linear-gradient(to right, #ffffff 1px, transparent 1px), linear-gradient(to bottom, #ffffff 1px, transparent 1px)",
          backgroundSize: "64px 64px",
        }}
      />

      <div className="relative mx-auto max-w-6xl px-5 sm:px-8 py-16 sm:py-24 lg:py-32">
        <p className="inline-flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-text-secondary mb-5">
          <LivePulse size="sm" />
          {s.hero_eyebrow}
        </p>

        <h1
          id="hero-headline"
          className="text-4xl sm:text-5xl font-semibold text-text-primary
                     tracking-tight leading-[1.05] mb-5 max-w-3xl text-balance"
        >
          {s.hero_headline}
        </h1>

        <p className="text-base sm:text-lg text-text-secondary leading-relaxed max-w-2xl mb-8">
          {s.hero_subhead}
        </p>

        <div className="flex flex-wrap items-center gap-4">
          <a href="#feed" className="btn-primary">
            {s.hero_cta}
            <ArrowDown className="w-4 h-4" strokeWidth={2.5} />
          </a>
          <p className="inline-flex items-center gap-2 text-sm text-text-secondary">
            <LivePulse size="sm" />
            <span>
              <span className="font-medium text-text-primary tabular-nums">
                {activeThreats}
              </span>{" "}
              {/* Render the trailing label without the leading number — the
                  number is highlighted above; this line reads "23 active threats now". */}
              {s.hero_pulse_label(activeThreats).replace(`${activeThreats} `, "")}
            </span>
          </p>
        </div>
      </div>
    </section>
  );
}
