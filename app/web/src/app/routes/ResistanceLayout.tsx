import { Outlet, useParams } from "react-router";
import { ApiError } from "../../api/errors";
import { copy, isResistanceStepSlug, type ResistanceStepSlug } from "../../copy/en";
import {
  useAntibioticCandidates,
  useResistanceProfile,
  type AntibioticCandidateResult,
  type ResistanceProfile,
} from "../../lib/resistance";
import { Loading, Unavailable } from "../ExperimentStatus";
import { FigureGrid } from "../Figure";
import { ResistanceShell } from "../Shell";
import { RESISTANCE_PATH } from "../steps";
import { MessagePage } from "./MessagePage";
import { NotFoundPage } from "./NotFoundPage";

/** What each resistance step's figure receives from the layout. */
export interface ResistanceStepContext {
  profile: ResistanceProfile;
  /** The ranked candidates, or undefined while they load or if they could not be loaded. */
  candidates: AntibioticCandidateResult | undefined;
  candidatesLoading: boolean;
  retryCandidates: () => void;
}

/**
 * `/resistance/:profileId/:step`: loads the profile once for every step, and the candidates
 * ranked against it alongside, so a step that needs both does not wait twice. The figure grid
 * lives here, not in the steps; each step only adds its own panels.
 */
export function ResistanceLayout() {
  const { profileId, step } = useParams();
  if (profileId === undefined || !isResistanceStepSlug(step)) return <NotFoundPage />;
  return <ResistanceScreen profileId={profileId} step={step} />;
}

function ResistanceScreen({ profileId, step }: { profileId: string; step: ResistanceStepSlug }) {
  const query = useResistanceProfile(profileId);
  const candidates = useAntibioticCandidates(profileId);
  const profile = query.data;
  const error = query.error;

  if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
    return <MessagePage {...copy.resistance.notFound} homePath={RESISTANCE_PATH} />;
  }

  // The pathogen is named once per screen: in the header, except on the step that chooses it.
  const pathogen =
    profile !== undefined && step !== "pathogen" ? profile.input.species.name : undefined;
  const retry = () => void query.refetch();

  return (
    <ResistanceShell step={step} profileId={profileId} pathogen={pathogen}>
      {profile === undefined ? (
        error ? (
          <Unavailable message={copy.resistance.unavailable} onRetry={retry} />
        ) : (
          <Loading message={copy.resistance.loading} />
        )
      ) : (
        <FigureGrid layout="single">
          <Outlet
            context={
              {
                profile,
                candidates: candidates.data,
                candidatesLoading: candidates.isPending,
                retryCandidates: () => void candidates.refetch(),
              } satisfies ResistanceStepContext
            }
          />
        </FigureGrid>
      )}
    </ResistanceShell>
  );
}
