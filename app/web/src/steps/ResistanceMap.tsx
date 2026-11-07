import type { ReactElement } from "react";
import { FigureNote } from "../app/Figure";
import { copy } from "../copy/en";
import type { AntibioticCandidateResult, ResistanceProfile } from "../lib/resistance";

export interface ResistanceMapProps {
  /** The profile to draw: its `mechanisms`, `defeated_classes` and the genes behind each. */
  profile: ResistanceProfile;
  /**
   * The candidates ranked against the profile, when they have loaded. Their `evasion.status` is
   * the only source for "evaded" and "partly affected"; the profile alone says which classes are
   * defeated. Undefined while the query is in flight, or when it failed.
   */
  candidates?: AntibioticCandidateResult | undefined;
}

/**
 * Step 2 of the resistance flow: the mechanisms an isolate carries against the drug classes they
 * defeat. Draws its own `Panel`s into the page's figure grid.
 *
 * TODO(#30): build the map. Join on ARO IDs, never names. `defeated_classes` is class-level, so
 * the map rules drugs out rather than in; `evasion.status: unaffected` means no link in CARD and
 * `unknown` means CARD cannot say, which is not the same thing, so neither may be drawn as a
 * measured result. Say the candidates' `fixture_note` once wherever their numbers show. Until
 * then this says so and draws nothing; the props above are the contract, so the signature is
 * written out and the placeholder ignores it.
 */
export const ResistanceMap: (props: ResistanceMapProps) => ReactElement = () => (
  <FigureNote>{copy.resistance.notBuilt.map}</FigureNote>
);
