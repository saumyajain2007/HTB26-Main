import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Outlet, useParams, useSearchParams } from "react-router";
import { ApiError } from "../../api/errors";
import { hasEarlyResult, isBuilding, useExperiment, useStartFollowUps } from "../../api/queries";
import type { Experiment } from "../../api/types";
import { copy, isStepSlug, type StepSlug } from "../../copy/en";
import { DRUG_PARAM } from "../../steps/EvidenceStep";
import { BuildFailed, BuildProgress, Loading, Unavailable } from "../ExperimentStatus";
import { FigureGrid, type FigureLayout } from "../Figure";
import { NetworkHoverContext, type NetworkHover } from "../networkHover";
import { NetworkPanel } from "../NetworkPanel";
import { NETWORK_STEPS, networkView } from "../networkView";
import { Shell } from "../Shell";
import { MessagePage } from "./MessagePage";
import { NotFoundPage } from "./NotFoundPage";

/** What each step's figure receives from the layout. */
export interface StepContext {
  experiment: Experiment | undefined;
}

/** Steps whose figure needs a ready Experiment; until then they show its build state. */
const RESULT_STEPS: readonly StepSlug[] = [
  "biology",
  "candidates",
  "evidence",
  "jury",
  "compare",
  "pose",
];

const LAYOUTS: Partial<Record<StepSlug, FigureLayout>> = {
  disease: "search",
  biology: "biology",
  candidates: "candidates",
  evidence: "evidence",
};

/**
 * `/e/:experimentId/:step`: loads the Experiment once for every step and keeps it polled while
 * it builds. The figure grid and the protein network live here, not in the steps, so the network
 * is mounted once and survives step changes; each step only adds its own panels (the outlet) and
 * tells the network what to point at.
 */
export function ExperimentLayout() {
  const { experimentId, step } = useParams();
  if (experimentId === undefined || !isStepSlug(step)) return <NotFoundPage />;
  return <ExperimentScreen experimentId={experimentId} step={step} />;
}

function ExperimentScreen({ experimentId, step }: { experimentId: string; step: StepSlug }) {
  const query = useExperiment(experimentId);
  const [params] = useSearchParams();
  const focusId = params.get(DRUG_PARAM);

  // A hover belongs to the step it happened on, so it clears itself when the step changes.
  const [hover, setHoverState] = useState<{ step: StepSlug; hover: NetworkHover } | null>(null);
  const setHover = useCallback(
    (next: NetworkHover | null) => {
      setHoverState(next === null ? null : { step, hover: next });
    },
    [step],
  );
  const activeHover = hover?.step === step ? hover.hover : null;

  const experiment = query.data;

  // Once the reader moves past choosing the Disease, start the slow work the later steps show
  // (the jury, the binding poses), so it is under way while they read. Not on step 1, where they
  // may try several Diseases. Once per Experiment; asking again would start nothing new anyway.
  const { mutate: startFollowUps } = useStartFollowUps();
  const followedUp = useRef<string | null>(null);
  const followable =
    step !== "disease" && experiment?.status === "ready" && experiment.archived_at === null;
  useEffect(() => {
    if (!followable || followedUp.current === experimentId) return;
    followedUp.current = experimentId;
    startFollowUps(experimentId);
  }, [followable, experimentId, startFollowUps]);

  const view = useMemo(
    () => (experiment ? networkView(step, experiment, focusId, activeHover) : null),
    [step, experiment, focusId, activeHover],
  );

  const error = query.error;
  if (error instanceof ApiError && (error.status === 404 || error.status === 422)) {
    return <MessagePage {...copy.experiment.notFound} />;
  }

  // The Disease is named once per screen: in the header, except on the step that lists Diseases.
  const disease =
    experiment !== undefined && step !== "disease" && step !== "history"
      ? experiment.disease.name
      : undefined;
  const ready = experiment?.status === "ready";
  // What is already drawable: the whole Experiment, or its Targets and network mid-build.
  const drawable = ready || (experiment !== undefined && hasEarlyResult(experiment));
  const early = drawable && !ready && step === "biology";
  const retry = () => void query.refetch();

  let figure;
  if (RESULT_STEPS.includes(step) && !ready && !early) {
    if (experiment === undefined) {
      figure = error ? (
        <Unavailable message={copy.experiment.unavailable} onRetry={retry} />
      ) : (
        <Loading message={copy.experiment.loading} />
      );
    } else if (isBuilding(experiment)) {
      figure = <BuildProgress experiment={experiment} />;
    } else {
      figure = <BuildFailed experiment={experiment} />;
    }
  } else {
    const showsNetwork = drawable && NETWORK_STEPS.includes(step);
    figure = (
      <FigureGrid
        layout={(showsNetwork ? LAYOUTS[step] : undefined) ?? fallbackLayout(step, experiment)}
        network={!drawable || experiment.network !== null}
      >
        <NetworkHoverContext.Provider value={setHover}>
          <Outlet context={{ experiment } satisfies StepContext} />
        </NetworkHoverContext.Provider>
        {drawable && view !== null && (
          <NetworkPanel
            experiment={experiment}
            step={step}
            view={view}
            focusId={focusId}
            hidden={!showsNetwork}
          />
        )}
      </FigureGrid>
    );
  }

  return (
    <Shell step={step} experimentId={experimentId} disease={disease}>
      {figure}
    </Shell>
  );
}

function fallbackLayout(step: StepSlug, experiment: Experiment | undefined): FigureLayout {
  if (step === "disease") return "search";
  // The jury's result is its ballot board and a reading pane; asking it and its progress are one.
  if (step === "jury" && experiment?.jury?.status === "done") return "jury";
  // The pose takes the stage; the network stays hidden, so it costs no drawing.
  if (step === "pose") return "pose";
  return "single";
}
