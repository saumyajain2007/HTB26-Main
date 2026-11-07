import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useDebouncedValue } from "../lib/useDebouncedValue";
import { api, apiUrl } from "./client";
import { ApiError, fetchText, unwrap } from "./errors";
import type { Conformer, DockFile, Experiment, ExperimentStatus, JuryRun } from "./types";

/** How long typing must pause before the disease search asks the API. */
export const SEARCH_DEBOUNCE_MS = 250;

/** How often a building Experiment is polled. */
export const BUILD_POLL_MS = 1000;

/** How often an Experiment is polled while its jury or a docking job is still working. */
export const WORK_POLL_MS = 2000;

const SEARCH_LIMIT = 8;

export const queryKeys = {
  search: (query: string) => ["diseases", "search", query] as const,
  commonDiseases: ["diseases", "common"] as const,
  experiment: (id: string) => ["experiments", id] as const,
  conformer: (cid: number) => ["molecules", cid, "conformer"] as const,
  history: (archived: boolean) => ["history", { archived }] as const,
  allHistory: ["history"] as const,
  structures: ["structures"] as const,
  evaluation: ["evaluation"] as const,
  dockJob: (id: string) => ["dock", id] as const,
  dockFile: (url: string, sha256: string) => ["dock-files", url, sha256] as const,
};

/**
 * Diseases matching `query`, asked once typing pauses. Blank queries never reach the API. While
 * a new query loads, the previous results stay on screen so the list does not flicker.
 */
export function useDiseaseSearch(query: string) {
  const debounced = useDebouncedValue(query.trim(), SEARCH_DEBOUNCE_MS);
  const result = useQuery({
    queryKey: queryKeys.search(debounced),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/api/diseases/search", {
          params: { query: { q: debounced, limit: SEARCH_LIMIT } },
          signal,
        }),
      ),
    enabled: debounced.length > 0,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });
  return { ...result, query: debounced, settled: debounced === query.trim() };
}

/** Well-known Diseases to offer before a search; the API puts the one to show first first. */
export function useCommonDiseases() {
  return useQuery({
    queryKey: queryKeys.commonDiseases,
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/diseases/common", { signal })).then((list) => list.items),
    staleTime: Infinity,
  });
}

/**
 * Opens a Disease and resolves to the Experiment to show for it: the newest active one that is
 * ready or still building, so its network can show at once, or else a new one, which starts
 * building. Choosing a Disease twice never builds it twice. Either way the Experiment is in the
 * cache before this resolves, so its screen draws it straight away instead of loading it again.
 */
export function useOpenDisease() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (diseaseId: string) => {
      const saved = await unwrap(
        api.GET("/api/experiments", { params: { query: { include_building: true } } }),
      );
      const reuse = saved.items.find(
        (item) => item.disease.id === diseaseId && item.status !== "failed",
      );
      if (reuse !== undefined) {
        // A copy already cached will do: its screen refreshes it once shown.
        const { queryKey, queryFn } = experimentQuery(reuse.id);
        await queryClient.query({ queryKey, queryFn, staleTime: "static" });
        return reuse.id;
      }
      const experiment = await unwrap(
        api.POST("/api/experiments", { body: { disease_id: diseaseId } }),
      );
      queryClient.setQueryData(queryKeys.experiment(experiment.id), experiment);
      return experiment.id;
    },
  });
}

const BUILDING: readonly ExperimentStatus[] = ["queued", "building"];

export function isBuilding(experiment: Experiment): boolean {
  return BUILDING.includes(experiment.status);
}

/**
 * True once a building Experiment has saved its Disease Targets and network: "Disease proteins"
 * draws them while the drugs are ranked and their evidence collected.
 */
export function hasEarlyResult(experiment: Experiment): boolean {
  return isBuilding(experiment) && experiment.targets.length > 0;
}

/** Jury runs and docking jobs share these states while they work. */
const WORKING: readonly JuryRun["status"][] = ["queued", "running"];

/** True while the Model jury is reviewing. */
export function isJuryWorking(jury: JuryRun | null): boolean {
  return jury !== null && WORKING.includes(jury.status);
}

/** True while the jury reviews or a binding pose is being computed. */
function isWorking(experiment: Experiment): boolean {
  return (
    isJuryWorking(experiment.jury) ||
    experiment.dock_jobs.some((job) => WORKING.includes(job.status))
  );
}

/**
 * One Experiment, polled every second while it is queued or building, and every two seconds
 * while its jury or a docking job works.
 */
function experimentQuery(id: string) {
  return queryOptions({
    queryKey: queryKeys.experiment(id),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/api/experiments/{experiment_id}", {
          params: { path: { experiment_id: id } },
          signal,
        }),
      ),
    refetchInterval: (query) => {
      const experiment = query.state.data;
      if (experiment === undefined) return false;
      if (isBuilding(experiment)) return BUILD_POLL_MS;
      return isWorking(experiment) ? WORK_POLL_MS : false;
    },
  });
}

export function useExperiment(id: string) {
  return useQuery(experimentQuery(id));
}

/**
 * The 3D conformer of a small molecule, or null when it has none: antibodies and other biologics
 * have no PubChem compound, and the API answers 404 for compounds without a 3D model.
 */
export function conformerQuery(pubchemCid: number | null) {
  return queryOptions({
    queryKey: queryKeys.conformer(pubchemCid ?? 0),
    queryFn: async ({ signal }): Promise<Conformer | null> => {
      if (pubchemCid === null) return null;
      try {
        return await unwrap(
          api.GET("/api/molecules/{pubchem_cid}/conformer", {
            params: { path: { pubchem_cid: pubchemCid } },
            signal,
          }),
        );
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: pubchemCid !== null,
    staleTime: Infinity,
  });
}

export function useConformer(pubchemCid: number | null) {
  return useQuery(conformerQuery(pubchemCid));
}

/**
 * Asks the Model jury to review the Experiment's shortlist. The queued run is put on the cached
 * Experiment at once, and the Experiment is fetched again so polling follows each juror.
 */
export function useAskJury(experimentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/experiments/{experiment_id}/jury", {
          params: { path: { experiment_id: experimentId } },
        }),
      ),
    onSuccess: (jury) => {
      queryClient.setQueryData<Experiment>(queryKeys.experiment(experimentId), (experiment) =>
        experiment === undefined ? experiment : { ...experiment, jury },
      );
    },
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.experiment(experimentId) }),
  });
}

/** Saved Experiments, newest first: active ones, or the archived ones. */
export function useHistory(archived: boolean) {
  return useQuery({
    queryKey: queryKeys.history(archived),
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/experiments", { params: { query: { archived } }, signal })).then(
        (list) => list.items,
      ),
  });
}

/**
 * Archives or restores an Experiment. The answer is the whole Experiment, so its cached copy is
 * replaced and both history lists are fetched again.
 */
export function useArchive() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, archive }: { id: string; archive: boolean }) => {
      const params = { path: { experiment_id: id } };
      return unwrap(
        archive
          ? api.POST("/api/experiments/{experiment_id}/archive", { params })
          : api.POST("/api/experiments/{experiment_id}/restore", { params }),
      );
    },
    onSuccess: (experiment) => {
      queryClient.setQueryData(queryKeys.experiment(experiment.id), experiment);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.allHistory }),
  });
}

/** The prepared protein structures a binding pose can be computed in. They rarely change. */
export function useStructures() {
  return useQuery({
    queryKey: queryKeys.structures,
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/structures", { signal })).then((list) => list.structures),
    staleTime: Infinity,
  });
}

/** The frozen evaluation: it never changes while the app runs. */
export function useEvaluation() {
  return useQuery({
    queryKey: queryKeys.evaluation,
    queryFn: ({ signal }) => unwrap(api.GET("/api/evaluation", { signal })),
    staleTime: Infinity,
  });
}

/**
 * Asks for a binding pose of one Candidate in one prepared structure. The new job is put on the
 * cached Experiment at once, and the Experiment is fetched again, so polling follows the job
 * until it is done. An identical earlier computation comes back already done.
 */
export function useRequestDock(experimentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ candidateId, structureId }: { candidateId: string; structureId: string }) =>
      unwrap(
        api.POST("/api/dock", {
          body: {
            experiment_id: experimentId,
            candidate_id: candidateId,
            structure_id: structureId,
          },
        }),
      ),
    onSuccess: (job) => {
      queryClient.setQueryData<Experiment>(queryKeys.experiment(experimentId), (experiment) =>
        experiment === undefined
          ? experiment
          : {
              ...experiment,
              dock_jobs: [...experiment.dock_jobs.filter((other) => other.id !== job.id), job],
            },
      );
    },
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.experiment(experimentId) }),
  });
}

/** One docking job, such as a structure's saved redocking control. Off while `id` is null. */
export function useDockJob(id: string | null) {
  return useQuery({
    queryKey: queryKeys.dockJob(id ?? ""),
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/dock/{job_id}", { params: { path: { job_id: id ?? "" } }, signal })),
    enabled: id !== null,
  });
}

/** A docking result file as text. Its checksum is in the key, so a file never changes under it. */
export function dockFileQuery(file: DockFile) {
  return queryOptions({
    queryKey: queryKeys.dockFile(file.url, file.sha256),
    queryFn: ({ signal }) => fetchText(apiUrl(file.url), signal),
    staleTime: Infinity,
  });
}

/**
 * Starts an Experiment's follow-ups: the Model jury and a binding pose for every drug that can be
 * docked. Asking again starts nothing new. The answer is the whole Experiment, with what started.
 */
export function useStartFollowUps() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (experimentId: string) =>
      unwrap(
        api.POST("/api/experiments/{experiment_id}/follow-ups", {
          params: { path: { experiment_id: experimentId } },
        }),
      ),
    onSuccess: (experiment) => {
      queryClient.setQueryData(queryKeys.experiment(experiment.id), experiment);
    },
  });
}
