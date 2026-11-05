"use client";

import { useEffect, useId, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { strings } from "@/lib/i18n";
import { TELEGRAM_CHANNELS } from "@/lib/site";
import type { Locale } from "@/lib/types";
import { SiteNav } from "./SiteNav";

/**
 * Below `lg` the section links fold behind a hamburger. Open, the three
 * lines turn into an X and a full-height graphite panel covers the page
 * under the header. Body scroll is locked while open; Escape, a link or the
 * X closes it, and focus returns to the button.
 */
export function MobileMenu({ lang }: { lang: Locale }) {
  const s = strings(lang);
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const panelId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.querySelector<HTMLElement>("a, button")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        button.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const bar = "absolute left-1/2 h-[2px] w-[22px] -translate-x-1/2 rounded-sm bg-current transition-transform duration-200 ease-out motion-reduce:transition-none";

  return (
    <div className="lg:hidden">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={open ? s.nav_menu_close : s.nav_menu_open}
        onClick={() => setOpen((v) => !v)}
        className="relative -mr-2 inline-flex h-11 w-11 items-center justify-center text-ink hover:text-signal-hover"
      >
        <span aria-hidden="true" className="relative block h-[16px] w-[22px]">
          <span className={`${bar} top-0 ${open ? "translate-y-[7px] rotate-45" : ""}`} />
          <span className={`${bar} top-[7px] transition-opacity ${open ? "opacity-0" : "opacity-100"}`} />
          <span className={`${bar} top-[14px] ${open ? "-translate-y-[7px] -rotate-45" : ""}`} />
        </span>
      </button>
      <div
        id={panelId}
        ref={panel}
        hidden={!open}
        className="fixed inset-x-0 bottom-0 top-[calc(4rem+env(safe-area-inset-top))] z-30 overflow-y-auto
                   overscroll-contain bg-ground-raised"
      >
        <nav
          aria-label={s.nav_label}
          className="page pb-[calc(2rem+env(safe-area-inset-bottom))] pt-2"
          onClick={(e) => {
            // Also close for the link to the current page (no route change).
            if ((e.target as HTMLElement).closest("a")) setOpen(false);
          }}
        >
          <SiteNav
            lang={lang}
            className="flex flex-col divide-y divide-line border-b border-line"
            itemClassName="flex w-full min-h-[56px] text-lead"
          />
          <div className="mt-6">
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
