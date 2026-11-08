/** Public SPA settings. Never put a client secret in a Vite environment variable. */
export const auth0Config = {
  domain: import.meta.env.VITE_AUTH0_DOMAIN ?? "dev-kt7rl83e2qb1qb6t.us.auth0.com",
  clientId: import.meta.env.VITE_AUTH0_CLIENT_ID ?? "IQjKLlPrAbcbA6emWspXyMXArwBFFPmM",
};

/** Only return to a local app route, never an external URL or the login page itself. */
export function safeReturnTo(value: unknown): string {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    Array.from(value).some((character) => character.charCodeAt(0) <= 32)
  ) {
    return "/account";
  }
  const base = "https://app.invalid";
  const url = new URL(value, base);
  try {
    if (
      url.origin !== base ||
      decodeURIComponent(url.pathname).toLowerCase().replace(/\/+$/u, "") === "/login"
    ) {
      return "/account";
    }
  } catch {
    return "/account";
  }
  return `${url.pathname}${url.search}${url.hash}`;
}
