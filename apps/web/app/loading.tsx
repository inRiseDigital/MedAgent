/*
 * Root loading state — first-class per 06 §10: skeletons matching the
 * final layout, never spinners-on-white. Route-specific skeletons ship
 * with their screens in S2/S3.
 */
export default function RootLoading() {
  return (
    <div aria-busy="true" className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="h-8 w-48 animate-pulse rounded-md bg-muted" />
      <div className="h-32 animate-pulse rounded-lg bg-muted" />
      <div className="h-32 animate-pulse rounded-lg bg-muted" />
    </div>
  );
}
