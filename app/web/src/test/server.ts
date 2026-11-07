import { HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { createOpenApiHttp } from "openapi-msw";
import type { components, paths } from "../api/schema";
import type { Experiment } from "../api/types";
import {
  conformers,
  covidExperiment,
  covidJury,
  dockJob,
  evaluation,
  redockControl,
  searchDiseases,
  structures,
  summaryOf,
} from "./fixtures";

/** MSW handlers typed by the generated contract: a wrong path or body fails `tsc`. */
export const http = createOpenApiHttp<paths>({ baseUrl: window.location.origin });

/**
 * The fake API's state. Each Experiment ID maps to the responses its GETs return in turn; the
 * last one repeats. That plays out a build (queued, building, ready) across polls.
 */
export const fakeApi = {
  experiments: new Map<string, Experiment[]>(),
  /** What a newly created Experiment answers to its GETs, in order. */
  buildSequence: (id: string): Experiment[] => [
    covidExperiment("building", "ranking", id),
    covidExperiment("ready", null, id),
  ],
  /** What the Experiment answers to its GETs once the jury is asked, in order. */
  jurySequence: (experiment: Experiment): Experiment[] => [
    { ...experiment, jury: covidJury("done") },
  ],
  created: 0,
  /** The Experiment IDs the app asked to start follow-ups for, in order. */
  followedUp: [] as string[],
};

/** The Experiment's current state: the last answer its GETs will give. */
function latest(id: string): Experiment | undefined {
  return fakeApi.experiments.get(id)?.at(-1);
}

/** Changes every answer an Experiment's GETs will give. */
function update(
  id: string,
  change: (experiment: Experiment) => Experiment,
): Experiment | undefined {
  const sequence = fakeApi.experiments.get(id);
  if (sequence === undefined) return undefined;
  const changed = sequence.map(change);
  fakeApi.experiments.set(id, changed);
  return changed.at(-1);
}

/**
 * The contract's own Experiment type. It differs from the app's only in fixed-length tuples (a
 * docking box's centre and size), which the fixtures fill with three numbers each.
 */
const contract = (experiment: Experiment) => experiment as components["schemas"]["Experiment"];

export function serveExperiment(...responses: Experiment[]): void {
  const first = responses[0];
  if (first) fakeApi.experiments.set(first.id, responses);
}

export const handlers = [
  http.get("/api/diseases/common", ({ response }) =>
    response(200).json({ items: [{ id: covidExperiment().disease.id, name: "COVID-19" }] }),
  ),

  http.get("/api/diseases/search", ({ query, response }) => {
    const q = query.get("q");
    return response(200).json({ query: q, results: searchDiseases(q) });
  }),

  http.post("/api/experiments", async ({ request, response }) => {
    const body = await request.json();
    fakeApi.created += 1;
    const id = `00000000-0000-4000-8000-${String(fakeApi.created).padStart(12, "0")}`;
    const queued = covidExperiment("queued", null, id);
    if (body.disease_id !== queued.disease.id) {
      return response(422).json({ detail: `There is no data for the Disease ${body.disease_id}.` });
    }
    fakeApi.experiments.set(id, fakeApi.buildSequence(id));
    return response(202).json(contract(queued));
  }),

  http.get("/api/experiments/{experiment_id}", ({ params, response }) => {
    const sequence = fakeApi.experiments.get(params.experiment_id);
    const next = sequence && (sequence.length > 1 ? sequence.shift() : sequence[0]);
    if (!next) {
      return response(404).json({ detail: "There is no saved Experiment with this ID." });
    }
    return response(200).json(contract(next));
  }),

  http.get("/api/experiments", ({ query, response }) => {
    const archived = query.get("archived") === "true";
    const building = query.get("include_building") === "true";
    const items = [...fakeApi.experiments.values()]
      .flatMap((sequence) => sequence.slice(-1))
      .filter((experiment) => building || experiment.status === "ready")
      .filter((experiment) => (experiment.archived_at !== null) === archived)
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .map(summaryOf);
    return response(200).json({ items });
  }),

  http.post("/api/experiments/{experiment_id}/jury", ({ params, response }) => {
    const experiment = latest(params.experiment_id);
    if (!experiment) {
      return response(404).json({ detail: "There is no saved Experiment with this ID." });
    }
    if (experiment.archived_at !== null) {
      return response(409).json({
        detail: "This Experiment is archived. Restore it to ask the Model jury.",
      });
    }
    if (experiment.jury !== null) {
      return response(409).json({
        detail:
          "The Model jury has already reviewed this Experiment. Each Experiment has one jury review.",
      });
    }
    fakeApi.experiments.set(experiment.id, fakeApi.jurySequence(experiment));
    return response(202).json(covidJury("queued"));
  }),

  // Starts nothing here: the jury and pose tests drive those states themselves.
  http.post("/api/experiments/{experiment_id}/follow-ups", ({ params, response }) => {
    const experiment = latest(params.experiment_id);
    if (!experiment) {
      return response(404).json({ detail: "There is no saved Experiment with this ID." });
    }
    fakeApi.followedUp.push(experiment.id);
    return response(200).json(contract(experiment));
  }),

  http.post("/api/experiments/{experiment_id}/archive", ({ params, response }) => {
    const experiment = latest(params.experiment_id);
    if (!experiment) {
      return response(404).json({ detail: "There is no saved Experiment with this ID." });
    }
    if (experiment.dock_jobs.some((job) => job.status === "queued" || job.status === "running")) {
      return response(409).json({
        detail:
          "A binding pose is still being computed for this Experiment. Archive it once the docking job has finished.",
      });
    }
    const archivedAt = experiment.archived_at ?? "2026-10-25T10:00:00Z";
    const archived = update(experiment.id, (e) => ({ ...e, archived_at: archivedAt }));
    return response(200).json(contract(archived ?? experiment));
  }),

  http.post("/api/experiments/{experiment_id}/restore", ({ params, response }) => {
    const restored = update(params.experiment_id, (e) => ({ ...e, archived_at: null }));
    if (!restored) {
      return response(404).json({ detail: "There is no saved Experiment with this ID." });
    }
    return response(200).json(contract(restored));
  }),

  http.get("/api/evaluation", ({ response }) => response(200).json(evaluation)),

  http.get("/api/structures", ({ response }) =>
    response(200).json({
      structures: structures as components["schemas"]["Structure"][],
    }),
  ),

  // Like the fixture API's demo pair: an identical earlier result is reused, already done.
  http.post("/api/dock", async ({ request, response }) => {
    const body = await request.json();
    const experiment = latest(body.experiment_id);
    if (!experiment) {
      return response(404).json({ detail: "There is no saved Experiment with this ID." });
    }
    if (experiment.archived_at !== null) {
      return response(409).json({
        detail: "This Experiment is archived. Restore it to compute a binding pose.",
      });
    }
    const job = {
      ...dockJob("done", "9e1f3a20-6b7c-4d8e-8f90-a1b2c3d4e5f6", body.candidate_id),
      cached_from: redockControl().id,
    };
    update(experiment.id, (e) => ({ ...e, dock_jobs: [...e.dock_jobs, job] }));
    return response(202).json(job as components["schemas"]["DockJob"]);
  }),

  http.get("/api/dock/{job_id}", ({ params, response }) => {
    const control = redockControl();
    if (params.job_id !== control.id) {
      return response(404).json({ detail: "There is no docking job with this ID." });
    }
    return response(200).json(control as components["schemas"]["DockJob"]);
  }),

  // The viewer is a stand-in in tests, so a file's content only has to arrive.
  http.get("/api/files/{job_id}/{name}", ({ params, response }) =>
    response.untyped(new HttpResponse(`fixture ${params.name}\n`)),
  ),

  http.get("/api/molecules/{pubchem_cid}/conformer", ({ params, response }) => {
    const conformer = conformers.get(Number(params.pubchem_cid));
    if (!conformer) {
      return response(404).json({
        detail: `No 3D structure is available for PubChem compound ${params.pubchem_cid}.`,
      });
    }
    return response(200).json(conformer);
  }),
];

export const server = setupServer(...handlers);

/** A request that never reaches the API, as when the server is down. */
export const networkError = () => HttpResponse.error();
