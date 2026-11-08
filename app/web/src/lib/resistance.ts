import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { unwrap } from "../api/errors";
import type { components } from "../api/schema";

/**
 * The antibiotic resistance flow's data (`docs/contracts.md`, `app/api/README.md` under
 * "Resistance routes"). Every shape comes from the generated contract, so a contract change
 * fails `tsc` here rather than at runtime.
 *
 * These routes are fixture-backed today and answer the same bytes every time, so each query is
 * kept for the life of the page (`staleTime: Infinity`), as the evaluation's is. Nothing here
 * claims a candidate works: `evasion.status` is what CARD links, not a measured result, and an
 * `AntibioticCandidateResult` with a `fixture_note` is made-up data and must be labelled as such
 * wherever its numbers are shown.
 */

export type Pathogen = components["schemas"]["Pathogen"];
export type PathogenPreset = components["schemas"]["PathogenPreset"];
export type ResistanceProfile = components["schemas"]["ResistanceProfile"];
export type AntibioticCandidateResult = components["schemas"]["AntibioticCandidateResult"];
export type AntibioticCandidate = components["schemas"]["AntibioticCandidate"];
export type Certificate = components["schemas"]["Certificate"];
export type EvasionStatus = components["schemas"]["EvasionStatus"];
export type ProfileRequest = components["schemas"]["ProfileRequest"];
export type JuryRun = components["schemas"]["JuryRun"];
export type JuryVote = components["schemas"]["JuryVote"];

export const resistanceKeys = {
  pathogens: ["resistance", "pathogens"] as const,
  profiles: ["resistance", "profiles"] as const,
  profile: (profileId: string) => ["resistance", "profiles", profileId] as const,
  candidates: (profileId: string) => ["resistance", "profiles", profileId, "candidates"] as const,
  certificates: ["resistance", "certificates"] as const,
  jury: (profileId: string) => ["resistance", "profiles", profileId, "jury"] as const,
};

/**
 * The pathogens the API can profile. A preset whose `profile_id` is null has no profile built
 * yet; its `note` says why, and the input screen must offer it as unavailable rather than
 * invent data for it.
 */
export function usePathogenPresets() {
  return useQuery({
    queryKey: resistanceKeys.pathogens,
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/resistance/pathogens", { signal })).then((list) => list.items),
    staleTime: Infinity,
  });
}

/** True when a preset already has a resistance profile to open. */
export function hasProfile(
  preset: PathogenPreset,
): preset is PathogenPreset & { profile_id: string } {
  return preset.profile_id !== null;
}

/** Every resistance profile the API holds. One, on fixtures: the *S. aureus* isolate. */
export function useResistanceProfiles() {
  return useQuery({
    queryKey: resistanceKeys.profiles,
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/resistance/profiles", { signal })).then((list) => list.items),
    staleTime: Infinity,
  });
}

/** One resistance profile. Off, and never asked for, while `profileId` is undefined. */
export function resistanceProfileQuery(profileId: string | undefined) {
  return queryOptions({
    queryKey: resistanceKeys.profile(profileId ?? ""),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/api/resistance/profiles/{profile_id}", {
          params: { path: { profile_id: profileId ?? "" } },
          signal,
        }),
      ),
    enabled: profileId !== undefined,
    staleTime: Infinity,
  });
}

export function useResistanceProfile(profileId: string | undefined) {
  return useQuery(resistanceProfileQuery(profileId));
}

/**
 * The antibiotic candidates ranked against one profile. Off while `profileId` is undefined.
 * `ranking` records how the ranks were made; the features are kept apart, never blended.
 */
export function antibioticCandidatesQuery(profileId: string | undefined) {
  return queryOptions({
    queryKey: resistanceKeys.candidates(profileId ?? ""),
    queryFn: ({ signal }) =>
      unwrap(
        api.GET("/api/resistance/profiles/{profile_id}/candidates", {
          params: { path: { profile_id: profileId ?? "" } },
          signal,
        }),
      ),
    enabled: profileId !== undefined,
    staleTime: Infinity,
  });
}

export function useAntibioticCandidates(profileId: string | undefined) {
  return useQuery(antibioticCandidatesQuery(profileId));
}

/**
 * Every property certificate the API holds, by InChIKey. A certificate confirms the encoded
 * property rules hold; it does not show a molecule is safe, selective or active.
 */
export function useCertificates() {
  return useQuery({
    queryKey: resistanceKeys.certificates,
    queryFn: ({ signal }) =>
      unwrap(api.GET("/api/resistance/certificates", { signal })).then((list) => list.certificates),
    staleTime: Infinity,
  });
}

/**
 * Build a profile from what someone typed, or from a species preset (#15's resolver, behind
 * `POST /api/resistance/profiles`).
 *
 * Resolving a determinant name needs CARD's vocabulary, which only the server holds, so this is
 * the only way typed names become a profile: the browser cannot tell a known name from an
 * unknown one and must not guess. The profile that comes back is cached under its own ID, so the
 * screen it opens does not fetch it again, and the names that matched nothing arrive in
 * `unresolved_inputs` with CARD's reason rather than being dropped.
 *
 * The API answers 503 when the process has no CARD release; `ApiError.status` carries that, so
 * the caller can say "not available here" instead of "that name is unknown".
 */
export function useBuildProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (request: ProfileRequest) =>
      unwrap(api.POST("/api/resistance/profiles", { body: request })),
    onSuccess: (profile) => {
      queryClient.setQueryData(resistanceKeys.profile(profile.profile_id), profile);
    },
  });
}

/**
 * Ask the Model jury to review the shortlist ranked against a profile, and keep its answer.
 *
 * The panel never sees our ranking: the packet withholds the rank, the evasion status and the
 * explanation, and the candidate labels are ordered by a hash. So its verdict is an independent
 * reading of the same evidence — and agreement between models is consistency, not correctness.
 *
 * The run is held in the query cache under the profile rather than in component state, so it
 * survives switching between candidates. The API does not store it, so a reload loses it and
 * asking again costs another live model call; the button is offered once per page for that
 * reason. A 503 means this API has no jury that can judge a new shortlist, which is a different
 * thing from the review having failed.
 */
export function useShortlistReview(profileId: string) {
  const queryClient = useQueryClient();
  const held = useQuery({
    queryKey: resistanceKeys.jury(profileId),
    // Never fetched: only the mutation below writes here.
    queryFn: () => null as JuryRun | null,
    enabled: false,
    staleTime: Infinity,
  });
  const ask = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/resistance/profiles/{profile_id}/jury", {
          params: { path: { profile_id: profileId } },
        }),
      ),
    onSuccess: (run) => {
      queryClient.setQueryData(resistanceKeys.jury(profileId), run);
    },
  });
  return { run: held.data ?? null, ask };
}

/** One juror's vote on a candidate, if that juror's ballot passed our checks. */
export function votesFor(run: JuryRun | null, candidateId: string): JuryVote[] {
  return (run?.votes ?? []).filter((vote) => vote.candidate_id === candidateId);
}
