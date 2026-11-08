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

  it("splits and tidies a typed list of genes", async () => {
    const user = userEvent.setup();
    renderApp(RESISTANCE_PATH);

    const field = screen.getByLabelText(PATHOGEN.genesLabel);
    expect(field).toHaveAccessibleDescription(PATHOGEN.genesHint);
    // Nothing to profile yet, so the one action is out of use rather than hidden.
    expect(screen.getByRole("button", { name: PATHOGEN.genesSubmit })).toBeDisabled();

    await user.type(field, "mecA, mecA{enter}  gyrA  S84L ,");

    expect(screen.getByText(PATHOGEN.genesRead(2))).toBeInTheDocument();
    // Each name shows twice: once as an example chip, once in the list that was read (and the
    // repeated mecA is read once, not twice).
    expect(screen.getAllByText("mecA")).toHaveLength(2);
    expect(screen.getAllByText("gyrA S84L")).toHaveLength(2);
    expect(screen.getByText(PATHOGEN.genesRepeated(["mecA"]))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: PATHOGEN.genesSubmit })).toBeEnabled();
  });

  it("adds an example chip to the field on its own line, and never decides it is known", async () => {
    const user = userEvent.setup();
    renderApp(RESISTANCE_PATH);
    const field = screen.getByLabelText(PATHOGEN.genesLabel);

    await user.click(screen.getByRole("button", { name: "mecA" }));
    expect(field).toHaveValue("mecA");

    await user.click(screen.getByRole("button", { name: "gyrA S84L" }));
    expect(field).toHaveValue("mecA\ngyrA S84L");
    // The chip only types for the reader: the profile still has to be built, and CARD still judges.
    expect(screen.getByRole("button", { name: PATHOGEN.genesSubmit })).toBeEnabled();
  });

  it("profiles a typed list and opens the profile it built", async () => {
    const user = userEvent.setup();
    const posted: unknown[] = [];
    server.use(
      http.post("/api/resistance/profiles", async ({ request, response }) => {
        posted.push(await request.json());
        return response(201).json(resistanceProfile());
      }),
    );
    const { router } = renderApp(RESISTANCE_PATH);

    await user.type(screen.getByLabelText(PATHOGEN.genesLabel), "mecA, gyrA S84L");
    await user.click(screen.getByRole("button", { name: PATHOGEN.genesSubmit }));

    // The tidied list is what is sent, and the profile it returns is the one opened.
    await waitFor(() => {
      expect(router.state.location.pathname).toBe(`${RESISTANCE_PATH}/${PROFILE_ID}/map`);
    });
    expect(posted).toEqual([{ kind: "gene_list", genes: "mecA, gyrA S84L" }]);
  });

  it("says the server cannot look names up, rather than blaming the names", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/resistance/profiles", ({ response }) =>
        response(503).json({ detail: "No usable CARD release under data." }),
      ),
    );
    renderApp(RESISTANCE_PATH);

    await user.type(screen.getByLabelText(PATHOGEN.genesLabel), "mecA");
    await user.click(screen.getByRole("button", { name: PATHOGEN.genesSubmit }));

    // A 503 means nothing was looked up: never "that name is unknown".
    expect(await screen.findByText(PATHOGEN.genesUnavailable)).toBeInTheDocument();
  });

  it("passes on the server's reason when the input is refused", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/resistance/profiles", ({ response }) =>
        response(422).json({ detail: "no preset for Escherichia coli" }),
      ),
    );
    renderApp(RESISTANCE_PATH);

    await user.type(screen.getByLabelText(PATHOGEN.genesLabel), "mecA");
    await user.click(screen.getByRole("button", { name: PATHOGEN.genesSubmit }));

    expect(
      await screen.findByText(PATHOGEN.genesRefused("no preset for Escherichia coli")),
    ).toBeInTheDocument();
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
