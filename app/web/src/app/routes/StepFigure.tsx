import { useOutletContext, useParams } from "react-router";
import { hasEarlyResult } from "../../api/queries";
import { isStepSlug } from "../../copy/en";
import { BiologyTargets } from "../../steps/BiologyTargets";
import { CandidatesStep } from "../../steps/CandidatesStep";
import { CompareStep } from "../../steps/CompareStep";
import { DiseaseSearch } from "../../steps/DiseaseSearch";
import { EvidenceStep } from "../../steps/EvidenceStep";
import { HistoryStep } from "../../steps/HistoryStep";
import { JuryStep } from "../../steps/JuryStep";
import { PoseStep } from "../../steps/PoseStep";
import type { StepContext } from "./ExperimentLayout";

/** One step's own panels, placed into the layout's figure grid beside the network. */
export function StepFigure() {
  const { step } = useParams();
  const { experiment } = useOutletContext<StepContext>();
  if (!isStepSlug(step)) return null;

  const ready = experiment?.status === "ready" ? experiment : undefined;
  switch (step) {
    case "disease":
      return <DiseaseSearch current={experiment} />;
    case "biology": {
      // Drawn as soon as the build has saved the Targets, before the drugs are ready.
      const drawn = ready ?? (experiment && hasEarlyResult(experiment) ? experiment : undefined);
      return drawn && <BiologyTargets experiment={drawn} />;
    }
    case "candidates":
      return ready && <CandidatesStep experiment={ready} />;
    case "evidence":
      return ready && <EvidenceStep experiment={ready} />;
    case "jury":
      return ready && <JuryStep experiment={ready} />;
    case "compare":
      return ready && <CompareStep key={ready.id} experiment={ready} />;
    case "pose":
      return ready && <PoseStep key={ready.id} experiment={ready} />;
    case "history":
      return <HistoryStep current={experiment} />;
  }
}
