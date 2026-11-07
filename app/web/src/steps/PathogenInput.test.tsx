import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { RESISTANCE_PATH } from "../app/steps";
import { copy } from "../copy/en";
import { renderApp } from "../test/render";
import {
  PRESET_WITHOUT_PROFILE,
  PRESET_WITH_PROFILE,
  PROFILE_ID,
  pathogenPresets,
  resistanceProfile,
} from "../test/resistance";
import { http, networkError, server } from "../test/server";

const PATHOGEN = copy.resistance.pathogen;
const SPECIES = "Staphylococcus aureus";

/** One of the API's own presets, so the test never writes a label or a note of its own. */
function preset(id: string) {
  const found = pathogenPresets().find((item) => item.id === id);
  if (found === undefined) throw new Error(`No fixture preset "${id}"`);
  return found;
}

describe("the pathogen input", () => {
  it("opens the profile of the pathogen that has one", async () => {
    const user = userEvent.setup();
    const { router } = renderApp(RESISTANCE_PATH);
    const mrsa = preset(PRESET_WITH_PROFILE);

    const button = await screen.findByRole("button", { name: mrsa.label });
    expect(button).toHaveAccessibleDescription(mrsa.note ?? "");
    await user.click(button);

    expect(router.state.location.pathname).toBe(`${RESISTANCE_PATH}/${PROFILE_ID}/map`);
  });

  it("offers a pathogen with no profile in the API's own words, and opens nothing", async () => {
    const user = userEvent.setup();
    const { router } = renderApp(RESISTANCE_PATH);
    const esbl = preset(PRESET_WITHOUT_PROFILE);

    const button = await screen.findByRole("button", { name: esbl.label });
    expect(button).toHaveAccessibleDescription(esbl.note ?? "");
    expect(button).toHaveAttribute("aria-disabled", "true");
    // Reachable by keyboard, so the reason is readable: kept out of use, not taken away.
    expect(button).not.toBeDisabled();

    await user.click(button);
    expect(router.state.location.pathname).toBe(RESISTANCE_PATH);
  });

  it("splits and tidies a typed list of genes, and says nothing is sent yet", async () => {
    const user = userEvent.setup();
    renderApp(RESISTANCE_PATH);

    const field = screen.getByLabelText(PATHOGEN.genesLabel);
    expect(field).toHaveAccessibleDescription(`${PATHOGEN.genesHint} ${PATHOGEN.genesBlocked}`);

    await user.type(field, "mecA, mecA{enter}  gyrA  S84L ,");

    expect(screen.getByText(PATHOGEN.genesRead(2))).toBeInTheDocument();
    expect(screen.getByText("mecA")).toBeInTheDocument();
    expect(screen.getByText("gyrA S84L")).toBeInTheDocument();
    expect(screen.getByText(PATHOGEN.genesRepeated(["mecA"]))).toBeInTheDocument();
    // Nothing can profile the list yet, so nothing offers to, and the screen says why.
    expect(screen.getByText(PATHOGEN.genesBlocked)).toBeInTheDocument();
  });

  it("names the profile on screen and the names it could not resolve", async () => {
    renderApp(`${RESISTANCE_PATH}/${PROFILE_ID}/pathogen`);
    const fixture = resistanceProfile();
    const unresolved = fixture.unresolved_inputs[0];

    expect(await screen.findByText(SPECIES)).toBeInTheDocument();
    expect(
      screen.getByText(
        PATHOGEN.profileResolved(fixture.genes.length, fixture.input.requested.length),
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(PATHOGEN.profileUnresolved)).toBeInTheDocument();
    expect(screen.getByText(unresolved?.text ?? "")).toBeInTheDocument();
    expect(screen.getByText(unresolved?.reason ?? "")).toBeInTheDocument();

    const mrsa = preset(PRESET_WITH_PROFILE);
    expect(await screen.findByRole("button", { name: mrsa.label })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("says when the pathogens couldn't be loaded, and asks again", async () => {
    server.use(http.untyped.get("*/api/resistance/pathogens", networkError));
    const user = userEvent.setup();
    renderApp(RESISTANCE_PATH);

    expect(await screen.findByText(PATHOGEN.presetsUnavailable)).toBeInTheDocument();
    const mrsa = preset(PRESET_WITH_PROFILE);
    expect(screen.queryByRole("button", { name: mrsa.label })).not.toBeInTheDocument();

    server.resetHandlers();
    await user.click(screen.getByRole("button", { name: copy.retry }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: mrsa.label })).toBeInTheDocument();
    });
    expect(screen.queryByText(PATHOGEN.presetsUnavailable)).not.toBeInTheDocument();
  });
});
