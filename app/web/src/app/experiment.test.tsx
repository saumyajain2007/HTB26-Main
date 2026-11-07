import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { copy } from "../copy/en";
import { covidExperiment, EXPERIMENT_ID } from "../test/fixtures";
import { renderApp } from "../test/render";
import { EXPLORE_PATH } from "./steps";
import { fakeApi, http, networkError, server, serveExperiment } from "../test/server";

const E = `/e/${EXPERIMENT_ID}`;

/** The search box once the Experiment has loaded and its Disease name is pre-filled. */
async function loadedSearchbox() {
  await waitFor(() => {
    expect(screen.getByRole("searchbox", { name: copy.search.placeholder })).toHaveValue(
      "COVID-19",
    );
  });
  return screen.getByRole("searchbox", { name: copy.search.placeholder });
}

describe("Choosing a disease", () => {
  it("builds the first common disease on arrival, on step 1, then Next shows its proteins", async () => {
    const created = fakeApi.created;
    const user = userEvent.setup();
    const { router } = renderApp(EXPLORE_PATH);

    // Nothing saved yet: the first common Disease starts building, and step 1 stays on screen
    // with it marked in the list.
    await waitFor(() => {
      expect(router.state.location.pathname).toMatch(/^\/e\/[0-9a-f-]+\/disease$/);
    });
    expect(fakeApi.created).toBe(created + 1);
    expect(screen.getByText(copy.search.common)).toBeInTheDocument();
    // The router has moved on before its screen is drawn, so wait for the mark.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /COVID-19/ })).toHaveAttribute(
        "aria-current",
        "true",
      );
    });
    expect(
      await screen.findByRole("img", { name: copy.network.label }, { timeout: 3000 }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: copy.next }));
    await waitFor(() => {
      expect(router.state.location.pathname).toMatch(/^\/e\/[0-9a-f-]+\/biology$/);
    });
    expect(
      await screen.findByRole("list", { name: copy.biology.targetsLabel }, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(fakeApi.created).toBe(created + 1);
  });

  it("shows the build on step 2 while it runs", async () => {
    // Hold the build until its progress is observed, independently of polling or CPU speed.
    let finished = false;
    server.use(
      http.untyped.get("*/api/experiments/:id", ({ params }) =>
        HttpResponse.json(
          covidExperiment(
            finished ? "ready" : "building",
            finished ? null : "ranking",
            String(params.id),
          ),
        ),
      ),
    );
    const user = userEvent.setup();
    const { router } = renderApp(EXPLORE_PATH);
    await waitFor(() => {
      expect(router.state.location.pathname).toMatch(/^\/e\/[0-9a-f-]+\/disease$/);
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: copy.next })).toBeEnabled();
    });
    await user.click(screen.getByRole("button", { name: copy.next }));

    // Queued, then building (polled each second): the stages in plain words, the current one
    // marked. The queued moment is short-lived; its own test covers it.
    await waitFor(
      () => {
        const stages = screen.getByRole("list", { name: copy.experiment.buildLabel });
        expect(
          within(stages).getByText(copy.experiment.stages.ranking).closest("li"),
        ).toHaveAttribute("aria-current", "step");
        expect(
          within(stages).getByText(copy.experiment.stages.targets).closest("li"),
        ).toHaveAttribute("data-state", "done");
      },
      { timeout: 2500 },
    );
    // The header names the Disease once it is known.
    expect(within(screen.getByRole("banner")).getByText("COVID-19")).toBeInTheDocument();

    // Polling picks up the finished build.
    finished = true;
    expect(
      await screen.findByRole("list", { name: copy.biology.targetsLabel }, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("list", { name: copy.experiment.buildLabel }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("COVID-19")).toHaveLength(1);
  });

  it("searches every disease, with the matched synonym and ID as quiet secondary text", async () => {
    serveExperiment(covidExperiment());
    const user = userEvent.setup();
    renderApp(`${E}/disease`);
    const box = await loadedSearchbox();
    await user.clear(box);
    await user.type(box, "sars");
    // The search results replace the common Diseases; the match is underlined, so its text
    // is split across elements.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /COVID-19/ })).toHaveTextContent("SARS-CoV-2");
    });
    const result = screen.getByRole("button", { name: /COVID-19/ });
    expect(within(result).getByText("MONDO_0100096")).toBeInTheDocument();
    expect(screen.queryByText(copy.search.common)).not.toBeInTheDocument();
  });

  it("says plainly when no disease matches", async () => {
    serveExperiment(covidExperiment());
    const user = userEvent.setup();
    renderApp(`${E}/disease`);
    const box = await loadedSearchbox();
    await user.clear(box);
    await user.type(box, "zzzz");
    expect(await screen.findByText(copy.search.noMatch("zzzz"))).toBeInTheDocument();
  });

  it("offers a retry when the search can't reach the API", async () => {
    server.use(http.untyped.get("*/api/diseases/search", networkError));
    serveExperiment(covidExperiment());
    const user = userEvent.setup();
    renderApp(`${E}/disease`);
    const box = await loadedSearchbox();
    await user.clear(box);
    await user.type(box, "covid");
    expect(await screen.findByText(copy.search.unavailable)).toBeInTheDocument();

    server.resetHandlers();
    await user.click(screen.getByRole("button", { name: copy.retry }));
    expect(await screen.findByRole("button", { name: /COVID-19/ })).toBeInTheDocument();
    expect(screen.queryByText(copy.search.unavailable)).not.toBeInTheDocument();
  });

  it("says so when the Experiment can't be started", async () => {
    server.use(
      http.post("/api/experiments", ({ response }) =>
        response(503).json({ detail: "The ranking service is down." }),
      ),
    );
    const { router } = renderApp(EXPLORE_PATH);
    // The first common Disease couldn't be opened: step 1 stays, saying so, with a retry.
    expect(await screen.findByText(copy.search.createFailed)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.retry })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(EXPLORE_PATH);
  });

  it("swaps in a saved disease in place, with no loading and no new list", async () => {
    const psoriasisId = "5c3e9a10-7d2b-4f6e-8a41-0b9c2d7e6f13";
    const psoriasis = {
      ...covidExperiment("ready", null, psoriasisId),
      disease: { id: "MONDO_0005083", name: "psoriasis" },
      created_at: "2026-10-25T09:00:00Z",
    };
    serveExperiment(covidExperiment());
    serveExperiment(psoriasis);
    let fetched = 0;
    server.use(
      http.get("/api/diseases/common", ({ response }) =>
        response(200).json({
          items: [{ id: covidExperiment().disease.id, name: "COVID-19" }, psoriasis.disease],
        }),
      ),
      // Slow enough that a screen shown before its Experiment arrived would be caught empty.
      http.untyped.get(`*/api/experiments/${psoriasisId}`, async () => {
        fetched += 1;
        await delay(150);
        return HttpResponse.json(psoriasis);
      }),
    );
    const created = fakeApi.created;
    const user = userEvent.setup();
    const { router, queryClient } = renderApp(`${E}/disease`);
    // A prefetched response stays fresh even when the route commits on a later clock tick.
    const systemTime = Date.now;
    let elapsed = 0;
    vi.spyOn(Date, "now").mockImplementation(() => systemTime() + elapsed);
    const unsubscribe = router.subscribe((state) => {
      if (state.location.pathname === `/e/${psoriasisId}/disease`) elapsed = 1000;
    });
    const box = await loadedSearchbox();
    const network = await screen.findByRole("img", { name: copy.network.label });
    const option = screen.getByRole("button", { name: /psoriasis/ });

    await user.click(option);
    // Busy from the click until its screen is drawn.
    expect(option).toHaveAttribute("aria-busy", "true");
    await waitFor(() => {
      expect(option).toHaveAttribute("aria-current", "true");
    });
    await waitFor(() => {
      expect(queryClient.isFetching()).toBe(0);
    });

    // Its screen showed the saved Experiment at once, fetched before it opened: the same search
    // box and list (never remounted, so never emptied), only the mark moved, and its network
    // redrawn in the same plate (never taken away while loading).
    expect(router.state.location.pathname).toBe(`/e/${psoriasisId}/disease`);
    expect(fetched).toBe(1);
    expect(option).not.toHaveAttribute("aria-busy");
    expect(screen.getByRole("button", { name: /COVID-19/ })).not.toHaveAttribute("aria-current");
    expect(box).toBeInTheDocument();
    expect(box).toHaveValue("psoriasis");
    expect(network).toBeInTheDocument();
    expect(fakeApi.created).toBe(created);
    unsubscribe();
  });

  it("marks the current Experiment's disease, and choosing it again changes nothing", async () => {
    serveExperiment(covidExperiment());
    const created = fakeApi.created;
    const user = userEvent.setup();
    const { router } = renderApp(`${E}/disease`);
    const current = await screen.findByRole("button", { name: /COVID-19/ });
    expect(current).toHaveAttribute("aria-current", "true");
    await user.click(current);
    expect(router.state.location.pathname).toBe(`${E}/disease`);
    expect(fakeApi.created).toBe(created);
  });
});

describe("Follow-ups", () => {
  it("start once the reader moves past step 1, not while they choose a disease", async () => {
    serveExperiment(covidExperiment());
    const user = userEvent.setup();
    renderApp(`${E}/disease`);
    await loadedSearchbox();
    expect(fakeApi.followedUp).toEqual([]);

    await user.click(screen.getByRole("button", { name: copy.next }));
    await waitFor(() => {
      expect(fakeApi.followedUp).toEqual([EXPERIMENT_ID]);
    });
    await user.click(screen.getByRole("button", { name: copy.next }));
    await screen.findByRole("heading", { level: 1, name: copy.steps[2].title });
    expect(fakeApi.followedUp).toEqual([EXPERIMENT_ID]);
  });

  it("wait for the build to be ready", async () => {
    serveExperiment(covidExperiment("building", "evidence"));
    renderApp(`${E}/biology`);
    expect(await screen.findByText(copy.experiment.stages.evidence)).toBeInTheDocument();
    expect(fakeApi.followedUp).toEqual([]);
  });
});

describe("An Experiment that isn't ready", () => {
  it("shows the plain error and the way back when the build failed", async () => {
    serveExperiment(covidExperiment("failed"));
    renderApp(`${E}/candidates`);
    expect(await screen.findByText(copy.experiment.failed)).toBeInTheDocument();
    expect(
      screen.getByText("The ranking could not be computed for this disease."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.experiment.chooseAnother })).toHaveAttribute(
      "href",
      EXPLORE_PATH,
    );
  });

  it("shows a retry when the API is down", async () => {
    server.use(http.untyped.get("*/api/experiments/:id", networkError));
    const user = userEvent.setup();
    renderApp(`${E}/biology`);
    expect(await screen.findByText(copy.experiment.unavailable)).toBeInTheDocument();

    server.resetHandlers();
    serveExperiment(covidExperiment());
    await user.click(screen.getByRole("button", { name: copy.retry }));
    expect(
      await screen.findByRole("list", { name: copy.biology.targetsLabel }),
    ).toBeInTheDocument();
  });

  it("says plainly when there is no such Experiment", async () => {
    renderApp(`${E}/biology`);
    expect(
      await screen.findByRole("heading", { level: 1, name: copy.experiment.notFound.title }),
    ).toBeInTheDocument();
  });

  it("says it is waiting while queued", async () => {
    serveExperiment(covidExperiment("queued"));
    renderApp(`${E}/evidence`);
    expect(await screen.findByText(copy.experiment.queued)).toBeInTheDocument();
  });
});
