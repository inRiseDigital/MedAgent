"use client";

/*
 * Client-side providers — S1 scaffold.
 * TanStack Query is the single mechanism for server data (06 §5, ADR W-4):
 * no server data in component state or global stores; SSE events
 * invalidate/patch these caches from S2 on. Zustand slices (≤ ~50 lines,
 * per-concern) are added beside the features that need them — no
 * monolithic store.
 */
import { useState, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Clinical data is never cache-first-stale for long (07 §12.1).
            staleTime: 15_000,
            retry: 1,
          },
        },
      }),
  );

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
