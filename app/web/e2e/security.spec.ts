import { expect, test } from "./console";
import type { DockJob, Experiment, ExperimentSummary } from "../src/api/types";

test("anonymous browsers keep private histories and cannot access each other's experiments", async ({
  page,
  context,
  browser,
}) => {
  await page.goto("/explore");
  await expect(page).toHaveURL(/\/e\/[0-9a-f-]{36}\/disease$/);
  const ownerId = new URL(page.url()).pathname.split("/")[2] ?? "";
  expect(ownerId).toBeTruthy();
  const experimentPath = `/api/experiments/${ownerId}`;
  await expect
    .poll(async () => {
      const experiment = (await (await context.request.get(experimentPath)).json()) as Experiment;
      return experiment.status;
    })
    .toBe("ready");

  const ownerCookie = (await context.cookies()).find((cookie) => cookie.name === "oxhack_session");
  expect(ownerCookie).toMatchObject({ httpOnly: true, sameSite: "Lax", path: "/" });
  expect(await page.evaluate(() => document.cookie)).not.toContain("oxhack_session");

  const other = await browser.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const otherPage = await other.newPage();
    await otherPage.goto("/explore");
    await expect(otherPage).toHaveURL(/\/e\/[0-9a-f-]{36}\/disease$/);
    const otherId = new URL(otherPage.url()).pathname.split("/")[2];
    expect(otherId).not.toBe(ownerId);
    const otherCookie = (await other.cookies()).find((cookie) => cookie.name === "oxhack_session");
    expect(otherCookie?.value).toBeTruthy();
    expect(otherCookie?.value).not.toBe(ownerCookie?.value);

    const history = (await (
      await other.request.get("/api/experiments?include_building=true")
    ).json()) as { items: ExperimentSummary[] };
    expect(history.items.map((item) => item.id)).toEqual([otherId]);
    expect((await other.request.get(experimentPath)).status()).toBe(404);
    for (const action of ["archive", "restore", "jury", "follow-ups"]) {
      expect((await other.request.post(`${experimentPath}/${action}`)).status()).toBe(404);
    }

    const dockRequest = {
      experiment_id: ownerId,
      candidate_id: "CHEMBL2105759",
      structure_id: "6WTO_A",
    };
    expect((await other.request.post("/api/dock", { data: dockRequest })).status()).toBe(404);
    const dockResponse = await context.request.post("/api/dock", { data: dockRequest });
    expect(dockResponse.status()).toBe(202);
    const job = (await dockResponse.json()) as DockJob;
    expect((await other.request.get(`/api/dock/${job.id}`)).status()).toBe(404);
    expect((await other.request.get(`/api/files/${job.id}/poses.sdf`)).status()).toBe(404);
    expect((await context.request.get(`/api/files/${job.id}/poses.sdf`)).status()).toBe(200);

    await page.reload();
    await expect(page).toHaveURL(new RegExp(`/e/${ownerId}/disease$`));
    const reloadedCookie = (await context.cookies()).find(
      (cookie) => cookie.name === "oxhack_session",
    );
    expect(reloadedCookie?.value).toBe(ownerCookie?.value);
  } finally {
    await other.close();
  }
});
