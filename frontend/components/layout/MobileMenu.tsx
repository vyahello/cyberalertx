"use client";

import { useEffect, useId, useState } from "react";
import { usePathname } from "next/navigation";
import { strings } from "@/lib/i18n";
import { TELEGRAM_CHANNELS } from "@/lib/site";
import type { Locale } from "@/lib/types";
import { SiteNav } from "./SiteNav";

/**
 * Below `lg` the section links fold behind a "Menu" word. The panel opens
 * in place under the bar (a disclosure, not a modal) and closes on
 * navigation and on Escape.
 */
export function MobileMenu({ lang }: { lang: Locale }) {
  const s = strings(lang);
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const panelId = useId();

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="lg:hidden">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-11 items-center px-3 -mr-3 font-sans text-[1rem] font-semibold text-ink hover:text-signal-hover"
      >
        {open ? s.menu_close : s.menu_open}
      </button>
      <div
        id={panelId}
        hidden={!open}
        className="absolute inset-x-0 top-full bg-ground-raised"
      >
        <nav aria-label={s.nav_label} className="page py-4">
          <SiteNav lang={lang} className="flex flex-col" itemClassName="min-h-[48px] text-lead" />
          <div className="mt-4">
            <a
              href={TELEGRAM_CHANNELS[lang]}
              target="_blank"
              rel="noopener noreferrer"
              className="link font-sans font-semibold"
            >
              {s.telegram}
            </a>
          </div>
        </nav>
      </div>
    </div>
  );
}
