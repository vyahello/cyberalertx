"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { strings } from "@/lib/i18n";
import type { FilterState, Locale } from "@/lib/types";
import { FilterPanel, type FilterOptions } from "./FilterPanel";

interface Props {
  open: boolean;
  onClose: () => void;
  state: FilterState;
  onChange: (next: FilterState) => void;
  lang: Locale;
  options: FilterOptions;
  resultCount: number;
}

/**
 * Filters on phones and tablets: a bottom sheet built on the native
 * <dialog>. showModal() gives real modal behaviour for free — focus moves
 * inside, the page behind becomes inert, Escape closes it, and focus returns
 * to the button that opened it.
 */
export function FilterSheet({
  open,
  onClose,
  state,
  onChange,
  lang,
  options,
  resultCount,
}: Props) {
  const s = strings(lang);
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby="filter-sheet-title"
      onClose={onClose}
      onClick={(e) => {
        // A click on the backdrop lands on the <dialog> itself.
        if (e.target === e.currentTarget) onClose();
      }}
      className="lg:hidden m-0 mt-auto w-full max-w-none max-h-[88dvh] p-0
                 bg-ground-raised text-ink open:animate-sheet-in
                 backdrop:bg-ground-sunk/80"
    >
      <div className="sticky top-0 z-10 flex items-center justify-between bg-ground-raised px-5 pt-4 pb-3">
        <h2 id="filter-sheet-title" className="font-sans text-lead font-semibold">
          {s.filters_title}
        </h2>
        <button
          type="button"
          onClick={onClose}
          className="inline-flex h-11 w-11 items-center justify-center -mr-2 text-ink-muted hover:text-ink hover:bg-ground-high"
          aria-label={s.menu_close}
        >
          <X className="h-5 w-5" aria-hidden />
        </button>
      </div>
      <div className="px-5 pb-6">
        <FilterPanel
          state={state}
          onChange={onChange}
          lang={lang}
          options={options}
          withSearch={false}
        />
      </div>
      <div className="sticky bottom-0 bg-ground-raised px-5 pt-3 pb-[max(1rem,env(safe-area-inset-bottom))]">
        <button type="button" onClick={onClose} className="btn-primary w-full">
          {s.filters_apply(resultCount)}
        </button>
      </div>
    </dialog>
  );
}
