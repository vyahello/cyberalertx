"use client";

import { useEffect, useState } from "react";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

interface Props {
  /** ISO 8601 timestamp from the backend (always UTC). */
  iso: string;
  /** Locale for the rendered label ("just now" vs "щойно"). */
  lang: Locale;
}

/**
 * Live-updating "X min ago" timestamp.
 *
 * Why a client component: the relative label is computed against the
 * client's wall clock. Without a periodic re-render, a server-rendered
 * "just now" stays "just now" in an open tab indefinitely (until ISR
 * re-renders the page and the user navigates back). This component
 * re-evaluates every 60s so the label crawls forward like a clock
 * hand without the user touching anything.
 *
 * SSR consideration: on first paint we render the same label
 * server-rendered HTML would (no extra network, no flicker). The
 * `tick` state is only there to force a re-evaluation on the
 * interval — its value isn't read.
 */
export function RelativeTime({ iso, lang }: Props) {
  const [, setTick] = useState(0);

  useEffect(() => {
    // Re-render every minute. 60s matches the granularity of the
    // formatter (it rounds to whole minutes), so a tighter interval
    // would burn re-renders without changing what the user sees.
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);

  return <>{strings(lang).card_published_relative(iso)}</>;
}
