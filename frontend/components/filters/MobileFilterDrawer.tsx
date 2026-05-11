"use client";

import { useEffect } from "react";
import { SlidersHorizontal, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { strings } from "@/lib/i18n";
import type {
  Audience,
  Category,
  FilterState,
  Locale,
} from "@/lib/types";
import { FilterPanel, countActiveFilters } from "./FilterPanel";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  state: FilterState;
  onChange: (next: FilterState) => void;
  onReset: () => void;
  lang: Locale;
  availableCategories: Category[];
  availablePlatforms: string[];
  availableAudiences: Audience[];
}

/**
 * Mobile filter UI.
 *
 *   - **Floating trigger button** sits bottom-right with a thumb-reachable
 *     offset. Visible only below the lg breakpoint where the sidebar
 *     disappears.
 *   - **Bottom sheet** (drawer rising from the bottom edge, not from the
 *     side) — feels native on iOS and Android, matches the user's mental
 *     model of a "filter tray", and avoids the visual jolt of side-slide.
 *   - **Body scroll lock** while the drawer is open — without this, the
 *     feed scrolls under the user's finger when they reach the drawer edge.
 *
 * Closing behaviors:
 *   - Tap the backdrop  → close
 *   - Tap the X button  → close
 *   - Press Escape      → close
 */
export function MobileFilterDrawer({
  open,
  onOpenChange,
  state,
  onChange,
  onReset,
  lang,
  availableCategories,
  availablePlatforms,
  availableAudiences,
}: Props) {
  const s = strings(lang);
  const activeCount = countActiveFilters(state);

  // ESC-to-close + body scroll lock — kept in one effect so they stay
  // mounted/unmounted together with the open state.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onOpenChange]);

  return (
    <>
      {/* Trigger — visible only below `lg`. Floats with a small drop shadow
          so it doesn't get lost on dense cards behind it. */}
      <button
        type="button"
        onClick={() => onOpenChange(true)}
        className={cn(
          "lg:hidden fixed bottom-5 right-5 z-30",
          "inline-flex items-center gap-2 px-4 py-3 rounded-full",
          "bg-accent text-white shadow-elevated",
          "hover:bg-[#4A7EE8] active:scale-[0.97] transition",
        )}
        aria-label={s.filters_button}
      >
        <SlidersHorizontal className="w-4 h-4" />
        <span className="text-sm font-medium">{s.filters_button}</span>
        {activeCount > 0 && (
          <span className="bg-white/20 rounded-full px-2 py-0.5 text-2xs font-semibold tabular-nums">
            {activeCount}
          </span>
        )}
      </button>

      {/* Backdrop + sheet — only mounted while open. We don't bother with
          unmount animation; the open animation alone reads as polished. */}
      {open && (
        <div className="lg:hidden fixed inset-0 z-40">
          <button
            type="button"
            aria-label="Close filters"
            onClick={() => onOpenChange(false)}
            className="absolute inset-0 bg-bg-inset/70 backdrop-blur-sm"
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="mobile-filter-title"
            className={cn(
              "absolute bottom-0 left-0 right-0",
              "max-h-[85vh] overflow-y-auto",
              "bg-bg-elevated border-t border-border-subtle",
              "rounded-t-xl shadow-elevated",
              "animate-fade-up",
            )}
            style={{ animationDuration: "0.25s" }}
          >
            {/* Drag handle — purely visual; the dialog opens via the trigger
                and closes via the explicit X / backdrop tap, but the handle
                makes the sheet feel pull-down-dismissible by convention. */}
            <div className="sticky top-0 z-10 bg-bg-elevated pt-3 pb-2 px-5">
              <div className="mx-auto w-10 h-1 rounded-full bg-border-strong mb-3" />
              <div className="flex items-center justify-between">
                <h2
                  id="mobile-filter-title"
                  className="text-base font-semibold text-text-primary"
                >
                  {s.filters_title}
                </h2>
                <button
                  type="button"
                  onClick={() => onOpenChange(false)}
                  className="p-1.5 -mr-1.5 rounded-md text-text-secondary hover:text-text-primary hover:bg-bg-elevated-2"
                  aria-label="Close"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>
            <div className="px-5 pb-5">
              <FilterPanel
                state={state}
                onChange={onChange}
                onReset={onReset}
                lang={lang}
                availableCategories={availableCategories}
                availablePlatforms={availablePlatforms}
                availableAudiences={availableAudiences}
              />
            </div>
            {/* Sticky bottom action — fixes a common bottom-sheet bug where
                the user scrolls and loses the "done" button. */}
            <div className="sticky bottom-0 bg-bg-elevated border-t border-border-subtle px-5 py-3">
              <button
                type="button"
                onClick={() => onOpenChange(false)}
                className="btn-primary w-full"
              >
                {s.filters_apply}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
