import { useId, useState } from "react";
import type { Candidate, Experiment } from "../api/types";
import { Panel } from "../app/Figure";
import { useNetworkHover } from "../app/networkHover";
import { candidateHover } from "../app/networkView";
import { SlopeChart, type SlopeRow } from "../charts/SlopeChart";
import { copy, unscorableReasonText, type UnscorableReason } from "../copy/en";
import { byEvidenceRank, byNetworkRank, isPlaced, networkRank } from "../lib/candidates";
import { drugName, listOf } from "../lib/format";
import styles from "./CandidatesStep.module.css";

/** How many drugs show before "Show all". */
export const SHOWN_BY_DEFAULT = 5;

function toRow(candidate: Candidate & { network: NonNullable<Candidate["network"]> }): SlopeRow {
  return {
    id: candidate.candidate_id,
    name: drugName(candidate.name),
    networkRank: networkRank(candidate),
    closeness: candidate.network.degree_matched_z,
    warning: candidate.network.warning,
    evidenceRank: candidate.direct_evidence_rank,
    emphasis: candidate.known_answer,
  };
}

/** Unplaceable drugs grouped by reason, so each reason is said once. */
function byReason(candidates: readonly Candidate[]): [UnscorableReason, string[]][] {
  const groups = new Map<UnscorableReason, string[]>();
  for (const candidate of candidates) {
    if (candidate.unscorable_reason === null) continue;
    const names = groups.get(candidate.unscorable_reason) ?? [];
    names.push(drugName(candidate.name));
    groups.set(candidate.unscorable_reason, names);
  }
  return [...groups];
}

/**
 * Step 3 without a network ranking (ranking_method evidence_only): one list in evidence order,
 * titled with the plan, and one line saying why. No closeness and no network rank: nothing ran.
 */
function EvidenceRanking({ experiment }: { experiment: Experiment }) {
  const [showAll, setShowAll] = useState(false);
  const toggleId = useId();
  const ordered = byEvidenceRank(experiment.candidates);
  const shown = showAll ? ordered : ordered.slice(0, SHOWN_BY_DEFAULT);
  const knownAnswer = experiment.candidates.find((candidate) => candidate.known_answer);

  const toggle =
    ordered.length > SHOWN_BY_DEFAULT ? (
      <label className={styles.toggle} htmlFor={toggleId}>
        <input
          id={toggleId}
          type="checkbox"
          checked={showAll}
          onChange={(event) => {
            setShowAll(event.target.checked);
          }}
        />
        {copy.candidates.showAll(ordered.length)}
      </label>
    ) : undefined;

  return (
    <Panel area="slope" title={copy.candidates.evidenceOnly.title} actions={toggle}>
      <p className={styles.help}>{copy.candidates.evidenceOnly.help}</p>
      <ol className={styles.ranked} aria-label={copy.candidates.evidenceOnly.listLabel}>
        {shown.map((candidate) => (
          <li key={candidate.candidate_id} data-emphasis={candidate.known_answer || undefined}>
            <span className={styles.rank}>
              {candidate.direct_evidence_rank === null ? (
                <span className={styles.quiet}>{copy.candidates.notRanked}</span>
              ) : (
                <>
                  <span className={styles.hidden}>
                    {copy.candidates.evidenceOnly.rank(candidate.direct_evidence_rank)}
                  </span>
                  <span aria-hidden="true">{candidate.direct_evidence_rank}</span>
                </>
              )}
            </span>
            <span className={styles.name}>{drugName(candidate.name)}</span>
          </li>
        ))}
      </ol>
      {knownAnswer && (
        <p className={styles.note}>
          {copy.candidates.knownAnswer(drugName(knownAnswer.name), experiment.disease.name)}
        </p>
      )}
    </Panel>
  );
}

/**
 * Step 3: the shortlist as one slope chart, top five first. Drugs that can't be placed on the
 * network are listed under the chart with the plain reason, and no score.
 */
export function CandidatesStep({ experiment }: { experiment: Experiment }) {
  if (experiment.ranking_method === "evidence_only") {
    return <EvidenceRanking experiment={experiment} />;
  }
  return <NetworkRanking experiment={experiment} />;
}

function NetworkRanking({ experiment }: { experiment: Experiment }) {
  const [showAll, setShowAll] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const setNetworkHover = useNetworkHover();
  const toggleId = useId();

  const { candidates } = experiment;
  const ordered = [...byNetworkRank(candidates), ...candidates.filter((c) => !isPlaced(c))];
  const shown = showAll ? ordered : ordered.slice(0, SHOWN_BY_DEFAULT);
  const rows = shown.filter(isPlaced).map(toRow);
  const unplaced = byReason(shown.filter((candidate) => !isPlaced(candidate)));
  const knownAnswer = candidates.find((candidate) => candidate.known_answer);

  const hover = (id: string | null) => {
    setHovered(id);
    setNetworkHover(id === null ? null : candidateHover(experiment, id));
  };

  const unplacedList =
    unplaced.length > 0 ? (
      <dl className={styles.unplaced}>
        {unplaced.map(([reason, names]) => (
          <div key={reason}>
            <dt>{listOf(names)}</dt>
            <dd>{unscorableReasonText(reason)}</dd>
          </div>
        ))}
      </dl>
    ) : null;

  const toggle =
    candidates.length > SHOWN_BY_DEFAULT ? (
      <label className={styles.toggle} htmlFor={toggleId}>
        <input
          id={toggleId}
          type="checkbox"
          checked={showAll}
          onChange={(event) => {
            setShowAll(event.target.checked);
          }}
        />
        {copy.candidates.showAll(candidates.length)}
      </label>
    ) : undefined;

  return (
    <Panel area="slope" title={copy.candidates.ranking} actions={toggle}>
      {rows.length > 0 ? (
        <SlopeChart
          rows={rows}
          hovered={hovered}
          onHover={hover}
          knownAnswerNote={
            knownAnswer
              ? copy.candidates.knownAnswer(drugName(knownAnswer.name), experiment.disease.name)
              : null
          }
          networkRankNote={
            experiment.ranking_settings.shortlist_method === "physical_rwr"
              ? copy.candidates.randomWalkHelp
              : null
          }
          below={unplacedList}
        />
      ) : (
        unplacedList
      )}
    </Panel>
  );
}
