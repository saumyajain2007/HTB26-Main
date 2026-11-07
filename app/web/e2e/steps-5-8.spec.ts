import type { Page } from "@playwright/test";
import type { GLViewer } from "3dmol";
import { expect, test } from "./console";

/*
 * Steps 5 to 8 against the real API in fixture mode (COVID-19). Once a student moves past choosing
 * the disease, the app starts the Experiment's follow-ups: the Model jury, and a binding pose for
 * every drug that can be docked. So the jury is at work or done when a student reaches it, and the
 * pose is there on arrival. Then compare three drugs and archive and restore the Experiment. Wording comes from
 * web/src/copy/en.ts; model names come from the API.
 */

async function expectStep(page: Page, title: string) {
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
}

interface ExperimentState {
  status: string;
  dock_jobs: { status: string }[];
}

async function state(page: Page, id: string): Promise<ExperimentState> {
  const response = await page.request.get(`/api/experiments/${id}`);
  return (await response.json()) as ExperimentState;
}

/** Creates a COVID-19 Experiment through the API and waits until it is ready. */
async function readyExperiment(page: Page): Promise<string> {
  const created = await page.request.post("/api/experiments", {
    data: { disease_id: "MONDO_0100096" },
  });
  expect(created.status()).toBe(202);
  const { id } = (await created.json()) as { id: string };
  await expect
    .poll(
      async () => {
        return (await state(page, id)).status === "ready";
      },
      { timeout: 15_000 },
    )
    .toBe(true);
  return id;
}

test("the jury has started on its own; a student compares drugs, then archives and restores", async ({
  page,
}) => {
  const id = await readyExperiment(page);

  // Step 5: opening a step past the first started the jury; nothing to ask, just the result.
  await page.goto(`/e/${id}/jury`);
  await expectStep(page, "Model jury");
  await expect(page.getByRole("button", { name: "Ask the Model jury" })).toHaveCount(0);

  const board = page.getByRole("table", { name: "Each model’s rank and decision for every drug" });
  await expect(board).toBeVisible({ timeout: 20_000 });
  await expect(board.getByTestId(/^jury-row-/)).toHaveCount(15);
  await expect(board.locator("[data-contested]")).toHaveCount(1);
  await expect(page.getByTestId("jury-row-CHEMBL107")).toHaveAttribute("data-contested", "true");
  for (const model of ["Claude Sonnet 5", "GPT-5.4", "GLM-5.3"]) {
    await expect(board.getByRole("columnheader", { name: model })).toHaveCount(1);
  }
  await expect(page.getByText("Agreement", { exact: true })).toHaveCount(1);
  await expect(page.getByText("0.62", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Split decision", { exact: true })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Ask the Model jury" })).toHaveCount(0);

  // The reading pane opens on the consensus favourite.
  let reading = page.getByRole("region", { name: "What the models said about Baricitinib" });
  await expect(reading.getByRole("heading", { level: 2 })).toHaveText("Baricitinib");
  await expect(reading.getByText("All 3 say Investigate", { exact: true })).toBeVisible();
  await expect(reading.getByText(/Blocking JAK1 may also weaken/)).toHaveCount(1);

  // Anywhere on a row picks its drug (here its middle, over the tiles); the arrow keys then
  // move through the drugs, not the steps.
  await page.getByTestId("jury-row-CHEMBL107").click();
  reading = page.getByRole("region", { name: "What the models said about Colchicine" });
  await expect(reading.getByText("Consensus #6", { exact: true })).toBeVisible();
  await expect(
    reading.getByText("1 says Investigate, 1 says Watch, 1 says Set aside", { exact: true }),
  ).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await expectStep(page, "Model jury");
  await expect(board.getByRole("button", { name: "Upadacitinib" })).toBeFocused();
  await expect(
    page.getByRole("region", { name: "What the models said about Upadacitinib" }),
  ).toBeVisible();
  // The board and the reading pane fit the step: the page itself doesn't scroll.
  expect(
    await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight),
  ).toBe(true);

  // Step 6: three drugs side by side, the molecules on one shared canvas.
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expectStep(page, "Compare");
  const pickers = page.getByRole("combobox", { name: "Change drug" });
  await expect(pickers).toHaveCount(3);
  await expect(pickers.nth(0)).toHaveValue("CHEMBL2105759");
  await expect(page.getByRole("img", { name: "Baricitinib in 3D. Drag to rotate." })).toBeVisible();
  await expect(page.getByRole("rowheader", { name: "Jury decision" })).toHaveCount(1);
  await pickers.nth(2).selectOption("CHEMBL107");
  await expect(page.getByText("Split decision", { exact: true })).toHaveCount(1);
  // Only drugs with a 3D model are offered: the antibodies (Tocilizumab and three more) are not.
  const offered = pickers.nth(1).getByRole("option");
  await expect(offered).toHaveCount(11);
  await expect(offered.filter({ hasText: "Tocilizumab" })).toHaveCount(0);
  await pickers.nth(1).selectOption("CHEMBL384467");
  await expect(
    page.getByRole("img", { name: "Dexamethasone in 3D. Drag to rotate." }),
  ).toBeVisible();
  await expect(page.getByText(/no (small-molecule )?3D model/i)).toHaveCount(0);
  // The hidden network plus one canvas for every molecule: well within the browser's limit.
  expect(await page.locator("canvas").count()).toBeLessThanOrEqual(3);

  // Step 8: archive the open experiment, then restore it, once its poses are computed (an
  // Experiment can't be archived while one is).
  await expect
    .poll(async () => (await state(page, id)).dock_jobs.every((job) => job.status === "done"), {
      timeout: 20_000,
    })
    .toBe(true);
  await page.goto(`/e/${id}/history`);
  await expectStep(page, "History");
  const list = page.getByRole("list", { name: "Experiments" });
  const open = list.locator("li[aria-current]");
  await expect(open).toContainText("COVID-19");
  await expect(open).toContainText("Open");
  await expect(page.getByText(/^Data: Open Targets/)).toHaveCount(1);
  await expect(page.getByText(/delete/i)).toHaveCount(0);
  await open.getByRole("button", { name: "Archive" }).click();
  await expect(list.locator("li[aria-current]")).toHaveCount(0);

  await page.getByRole("button", { name: /^Archived/ }).click();
  const archived = list.locator("li[aria-current]");
  await expect(archived).toContainText("COVID-19");
  await archived.getByRole("button", { name: "Restore" }).click();
  await expect(archived).toHaveCount(0);
  await page.getByRole("button", { name: /^Saved/ }).click();
  await expect(list.locator("li[aria-current]")).toContainText("COVID-19");
});

/**
 * Counts every WebGL context the page creates, on a canvas or offscreen (3Dmol.js draws through
 * an offscreen one), so the test can tell how many are still alive.
 */
async function trackWebGLContexts(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const contexts: WebGLRenderingContext[] = [];
    const origins = new Map<
      WebGLRenderingContext,
      { stack: string; lossRequests: number; lostOnStep?: string }
    >();
    interface HasContext {
      getContext: (this: unknown, ...args: never[]) => unknown;
    }
    const track = (proto: HasContext) => {
      const original = proto.getContext;
      proto.getContext = function getContext(this: unknown, ...args: never[]) {
        const context = original.apply(this, args);
        const isGL =
          context instanceof WebGLRenderingContext || context instanceof WebGL2RenderingContext;
        if (isGL && !contexts.includes(context)) {
          contexts.push(context);
          const origin: { stack: string; lossRequests: number; lostOnStep?: string } = {
            stack: new Error().stack ?? "unknown",
            lossRequests: 0,
          };
          origins.set(context, origin);
          const extension = context.getExtension("WEBGL_lose_context");
          if (extension !== null) {
            const lose = extension.loseContext.bind(extension);
            extension.loseContext = () => {
              origin.lossRequests += 1;
              origin.lostOnStep ??= document.querySelector("h1")?.textContent ?? "";
              lose();
            };
          }
        }
        return context;
      };
    };
    track(HTMLCanvasElement.prototype);
    track(OffscreenCanvas.prototype);
    const start = document.startViewTransition.bind(document);
    let starts = 0;
    document.startViewTransition = (options) => {
      starts += 1;
      return start(options);
    };
    Object.assign(window, {
      nativeTransitionStarts: () => starts,
      liveWebGLContexts: () => contexts.filter((context) => !context.isContextLost()).length,
      lostOnSteps: () =>
        contexts.flatMap((context) => {
          const step = origins.get(context)?.lostOnStep;
          return step === undefined ? [] : [step];
        }),
      webGLContextDiagnostics: () =>
        contexts.map((context) => ({
          ...origins.get(context),
          lost: context.isContextLost(),
          canvas: context.canvas.constructor.name,
          connected:
            context.canvas instanceof HTMLCanvasElement ? context.canvas.isConnected : null,
          className: context.canvas instanceof HTMLCanvasElement ? context.canvas.className : null,
          width: context.canvas.width,
          height: context.canvas.height,
        })),
    });
  });
}

function liveContexts(page: Page): Promise<number> {
  return page.evaluate(() =>
    (window as unknown as { liveWebGLContexts: () => number }).liveWebGLContexts(),
  );
}

test("a hidden network cannot delay leaving a pose while native snapshot capture stalls", async ({
  page,
}) => {
  const id = await readyExperiment(page);
  await page.goto(`/e/${id}/pose`);
  const view = page.getByRole("img", {
    name: "Baricitinib in JAK2, in 3D. Drag to rotate, scroll to zoom.",
  });
  await expect(view).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  await expect(view).toHaveAttribute("data-surface", "on", { timeout: 20_000 });
  await page.evaluate(() => {
    const start = document.startViewTransition.bind(document);
    let starts = 0;
    Object.assign(window, { nativeTransitionStarts: () => starts });
    document.startViewTransition = (options) => {
      starts += 1;
      const update = typeof options === "function" ? options : options?.update;
      return start({
        update: async () => {
          // Slow GPU snapshot capture must never hold up a step whose network is hidden.
          await new Promise<void>((resolve) => setTimeout(resolve, 10_000));
          await update?.();
        },
      });
    };
  });
  await page.getByRole("link", { name: "History", exact: true }).click();
  await expectStep(page, "History");
  await expect(view).toHaveCount(0);
  expect(
    await page.evaluate(() =>
      (window as unknown as { nativeTransitionStarts: () => number }).nativeTransitionStarts(),
    ),
  ).toBe(0);
});

test("a student shows baricitinib's binding pose and checks it against the crystal", async ({
  page,
}, testInfo) => {
  await trackWebGLContexts(page);
  const id = await readyExperiment(page);

  // Walk on from Compare: the pose takes the stage and the network stays hidden.
  await page.goto(`/e/${id}/compare`);
  await expectStep(page, "Compare");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expectStep(page, "Binding pose");
  await expect(page.getByRole("combobox", { name: "Change drug" })).toHaveValue("CHEMBL2105759");
  await expect(
    page.getByText("Crystal structure 6WTO of JAK2, 1.74 Å resolution", { exact: true }),
  ).toHaveCount(1);
  // Only the drugs that can be docked are offered; the others aren't listed.
  await expect(page.getByText("Not available yet", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("img", { name: "Protein network in 3D. Drag to rotate." }),
  ).toBeHidden();

  // The pose was started when the student moved past step 1 (a saved demo pair): no button.
  await expect(page.getByRole("button", { name: "Show binding pose" })).toHaveCount(0);
  const view = page.getByRole("img", {
    name: "Baricitinib in JAK2, in 3D. Drag to rotate, scroll to zoom.",
  });
  await expect(view).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  await expect(view.locator("canvas")).toHaveCount(1);
  await expect(view.locator("canvas")).toBeVisible();
  // Each number once, marked as demo data, and never called by the program's or statistic's name.
  await expect(page.getByText("Docking score", { exact: true })).toHaveCount(1);
  await expect(page.getByText("−10.2", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Redock check", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Good match", { exact: true })).toHaveCount(1);
  await expect(
    page.getByText("Demo data: this pose, its docking score and the redock check are made up."),
  ).toHaveCount(1);
  await expect(page.locator("body")).not.toContainText(/vina|rmsd/i);

  // The pocket surface is computed in the background; it turns off and on again cleanly.
  const surface = page.getByRole("button", { name: "Pocket surface" });
  await expect(surface).toHaveAttribute("aria-pressed", "true");
  await expect(view).toHaveAttribute("data-surface", "on", { timeout: 20_000 });
  await surface.click();
  await expect(surface).toHaveAttribute("aria-pressed", "false");
  await expect(view).toHaveAttribute("data-surface", "off");
  await surface.click();
  await expect(view).toHaveAttribute("data-surface", "on", { timeout: 20_000 });

  // The crystal position, drawn over the pose and taken away again.
  const overlay = page.getByRole("button", { name: "Crystal position" });
  await expect(overlay).toHaveAttribute("aria-pressed", "false");
  await overlay.click();
  await expect(overlay).toHaveAttribute("aria-pressed", "true");
  await overlay.click();
  await expect(overlay).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Spin" }).click();
  await page.getByRole("button", { name: "Reset view" }).click();

  // The hidden network and the pose: two live WebGL contexts, within the limit of three.
  expect(await page.locator("canvas").count()).toBeLessThanOrEqual(3);
  expect(await liveContexts(page)).toBe(2);

  await view.locator("canvas").evaluate((canvas) => {
    const viewer = (canvas as HTMLCanvasElement & { _3dmol_viewer: GLViewer })._3dmol_viewer;
    const gl = viewer.getRenderer().getContext();
    const clear = viewer.clear.bind(viewer);
    Object.assign(window, { poseClearedWhileLive: false });
    viewer.clear = () => {
      if (!gl.isContextLost()) Object.assign(window, { poseClearedWhileLive: true });
      return clear();
    };
  });

  // Leaving the step releases the pose's context, once the step's transition has played.
  await page.getByRole("link", { name: "History", exact: true }).click();
  await expectStep(page, "History");
  await expect(view).toHaveCount(0);
  try {
    // Released after History is drawn, once the GPU has caught up: seconds on a software GPU.
    await expect.poll(() => liveContexts(page), { timeout: 30_000 }).toBe(1);
  } catch (error) {
    const diagnostics = await page.evaluate(() =>
      (window as unknown as { webGLContextDiagnostics: () => unknown }).webGLContextDiagnostics(),
    );
    await testInfo.attach("webgl-contexts", {
      body: JSON.stringify(diagnostics, null, 2),
      contentType: "application/json",
    });
    throw error;
  }
  expect(
    await page.evaluate(
      () => (window as unknown as { poseClearedWhileLive: boolean }).poseClearedWhileLive,
    ),
    "3Dmol clearing must not render a final protein frame during navigation",
  ).toBe(false);
  expect(
    await page.evaluate(() =>
      (window as unknown as { lostOnSteps: () => string[] }).lostOnSteps().at(-1),
    ),
    "losing the pose's context waits for the GPU, so it must not hold up the next step",
  ).toBe("History");
  expect(
    await page.evaluate(() =>
      (window as unknown as { nativeTransitionStarts: () => number }).nativeTransitionStarts(),
    ),
    "3D steps must navigate without snapshotting their live canvases",
  ).toBe(0);
});
