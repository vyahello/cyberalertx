"use client";

import { useEffect, useState } from "react";
import { strings } from "@/lib/i18n";
import type { Locale } from "@/lib/types";

interface Props {
  iso: string;
  lang: Locale;
  className?: string;
}

/**
 * Relative publication time ("2 h ago") that keeps itself current. The
 * machine-readable timestamp and the full date ride along on <time>, so the
 * relative wording never stands alone.
 */
export function TimeAgo({ iso, lang, className }: Props) {
  const s = strings(lang);
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);
  return (
    <time
      dateTime={iso}
      title={s.published_absolute(iso)}
      className={className}
      // Server and client can disagree by a minute; the client value wins.
      suppressHydrationWarning
    >
      {s.published_relative(iso)}
    </time>
  );
}
