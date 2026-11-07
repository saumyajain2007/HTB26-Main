import type { Candidate, EvidenceItem, NetworkGraph } from "../api/types";
import { copy } from "../copy/en";
import { capitalise, drugName, listOf } from "./format";

/** A Candidate that has a place in the protein network: scored or distance_only. */
export type PlacedCandidate = Candidate & { network: NonNullable<Candidate["network"]> };

export function isPlaced(candidate: Candidate): candidate is PlacedCandidate {
  return candidate.network !== null;
}

/**
 * A placed Candidate's network rank: its random-walk rank when the Experiment's shortlist came
 * from the random walk (ranking_settings.shortlist_method physical_rwr, the only time `rwr` is
 * set), else its closeness rank.
 */
export function networkRank(candidate: PlacedCandidate): number {
  return candidate.network.rwr?.rank ?? candidate.network.rank;
}

/** Placed Candidates in network-rank order; scored ones always rank before distance_only ones. */
export function byNetworkRank(candidates: readonly Candidate[]): PlacedCandidate[] {
  return candidates.filter(isPlaced).sort((a, b) => networkRank(a) - networkRank(b));
}

/**
 * The Candidate the Evidence step is about: the one asked for, else the known-answer check, else
 * the top of the shortlist.
 */
export function focusCandidate(
  candidates: readonly Candidate[],
  preferredId?: string | null,
): Candidate | undefined {
  return (
    candidates.find((candidate) => candidate.candidate_id === preferredId) ??
    candidates.find((candidate) => candidate.known_answer) ??
    candidates[0]
  );
}

/** Protein IDs a Candidate acts on that are drawn in the network. */
export function drawnTargets(candidate: Candidate, graph: NetworkGraph): string[] {
  const drawn = new Set(graph.nodes.map((node) => node.id));
  return candidate.targets.map((target) => target.id).filter((id) => drawn.has(id));
}

/**
 * The route from a Candidate to the Disease in plain words, naming each protein by its symbol.
 * Null when the Candidate has no place in the network.
 */
export function routeSentence(candidate: Candidate, graph: NetworkGraph): string | null {
  if (candidate.network === null) return null;
  const symbols = new Map(graph.nodes.map((node) => [node.id, node.symbol]));
  const names = candidate.network.path.map((id) => symbols.get(id) ?? id);
  const drug = drugName(candidate.name);
  const [first, ...rest] = names;
  if (first === undefined) return null;
  const last = rest.at(-1);
  if (last === undefined) return copy.evidence.route.self(drug, first);
  const through = rest.slice(0, -1);
  if (through.length === 0) return copy.evidence.route.direct(drug, first, last);
  return copy.evidence.route.via(drug, first, last, listOf(through));
}

/**
 * The proteins of a network-route evidence item, in order (its `source_id` is the route's IDs
 * joined by ">", then "@" and the network's hash). Null for any other kind of item.
 */
export function routeOf(item: EvidenceItem): string[] | null {
  if (item.kind !== "network_path") return null;
  return item.source_id.split("@")[0]?.split(">") ?? null;
}

/**
 * The facts the Evidence step lists for a Candidate: every item except its label warnings (said
 * in the warning box) and the route the network panel already describes in words.
 */
export function listedEvidence(candidate: Candidate, graph: NetworkGraph | null): EvidenceItem[] {
  const shown = graph === null ? null : (candidate.network?.path.join(">") ?? null);
  return candidate.evidence.filter(
    (item) => item.kind !== "warning" && (shown === null || routeOf(item)?.join(">") !== shown),
  );
}

/**
 * The label risks as one plain sentence, from each cited warning's summary, e.g. "Serious
 * infections, cancer and lung problems." Null when no warning is recorded.
 */
export function warningSentence(candidate: Candidate): string | null {
  const byId = new Map(candidate.evidence.map((item) => [item.id, item]));
  const risks: string[] = [];
  for (const warning of candidate.warnings) {
    const summary = byId.get(warning.evidence_id)?.summary.replace(/\.$/, "");
    if (summary === undefined) continue;
    const risk = summary.charAt(0).toLowerCase() + summary.slice(1);
    if (!risks.includes(risk)) risks.push(risk);
  }
  return risks.length === 0 ? null : `${capitalise(listOf(risks))}.`;
}

/** What the regulators' approval records say, e.g. "Approved by the US regulator (FDA)." */
export function approvals(candidate: Candidate): string[] {
  return [
    ...new Set(
      candidate.evidence.filter((item) => item.kind === "approval").map((item) => item.summary),
    ),
  ];
}

/** How many drugs the Compare step puts side by side. */
export const COMPARED = 3;

/**
 * What is known of a drug's 3D model: it loaded, there is none (no PubChem compound, or PubChem
 * has no 3D conformer), the answer is still coming, or the model couldn't be asked for.
 */
export type ModelState = "model" | "none" | "pending" | "failed";

/**
 * The drugs the Compare step offers, in shortlist order: those with a 3D model, and those whose
 * model couldn't be loaded, since a failure doesn't show there is none. Undefined while any
 * answer is pending, so no drug is offered that may disappear a moment later.
 */
export function comparableDrugs(
  candidates: readonly Candidate[],
  modelOf: (candidate: Candidate) => ModelState,
): Candidate[] | undefined {
  const states = new Map(candidates.map((candidate) => [candidate, modelOf(candidate)]));
  if ([...states.values()].includes("pending")) return undefined;
  return candidates.filter((candidate) => states.get(candidate) !== "none");
}

/**
 * The drugs compared first: the known-answer drug and the ones after it on the shortlist (or the
 * top of the shortlist when there is no known answer), keeping to drugs with a 3D model. Drugs
 * whose model couldn't be loaded only fill columns no modelled drug can.
 */
export function defaultPicks(
  candidates: readonly Candidate[],
  modelOf: (candidate: Candidate) => ModelState,
): string[] {
  const start = Math.max(
    0,
    candidates.findIndex((candidate) => candidate.known_answer),
  );
  const order = [...candidates.slice(start), ...candidates.slice(0, start)];
  const inState = (state: ModelState) => order.filter((candidate) => modelOf(candidate) === state);
  return [...inState("model"), ...inState("failed")]
    .slice(0, COMPARED)
    .map((candidate) => candidate.candidate_id);
}

/**
 * Whether the drug is known to be an antibody: its name carries the INN stem for monoclonal
 * antibodies ("-mab"), or its records say so. A missing PubChem compound alone doesn't tell:
 * some small molecules have none in the data.
 */
export function isAntibody(candidate: Candidate): boolean {
  if (/mab$/i.test(candidate.name.trim())) return true;
  return candidate.evidence.some((item) => /\bantibod(y|ies)\b/i.test(item.statement));
}

/** Candidates in direct-evidence order; drugs without an evidence rank keep shortlist order last. */
export function byEvidenceRank(candidates: readonly Candidate[]): Candidate[] {
  const rank = (candidate: Candidate) => candidate.direct_evidence_rank ?? Number.POSITIVE_INFINITY;
  return [...candidates].sort((a, b) => rank(a) - rank(b) || a.shortlist_rank - b.shortlist_rank);
}

/** Why no 3D model of the drug is shown: the antibody wording only when it is known to be one. */
export function noModelText(candidate: Candidate): string {
  return isAntibody(candidate) ? copy.evidence.noModel : copy.evidence.noModelNeutral;
}
