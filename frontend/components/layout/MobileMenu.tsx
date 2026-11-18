"use client";

import { useEffect, useId, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { ArrowUpRight } from "lucide-react";
import { strings } from "@/lib/i18n";
import { TELEGRAM_CHANNELS } from "@/lib/site";
import type { Locale } from "@/lib/types";
import { SiteNav } from "./SiteNav";

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Below `lg` the section links fold behind a hamburger at the far right of
 * the header. Open, the three lines turn into an X in the same place and a
 * sheet drops from under the header: the sections first, then a separate
 * follow group (Telegram, RSS). The sheet is as tall as its content; the
 * page behind is dimmed, and tapping it closes the menu.
 *
 * Body scroll is locked while open. Escape, a link, the X or the dimmed page
 * closes it, and focus returns to the button. Tab cycles within the header
 * (wordmark, language, button, menu links) while the menu is open.
 */
export function MobileMenu({ lang }: { lang: Locale }) {
  const s = strings(lang);
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const panelId = useId();
  const followId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.querySelector<HTMLElement>("a, button")?.focus();

    const close = (refocus: boolean) => {
      setOpen(false);
      if (refocus) button.current?.focus();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close(true);
        return;
      }
      if (e.key !== "Tab") return;
      const scope = button.current?.closest("header");
      if (!scope) return;
      const items = Array.from(scope.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      );
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && (active === first || !scope.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !scope.contains(active))) {
        e.preventDefault();
        first.focus();
      }
    };
    // Widening past the breakpoint hides the menu; release the scroll lock.
    const wide = window.matchMedia("(min-width: 1024px)");
    const onWide = () => wide.matches && close(false);
    window.addEventListener("keydown", onKey);
    wide.addEventListener("change", onWide);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
      wide.removeEventListener("change", onWide);
    };
  }, [open]);

  const bar = "absolute left-1/2 h-[2px] w-[22px] -translate-x-1/2 rounded-sm bg-current transition-transform duration-200 ease-out motion-reduce:transition-none";
  const follow =
    "inline-flex min-h-[44px] items-center gap-1.5 font-sans text-[1rem] font-semibold text-ink-muted " +
    "transition-colors duration-150 hover:text-ink";

  return (
    <div className="lg:hidden">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={open ? s.nav_menu_close : s.nav_menu_open}
        data-testid="menu-button"
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
        hidden={!open}
        className="fixed inset-x-0 bottom-0 top-[calc(4rem+env(safe-area-inset-top))] z-30"
      >
        {/* The dimmed page: a pointer target only (keyboard users have
            Escape and the X), so it stays out of the tab order. */}
        <div aria-hidden="true" className="absolute inset-0 bg-ground-sunk/75" onClick={() => setOpen(false)} />
        <div
          ref={panel}
          className="relative max-h-full overflow-y-auto overscroll-contain bg-ground-raised"
          onClick={(e) => {
            // Also close for the link to the current page (no route change).
            if ((e.target as HTMLElement).closest("a")) setOpen(false);
          }}
        >
          <nav aria-label={s.nav_label} data-testid="menu-primary" className="page pt-3 pb-4">
            <SiteNav
              lang={lang}
              labels="name"
              className="flex flex-col"
              itemClassName="flex w-full min-h-[52px] text-[1.1875rem] leading-tight"
            />
          </nav>
          <div
            role="group"
            aria-labelledby={followId}
            data-testid="menu-secondary"
            className="page border-t border-line pt-4 pb-[calc(1.25rem+env(safe-area-inset-bottom))]"
          >
            <p id={followId} className="font-sans text-small text-ink-faint">
              {s.footer_follow}
            </p>
            <ul className="flex flex-wrap gap-x-7">
              <li>
                <a href={TELEGRAM_CHANNELS[lang]} target="_blank" rel="noopener noreferrer" className={follow}>
                  {s.subscribe_telegram}
                  <ArrowUpRight className="h-4 w-4" aria-hidden />
                </a>
              </li>
              <li>
                <a href={`/${lang}/feed.xml`} className={follow}>
                  {s.subscribe_rss}
                </a>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
