import type { Experiment } from "../api/types";
import type { StepSlug } from "../copy/en";
import { drawnTargets, focusCandidate } from "../lib/candidates";
import { drugName } from "../lib/format";
import type { NetworkView } from "../three/NetworkFigure";
import type { NetworkHover } from "./networkHover";

/** Steps whose figure includes the persistent protein network. */
export const NETWORK_STEPS: readonly StepSlug[] = ["disease", "biology", "candidates", "evidence"];

const NEUTRAL: NetworkView = {
  mode: "disease",
  highlight: null,
  focus: null,
  route: null,
  drug: null,
};

/**
 * What the network shows on each step (docs/engineering/design.md: each step highlights only what it is
 * about): disease proteins on steps 1 and 2, the candidates' targets on step 3, and the route
 * from the focus drug to a disease protein on the evidence step. A hovered row narrows that emphasis.
 */
export function networkView(
  step: StepSlug,
  experiment: Experiment,
  focusId: string | null,
  hover: NetworkHover | null,
): NetworkView {
  const graph = experiment.network;
  if (graph === null) return NEUTRAL;
  const diseaseIds = graph.nodes
    .filter((node) => node.role === "disease" || node.role === "both")
    .map((node) => node.id);

  switch (step) {
    case "biology":
      return hover ? { ...NEUTRAL, highlight: hover.highlight, focus: hover.focus } : NEUTRAL;
    case "candidates": {
      if (hover) {
        return { ...NEUTRAL, mode: "roles", highlight: hover.highlight, focus: hover.focus };
      }
      const targets = experiment.candidates.flatMap((candidate) => drawnTargets(candidate, graph));
      return { ...NEUTRAL, mode: "roles", highlight: [...new Set([...diseaseIds, ...targets])] };
    }
    case "evidence": {
      const candidate = focusCandidate(experiment.candidates, focusId);
      if (candidate?.network == null) return NEUTRAL;
      const targets = drawnTargets(candidate, graph);
      const route = candidate.network.path;
      return {
        mode: "path",
        highlight: [...new Set([...route, ...targets])],
        focus: route,
        route,
        drug: { label: drugName(candidate.name), targets },
      };
    }
    default:
      return NEUTRAL;
  }
}

/** The disease proteins plus one drug's targets: what hovering that drug points at. */
export function candidateHover(experiment: Experiment, candidateId: string): NetworkHover | null {
  const graph = experiment.network;
  const candidate = experiment.candidates.find((c) => c.candidate_id === candidateId);
  if (graph === null || candidate === undefined) return null;
  const targets = drawnTargets(candidate, graph);
  const diseaseIds = graph.nodes
    .filter((node) => node.role === "disease" || node.role === "both")
    .map((node) => node.id);
  return { highlight: [...new Set([...diseaseIds, ...targets])], focus: targets };
}
