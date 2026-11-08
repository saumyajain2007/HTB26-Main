import "@fontsource-variable/instrument-sans/wdth.css";
import "@fontsource-variable/source-serif-4/opsz.css";
import "./styles/tokens.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { Auth0Provider } from "@auth0/auth0-react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { createQueryClient } from "./app/queryClient";
import { routes } from "./app/routes";
import { auth0Config, safeReturnTo } from "./auth/config";

const container = document.getElementById("root");
if (container === null) throw new Error("index.html is missing #root");

const router = createBrowserRouter(routes);
const queryClient = createQueryClient();

createRoot(container).render(
  <StrictMode>
    <Auth0Provider
      domain={auth0Config.domain}
      clientId={auth0Config.clientId}
      authorizationParams={{ redirect_uri: window.location.origin }}
      onRedirectCallback={(appState) => {
        void router.navigate(safeReturnTo(appState?.returnTo), { replace: true });
      }}
    >
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </Auth0Provider>
  </StrictMode>,
);
