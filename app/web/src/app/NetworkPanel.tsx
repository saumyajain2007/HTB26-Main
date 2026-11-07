import { lazy, Suspense } from "react";
import type { Experiment } from "../api/types";
import { copy, unscorableReasonText, type StepSlug } from "../copy/en";
import { focusCandidate, routeSentence } from "../lib/candidates";
import type { NetworkView } from "../three/NetworkFigure";
import { Panel } from "./Figure";
import { Legend, type LegendKey } from "./Legend";
import styles from "./NetworkPanel.module.css";

interface NetworkPanelProps {
  experiment: Experiment;
  step: StepSlug;
  view: NetworkView;
  focusId: string | null;
  hidden: boolean;
}

// Three.js loads only once a figure needs it, so the first screen stays light.
const NetworkFigure = lazy(() =>
  import("../three/NetworkFigure").then((module) => ({ default: module.NetworkFigure })),
);

function legendFor(step: StepSlug, view: NetworkView): LegendKey[] {
  if (view.mode === "path") return ["disease", "drug", "path"];
  if (view.mode === "roles") return ["disease", "drug", "both"];
  return step === "biology" ? ["disease", "link"] : ["disease"];
}

/**
 * The panel holding the persistent network. On the Evidence step it also says, once, why the
 * focus drug sits where it does: its route to a disease protein, or why it has none.
 */
export function NetworkPanel({ experiment, step, view, focusId, hidden }: NetworkPanelProps) {
  const graph = experiment.network;
  if (graph === null) return null;
  const empty = graph.nodes.length === 0;

  let title: string | undefined;
  let lede: string | null = null;
  if (step === "evidence") {
    const candidate = focusCandidate(experiment.candidates, focusId);
    if (candidate?.network) {
      // "Why it ranks high" only for a drug the network ranking put on the shortlist; one
      // chosen for its direct evidence (or with no closeness) just has a route.
      const rankedHigh = candidate.status === "scored" && candidate.selected_by.includes("network");
      title = rankedHigh ? copy.evidence.pathTitle : copy.evidence.routeTitle;
      lede = routeSentence(candidate, graph);
    } else if (candidate?.unscorable_reason) {
      title = copy.evidence.noRouteTitle;
      lede = unscorableReasonText(candidate.unscorable_reason);
    }
  }

  // Keep the network mounted across steps without capturing the page's live WebGL canvases.
  return (
    <Panel area="net" hidden={hidden} title={title} label={copy.network.title}>
      {lede !== null && <p className={styles.lede}>{lede}</p>}
      {(!empty || step === "biology") && (
        <Suspense fallback={<div className={styles.loading} />}>
          <NetworkFigure graph={graph} view={view} />
        </Suspense>
      )}
      {!empty && <Legend keys={legendFor(step, view)} />}
    </Panel>
  );
}
