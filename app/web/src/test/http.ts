import { createOpenApiHttp } from "openapi-msw";
import type { paths } from "../api/schema";

/**
 * MSW handlers typed by the generated contract: a wrong path or body fails `tsc`. One instance,
 * shared by `server.ts` and `resistance.ts`, so neither has to import the other.
 */
export const http = createOpenApiHttp<paths>({ baseUrl: window.location.origin });
