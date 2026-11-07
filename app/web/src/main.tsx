import "@fontsource-variable/instrument-sans/wdth.css";
import "@fontsource-variable/source-serif-4/opsz.css";
import "./styles/tokens.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { createQueryClient } from "./app/queryClient";
import { routes } from "./app/routes";

const container = document.getElementById("root");
if (container === null) throw new Error("index.html is missing #root");

const router = createBrowserRouter(routes);
const queryClient = createQueryClient();

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
