import { useCallback } from "react";
import { useNavigate, useOutletContext, useParams } from "react-router";
import { isResistanceStepSlug } from "../../copy/en";
import { PathogenInput } from "../../steps/PathogenInput";
import { ResistanceCandidates } from "../../steps/ResistanceCandidates";
import { ResistanceMap } from "../../steps/ResistanceMap";
import { RESISTANCE_PATH, resistanceStepPath } from "../steps";
import type { ResistanceStepContext } from "./ResistanceLayout";

/** One resistance step's own panels, placed into the layout's figure grid. */
export function ResistanceStep() {
  const { step } = useParams();
  const { profile, candidates, certificates, candidatesLoading, retryCandidates } =
    useOutletContext<ResistanceStepContext>();
  const navigate = useNavigate();
  const openProfile = useCallback(
    (profileId: string) => {
      void navigate(resistanceStepPath(profileId, "map") ?? RESISTANCE_PATH);
    },
    [navigate],
  );
  if (!isResistanceStepSlug(step)) return null;

  switch (step) {
    case "pathogen":
      return <PathogenInput profile={profile} onProfile={openProfile} />;
    case "map":
      return <ResistanceMap profile={profile} candidates={candidates} />;
    case "candidates":
      return (
        <ResistanceCandidates
          profile={profile}
          candidates={candidates}
          certificates={certificates}
          loading={candidatesLoading}
          onRetry={retryCandidates}
        />
      );
  }
}
