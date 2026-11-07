import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { copy } from "../../copy/en";
import { renderApp } from "../../test/render";
import { PROFILE_ID, UNKNOWN_PROFILE_ID } from "../../test/resistance";
import { http, networkError, server } from "../../test/server";
import { RESISTANCE_PATH } from "../steps";

const PATHOGEN = copy.resistanceSteps[0];
const MAP = copy.resistanceSteps[1];
const SPECIES = "Staphylococcus aureus";

/** The step the navigation marks as current, and nothing else marked with it. */
function expectOnStep(title: string) {
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(title);
  const nav = screen.getByRole("navigation", { name: copy.stepsLabel });
  const current = within(nav).getAllByRole("link", { current: "step" });
  expect(current).toHaveLength(1);
  expect(current[0]).toHaveAccessibleName(title);
}

describe("the resistance flow", () => {
  it("opens on the pathogen input, with the later step not yet reachable", () => {
    renderApp(RESISTANCE_PATH);

    expectOnStep(PATHOGEN.title);
    expect(screen.getAllByText(PATHOGEN.intro)).toHaveLength(1);
    expect(screen.getByLabelText(copy.resistance.pathogen.genesLabel)).toBeInTheDocument();

    const nav = screen.getByRole("navigation", { name: copy.stepsLabel });
    expect(within(nav).getAllByRole("link")).toHaveLength(1);
    expect(within(nav).getByText(MAP.title)).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("button", { name: copy.back })).toBeDisabled();
    expect(screen.getByRole("button", { name: copy.next })).toBeDisabled();
  });

  it("shows the profile's pathogen once in the header on the map step", async () => {
    renderApp(`${RESISTANCE_PATH}/${PROFILE_ID}/map`);

    await waitFor(() => {
      expect(screen.queryByText(copy.resistance.loading)).not.toBeInTheDocument();
    });
    expectOnStep(MAP.title);
    expect(screen.getByRole("table", { name: copy.resistance.map.caption })).toBeInTheDocument();
    expect(screen.getAllByText(SPECIES)).toHaveLength(1);
    expect(within(screen.getByRole("banner")).getByText(SPECIES)).toBeInTheDocument();
  });

  it("does not repeat the pathogen in the header on the step that chooses it", async () => {
    renderApp(`${RESISTANCE_PATH}/${PROFILE_ID}/pathogen`);

    // The step that chooses the pathogen names it itself, so the header leaves it out.
    expect(await screen.findByText(SPECIES)).toBeInTheDocument();
    expectOnStep(PATHOGEN.title);
    expect(screen.getAllByText(SPECIES)).toHaveLength(1);
    expect(within(screen.getByRole("banner")).queryByText(SPECIES)).not.toBeInTheDocument();
  });

  it("moves between the steps with Back and Next once a profile is open", async () => {
    const user = userEvent.setup();
    const { router } = renderApp(`${RESISTANCE_PATH}/${PROFILE_ID}/pathogen`);

    await user.click(screen.getByRole("button", { name: copy.next }));
    expectOnStep(MAP.title);
    expect(router.state.location.pathname).toBe(`${RESISTANCE_PATH}/${PROFILE_ID}/map`);

    await user.click(screen.getByRole("button", { name: copy.back }));
    expectOnStep(PATHOGEN.title);
    expect(screen.getByRole("button", { name: copy.back })).toBeDisabled();
  });

  it("says plainly when there is no profile at this address", async () => {
    renderApp(`${RESISTANCE_PATH}/${UNKNOWN_PROFILE_ID}/map`);

    expect(
      await screen.findByRole("heading", { level: 1, name: copy.resistance.notFound.title }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.resistance.notFound.home })).toHaveAttribute(
      "href",
      RESISTANCE_PATH,
    );
  });

  it("says when the profile couldn't be loaded, and asks again", async () => {
    server.use(http.untyped.get("*/api/resistance/profiles/:id", networkError));
    const user = userEvent.setup();
    renderApp(`${RESISTANCE_PATH}/${PROFILE_ID}/map`);

    expect(await screen.findByText(copy.resistance.unavailable)).toBeInTheDocument();
    expectOnStep(MAP.title);

    server.resetHandlers();
    await user.click(screen.getByRole("button", { name: copy.retry }));
    expect(
      await screen.findByRole("table", { name: copy.resistance.map.caption }),
    ).toBeInTheDocument();
  });

  it("is not found without a step", () => {
    renderApp(`${RESISTANCE_PATH}/${PROFILE_ID}`);

    expect(
      screen.getByRole("heading", { level: 1, name: copy.notFound.title }),
    ).toBeInTheDocument();
  });
});
