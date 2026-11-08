import { Auth0Context, initialContext, type Auth0ContextInterface } from "@auth0/auth0-react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { PageFrame } from "../app/PageFrame";
import { copy } from "../copy/en";
import { AccountPage } from "./AccountPage";
import { LoginPage } from "./LoginPage";
import { safeReturnTo } from "./config";

function renderAuth(path = "/login", state: Partial<Auth0ContextInterface> = {}) {
  const loginWithRedirect = vi
    .fn<Auth0ContextInterface["loginWithRedirect"]>()
    .mockResolvedValue(undefined);
  const logout = vi.fn<Auth0ContextInterface["logout"]>().mockResolvedValue(undefined);
  const context = { ...initialContext, isLoading: false, loginWithRedirect, logout, ...state };
  const router = createMemoryRouter(
    [
      { path: "/login", element: <LoginPage /> },
      { path: "/account", element: <AccountPage /> },
      {
        path: "/resistance",
        element: (
          <PageFrame>
            <p>Research</p>
          </PageFrame>
        ),
      },
      { path: "/", element: <p>Home</p> },
    ],
    { initialEntries: [path] },
  );
  render(
    <Auth0Context.Provider value={context}>
      <RouterProvider router={router} />
    </Auth0Context.Provider>,
  );
  return { loginWithRedirect, logout, router };
}

describe("Auth0 login", () => {
  it("uses the SDK with the requested local return address", async () => {
    const { loginWithRedirect } = renderAuth(
      "/login?returnTo=%2Fresistance%3Fview%3Dmap%23evidence",
    );
    await userEvent.click(screen.getByRole("button", { name: copy.auth.signIn }));
    expect(loginWithRedirect).toHaveBeenCalledWith({
      appState: { returnTo: "/resistance?view=map#evidence" },
    });
    expect(screen.getByRole("button", { name: copy.auth.redirecting })).toBeDisabled();
  });

  it("requests Universal Login sign-up without collecting a password locally", async () => {
    const { loginWithRedirect } = renderAuth();
    await userEvent.click(screen.getByRole("button", { name: copy.auth.signUp }));
    expect(loginWithRedirect).toHaveBeenCalledWith({
      appState: { returnTo: "/account" },
      authorizationParams: { screen_hint: "signup" },
    });
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
  });

  it("disables authentication controls while the SDK checks the session", () => {
    renderAuth("/login", { isLoading: true });
    expect(screen.getByRole("status")).toHaveTextContent(copy.auth.loading);
    expect(screen.getByRole("button", { name: copy.auth.signIn })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.auth.signUp })).toBeDisabled();
  });

  it("allows retry after a rejected redirect without exposing provider error details", async () => {
    const failure = vi
      .fn<Auth0ContextInterface["loginWithRedirect"]>()
      .mockRejectedValue(new Error("internal detail"));
    renderAuth("/login", { loginWithRedirect: failure });
    await userEvent.click(screen.getByRole("button", { name: copy.auth.signIn }));
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.auth.loginError);
    expect(screen.getByRole("button", { name: copy.auth.signIn })).toBeEnabled();
    expect(screen.queryByText("internal detail")).not.toBeInTheDocument();
  });

  it("shows an SDK callback error with a way to retry or leave", () => {
    renderAuth("/login", { error: new Error("access_denied") });
    expect(screen.getByRole("alert")).toHaveTextContent(copy.auth.loginError);
    expect(screen.getByRole("link", { name: copy.auth.guest })).toHaveAttribute(
      "href",
      "/resistance",
    );
  });

  it("returns signed-in users to their local destination", async () => {
    const { router } = renderAuth("/login?returnTo=%2Fresistance", { isAuthenticated: true });
    expect(await screen.findByText("Research")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/resistance");
  });

  it("offers login in the header and remembers the current location", () => {
    renderAuth("/resistance?view=map#evidence");
    expect(screen.getByRole("link", { name: copy.auth.signIn })).toHaveAttribute(
      "href",
      "/login?returnTo=%2Fresistance%3Fview%3Dmap%23evidence",
    );
  });

  it("offers the account link after authentication", () => {
    renderAuth("/resistance", { isAuthenticated: true });
    expect(screen.getByRole("link", { name: copy.auth.account })).toHaveAttribute(
      "href",
      "/account",
    );
  });
});

describe("account", () => {
  it("redirects guests to login", async () => {
    const { router } = renderAuth("/account");
    expect(await screen.findByRole("button", { name: copy.auth.signIn })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/login");
  });

  it("shows profile information and signs out using the SDK", async () => {
    const { logout } = renderAuth("/account", {
      isAuthenticated: true,
      user: { name: "Alex Researcher", email: "alex@example.com", email_verified: true },
    });
    expect(screen.getByText("Alex Researcher")).toBeInTheDocument();
    expect(screen.getByText("alex@example.com")).toBeInTheDocument();
    expect(screen.getByText(copy.auth.verified)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: copy.auth.signOut }));
    expect(logout).toHaveBeenCalledWith({ logoutParams: { returnTo: window.location.origin } });
  });

  it("keeps sign-out retryable when the SDK rejects", async () => {
    renderAuth("/account", {
      isAuthenticated: true,
      logout: vi.fn<Auth0ContextInterface["logout"]>().mockRejectedValue(new Error("offline")),
    });
    await userEvent.click(screen.getByRole("button", { name: copy.auth.signOut }));
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.auth.logoutError);
    expect(screen.getByRole("button", { name: copy.auth.signOut })).toBeEnabled();
  });
});

describe("safe return locations", () => {
  it.each([
    undefined,
    null,
    {},
    "https://evil.example",
    "//evil.example",
    "///",
    "/\\evil.example",
    "/login",
    "/login/",
    "/LOGIN?returnTo=/login",
    "/%6cogin",
    "/x/../login",
    "/bad\npath",
    "/bad\u0000path",
    "/%xx",
  ])("rejects %j", (value) => {
    expect(safeReturnTo(value)).toBe("/account");
  });
  it("preserves a local path, query and fragment", () => {
    expect(safeReturnTo("/resistance/profile/map?view=genes#details")).toBe(
      "/resistance/profile/map?view=genes#details",
    );
  });
});
