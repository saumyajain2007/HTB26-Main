/**
 * Test data for the antibiotic resistance flow, read straight from the API's own fixture files
 * (`@api-fixtures` is an alias for `api/htb_api/fixtures`), so the web tests and the API serve
 * one copy of the data.
 *
 * It keeps the API's own shape of the world: **only *S. aureus* has a profile**. The other two
 * presets carry `profile_id: null` and a note, exactly as `services/resistance.py` serves them,
 * so a test can check that the app shows them as not yet available instead of inventing data.
 */
import candidatesFile from "@api-fixtures/resistance/antibiotic_candidates.json";
import certificatesFile from "@api-fixtures/resistance/certificate.json";
import profileFile from "@api-fixtures/resistance/resistance_profile.json";
import type {
  AntibioticCandidateResult,
  Certificate,
  PathogenPreset,
  ResistanceProfile,
} from "../lib/resistance";
import { http } from "./http";

// JSON imports widen string literals (a status becomes `string`); the API validates these same
// files against the contract, so narrowing them here is safe.
const profileData = profileFile as unknown as ResistanceProfile;
const candidatesData = candidatesFile as unknown as AntibioticCandidateResult;
const certificatesData = certificatesFile as unknown as { certificates: Certificate[] };

/** The one profile the fixtures cover: the *S. aureus* isolate with `mecA` and `gyrA` S84L. */
export const PROFILE_ID = profileData.profile_id;

/** A profile ID the API has nothing for, so a route can be asked for a 404. */
export const UNKNOWN_PROFILE_ID = "00000000-0000-4000-8000-00000000ffff";

/** The preset that has a profile, and one that has none; `pathogenPresets()` holds both. */
export const PRESET_WITH_PROFILE = "s_aureus_mrsa";
export const PRESET_WITHOUT_PROFILE = "k_pneumoniae_esbl";

/** `FIXTURE_NOTE` in `app/api/htb_api/services/resistance.py`, which the routes set. */
export const FIXTURE_NOTE =
  "Fixture data. The scores, MICs and ranks are made up; the descriptors, rule " +
  "outcomes and Lean results are real output of core/verify.";

/** A fresh copy on every call, so a test can change one without touching the next. */
export function resistanceProfile(): ResistanceProfile {
  return structuredClone(profileData);
}

/** The ranked candidates for `PROFILE_ID`, with the `fixture_note` the API adds. */
export function antibioticCandidates(): AntibioticCandidateResult {
  return { ...structuredClone(candidatesData), fixture_note: FIXTURE_NOTE };
}

export function certificates(): Certificate[] {
  return structuredClone(certificatesData.certificates);
}

/** The three presets of issue #4, as `FixtureResistance.presets()` builds them. */
export function pathogenPresets(): PathogenPreset[] {
  const covered = profileData.input.species.name;
  const presets: readonly { id: string; label: string; name: string; ncbiTaxid: number }[] = [
    {
      id: "s_aureus_mrsa",
      label: "MRSA (S. aureus)",
      name: "Staphylococcus aureus",
      ncbiTaxid: 1280,
    },
    {
      id: "k_pneumoniae_esbl",
      label: "ESBL/KPC K. pneumoniae",
      name: "Klebsiella pneumoniae",
      ncbiTaxid: 573,
    },
    {
      id: "a_baumannii_carbapenem",
      label: "Carbapenem-resistant A. baumannii",
      name: "Acinetobacter baumannii",
      ncbiTaxid: 470,
    },
  ];
  return presets.map(({ id, label, name, ncbiTaxid }) => {
    const fixture = name === covered;
    return {
      id,
      label,
      pathogen: { name, ncbi_taxid: ncbiTaxid },
      profile_id: fixture ? PROFILE_ID : null,
      note: fixture ? FIXTURE_NOTE : "No profile built for this pathogen yet.",
    };
  });
}

/**
 * The five resistance routes, answering the fixtures as the API does: an unknown profile ID is a
 * 404 with the API's own wording. Already wired into `server.ts`; `server.use(...)` one of these
 * again to replace it for a single test.
 */
export const resistanceHandlers = [
  http.get("/api/resistance/pathogens", ({ response }) =>
    response(200).json({ items: pathogenPresets() }),
  ),

  http.get("/api/resistance/profiles", ({ response }) =>
    response(200).json({ items: [resistanceProfile()] }),
  ),

  http.get("/api/resistance/profiles/{profile_id}", ({ params, response }) => {
    if (params.profile_id !== PROFILE_ID) {
      return response(404).json({ detail: `No resistance profile ${params.profile_id}.` });
    }
    return response(200).json(resistanceProfile());
  }),

  http.get("/api/resistance/profiles/{profile_id}/candidates", ({ params, response }) => {
    if (params.profile_id !== PROFILE_ID) {
      return response(404).json({
        detail: `No resistance profile ${params.profile_id}.`,
      });
    }
    return response(200).json(antibioticCandidates());
  }),

  http.get("/api/resistance/certificates", ({ response }) =>
    response(200).json({ contract_version: "1", certificates: certificates() }),
  ),
];
