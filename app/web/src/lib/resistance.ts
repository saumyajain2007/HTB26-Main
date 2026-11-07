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

export const resistanceKeys = {
  pathogens: ["resistance", "pathogens"] as const,
  profiles: ["resistance", "profiles"] as const,
  profile: (profileId: string) => ["resistance", "profiles", profileId] as const,
  candidates: (profileId: string) => ["resistance", "profiles", profileId, "candidates"] as const,
  certificates: ["resistance", "certificates"] as const,
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
