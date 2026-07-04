/**
 * Threat-detail route-level loading state.
 *
 * Feed cards use `prefetch={false}` (deliberate — the feed can hold 20
 * links and speculative RSC fetches would hammer the backend), so every
 * card tap pays a real server round-trip. This skeleton is what makes
 * that trip feel instant: badge row, title, snapshot card, and paragraph
 * silhouette paint immediately under the persistent header.
 */
export default function ThreatDetailLoading() {
  return (
    <div
      role="status"
      aria-busy="true"
      className="mx-auto max-w-6xl px-5 sm:px-8 py-8 sm:py-12 animate-fade-up"
    >
      <span className="sr-only">Loading…</span>

      {/* Back link */}
      <div className="skeleton h-4 w-32 mb-8" />

      {/* Badge row + title + source line */}
      <div className="flex flex-wrap gap-2 mb-5">
        <div className="skeleton h-8 w-8 rounded-lg" />
        <div className="skeleton h-6 w-24 rounded-md" />
        <div className="skeleton h-6 w-32 rounded-md" />
      </div>
      <div className="skeleton h-8 sm:h-10 w-full max-w-3xl mb-3" />
      <div className="skeleton h-8 sm:h-10 w-2/3 max-w-xl mb-5" />
      <div className="skeleton h-5 w-44 mb-10" />

      {/* Threat snapshot card */}
      <div className="skeleton h-36 w-full rounded-xl mb-10" />

      {/* Narrative + sticky sidebar silhouette */}
      <div className="grid gap-10 lg:gap-12 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4">
          <div className="skeleton h-4 w-40" />
          <div className="skeleton h-5 w-full max-w-2xl" />
          <div className="skeleton h-5 w-full max-w-2xl" />
          <div className="skeleton h-5 w-3/4 max-w-xl" />
          <div className="skeleton h-4 w-40 !mt-8" />
          <div className="skeleton h-5 w-full max-w-2xl" />
          <div className="skeleton h-5 w-5/6 max-w-2xl" />
        </div>
        <div className="hidden lg:block">
          <div className="skeleton h-64 w-full rounded-lg" />
        </div>
      </div>
    </div>
  );
}
