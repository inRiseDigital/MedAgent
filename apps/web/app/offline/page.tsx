/* Offline fallback shown by the service worker when a navigation can't reach the
 * network. Deliberately self-contained and calm. */
export default function OfflinePage() {
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col items-center justify-center gap-3 px-6 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary text-2xl">📶</div>
      <h1 className="text-xl font-bold tracking-tight">You're offline</h1>
      <p className="text-sm text-muted-foreground">
        MedAgent needs a connection to load your latest health information. Please reconnect and try again — your data is safe.
      </p>
    </div>
  );
}
