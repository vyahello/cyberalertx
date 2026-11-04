/** Article skeleton: marks column left of the axis, title and text on it. */
export default function Loading() {
  return (
    <main aria-busy="true" aria-live="polite" className="page pt-6 sm:pt-10">
      <span className="sr-only">Loading…</span>
      <div className="axis">
        <div className="on-axis skeleton h-4 w-48" />
      </div>
      <div className="axis mt-5 gap-y-8">
        <div className="lg:col-start-2 space-y-4">
          <div className="skeleton h-10 w-full" />
          <div className="skeleton h-10 w-3/4" />
          <div className="skeleton h-16 w-full max-w-measure" />
        </div>
        <div className="lg:col-start-1 lg:row-start-1 lg:row-span-2 space-y-4 lg:max-w-[18rem] lg:justify-self-end lg:w-full">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="skeleton h-9 w-full" />
          ))}
        </div>
        <div className="lg:col-start-2 space-y-3 max-w-measure">
          <div className="skeleton h-7 w-48" />
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton h-4 w-full" />
          ))}
        </div>
      </div>
    </main>
  );
}
