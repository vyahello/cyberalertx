/**
 * Homepage route-level loading state.
 *
 * Renders instantly under the persistent header (which lives in the
 * layout) while the server fetches the feed. The skeleton mirrors the
 * real page's silhouette — hero band, trending row, filter+feed split —
 * so the content swap lands in place instead of reflowing the viewport.
 *
 * Purely visual: no i18n (loading.tsx receives no params), one sr-only
 * label for assistive tech.
 */
export default function HomeLoading() {
  return (
    <div role="status" aria-busy="true" className="animate-fade-up">
      <span className="sr-only">Loading…</span>

      {/* Hero band */}
      <div className="border-b border-border-subtle">
        <div className="mx-auto max-w-6xl px-5 sm:px-8 py-16 sm:py-24 lg:py-32">
          <div className="skeleton h-3 w-56 mb-6" />
          <div className="skeleton h-10 sm:h-12 w-full max-w-2xl mb-3" />
          <div className="skeleton h-10 sm:h-12 w-3/4 max-w-xl mb-6" />
          <div className="skeleton h-5 w-full max-w-lg mb-8" />
          <div className="skeleton h-11 w-44 rounded-md" />
        </div>
      </div>

      {/* Trending row */}
      <div className="mx-auto max-w-6xl px-5 sm:px-8 py-10 sm:py-12">
        <div className="skeleton h-6 w-44 mb-2" />
        <div className="skeleton h-4 w-72 mb-6" />
        <div className="flex gap-3 overflow-hidden">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="skeleton h-44 w-[300px] sm:w-[340px] flex-shrink-0 rounded-lg"
            />
          ))}
        </div>
      </div>

      {/* Feed split — sidebar only from lg, matching HomeShell's grid */}
      <div className="mx-auto max-w-6xl px-5 sm:px-8 pb-24">
        <div className="skeleton h-6 w-40 mb-8" />
        <div className="grid gap-8 lg:gap-10 lg:grid-cols-[260px_minmax(0,1fr)]">
          <div className="hidden lg:block space-y-4">
            <div className="skeleton h-9 w-full" />
            <div className="skeleton h-24 w-full" />
            <div className="skeleton h-24 w-full" />
          </div>
          <div className="space-y-4">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton h-48 w-full rounded-lg" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
