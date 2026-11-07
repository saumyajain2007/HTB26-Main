import type { ReactElement } from "react";
import { FigureNote } from "../app/Figure";
import { copy } from "../copy/en";
import type { ResistanceProfile } from "../lib/resistance";

export interface PathogenInputProps {
  /**
   * The profile already on screen, when the reader comes back to step 1 from the map. Undefined
   * on `/resistance`, before anything has been profiled.
   */
  profile?: ResistanceProfile | undefined;
  /**
   * Called with the ID of the profile to open, once the reader picks a preset that has one or a
   * pasted gene list has been profiled. The page navigates; this component never does.
   */
  onProfile: (profileId: string) => void;
}

/**
 * Step 1 of the resistance flow: pick one of the three pathogen presets, or paste resistance
 * gene names. Draws its own `Panel`s into the page's figure grid.
 *
 * TODO(#29): build the input screen. It should read the presets with `usePathogenPresets()` from
 * `src/lib/resistance.ts`, offer a preset whose `profile_id` is null as not yet available with
 * the preset's own `note`, and show unresolved gene names from a profile's `unresolved_inputs`
 * rather than dropping them. Until then this says so and takes no input; the props above are the
 * contract, so the signature is written out and the placeholder ignores it.
 */
export const PathogenInput: (props: PathogenInputProps) => ReactElement = () => (
  <FigureNote>{copy.resistance.notBuilt.pathogen}</FigureNote>
);
