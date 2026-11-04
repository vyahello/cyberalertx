/**
 * Front-page skeleton: same frame as the real page (masthead left of the
 * axis, lead story on it, then rows), so nothing jumps when data lands.
 */
export default function Loading() {
  return (
    <main aria-busy="true" aria-live="polite" className="page pt-8 sm:pt-12 lg:pt-16">
      <span className="sr-only">Loading…</span>
      <div className="axis gap-y-10">
        <div className="space-y-5">
          <div className="skeleton h-16 w-3/4" />
          <div className="skeleton h-4 w-40" />
          <div className="skeleton h-20 w-full max-w-[34ch]" />
        </div>
        <div className="on-axis space-y-4">
          <div className="skeleton h-4 w-64" />
          <div className="skeleton h-10 w-full" />
          <div className="skeleton h-10 w-4/5" />
          <div className="skeleton h-16 w-full max-w-measure" />
          <div className="skeleton h-11 w-40" />
        </div>
      </div>
      <div className="axis mt-24 gap-y-3">
        <div className="skeleton h-8 w-56" />
        <div className="on-axis space-y-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="skeleton h-7 w-full" />
          ))}
        </div>
      </div>
    </main>
  );
}
