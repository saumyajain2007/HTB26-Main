import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/errors";

/** Ask again once when the API was unreachable or failed; a 4xx answer won't change by asking. */
function retryOnce(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && !error.unreachable) return false;
  return failureCount < 1;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Experiments change only through the user's own actions; polling is opted into per query.
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: retryOnce,
      },
    },
  });
}
