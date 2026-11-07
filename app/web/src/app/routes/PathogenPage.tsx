import { useCallback } from "react";
import { useNavigate } from "react-router";
import { FigureGrid } from "../Figure";
import { ResistanceShell } from "../Shell";
import { PathogenInput } from "../../steps/PathogenInput";
import { RESISTANCE_PATH, resistanceStepPath } from "../steps";

/**
 * `/resistance`: step 1 of the resistance flow, before any profile is on screen. Once a profile
 * exists the reader moves to `/resistance/:profileId/map`, and step 1 keeps its page there, so
 * they can change the pathogen without losing the one they had.
 */
export function PathogenPage() {
  const navigate = useNavigate();
  const openProfile = useCallback(
    (profileId: string) => {
      void navigate(resistanceStepPath(profileId, "map") ?? RESISTANCE_PATH);
    },
    [navigate],
  );
  return (
    <ResistanceShell step="pathogen">
      <FigureGrid layout="single">
        <PathogenInput onProfile={openProfile} />
      </FigureGrid>
    </ResistanceShell>
  );
}
