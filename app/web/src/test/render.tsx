import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { createQueryClient } from "../app/queryClient";
import { routes } from "../app/routes";

/**
 * Renders the whole app at `path`, with a fresh cache and no retries, so failures show at once.
 * `appRoutes` renders a different set of addresses than the app's own, which is how a test
 * reaches a flow the build-time flags leave out (`createRoutes` in `src/app/routes.tsx`).
 */
export function renderApp(path: string, appRoutes: RouteObject[] = routes) {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({
    queries: { ...queryClient.getDefaultOptions().queries, retry: false },
  });
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router, queryClient };
}
