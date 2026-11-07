import { useQueries } from "@tanstack/react-query";
import { type CSSProperties, lazy, Suspense, useState, type ReactNode } from "react";
import { conformerQuery, useStructures } from "../api/queries";
import type { Candidate, Conformer, DockJob, Experiment, JuryRun, Structure } from "../api/types";
import { DrugPicker } from "../app/DrugPicker";
import { FigureNote, Panel } from "../app/Figure";
import { Marker } from "../charts/Marker";
import { copy, stepCopy } from "../copy/en";
import {
  approvals,
  comparableDrugs,
  defaultPicks,
  isPlaced,
  type ModelState,
  networkRank,
  warningSentence,
} from "../lib/candidates";
import { structureFor } from "../lib/docking";
import { drugName, listOf } from "../lib/format";
import { decisionsFor } from "../lib/jury";
import type { StripItem } from "../three/MoleculeStrip";
import styles from "./CompareStep.module.css";

/** How many of a drug's targets are named before "and N more". */
const TARGETS_SHOWN = 4;

const MoleculeStrip = lazy(() =>
  import("../three/MoleculeStrip").then((module) => ({ default: module.MoleculeStrip })),
);

const LIVE: readonly DockJob["status"][] = ["queued", "running"];

/** Whether a binding pose exists, is being computed, could be computed, or can't be. */
function poseText(
  candidate: Candidate,
  jobs: readonly DockJob[],
  structures: readonly Structure[] | undefined,
): string | null {
  const own = jobs.filter(
    (job) => job.kind === "candidate" && job.candidate_id === candidate.candidate_id,
  );
  const symbol = (targetId: string, structureId?: string) =>
    structures?.find((s) => s.id === structureId)?.target_symbol ??
    candidate.targets.find((target) => target.id === targetId)?.name ??
    targetId;
  const done = own.find((job) => job.status === "done");
  if (done) return copy.compare.pose.done(symbol(done.target_id, done.structure_id));
  const live = own.find((job) => LIVE.includes(job.status));
  if (live) return copy.compare.pose.running(symbol(live.target_id, live.structure_id));
  if (!candidate.dockable) return copy.compare.pose.unavailable;
  if (structures === undefined) return null;
  const structure = structureFor(candidate, structures);
  return structure
    ? copy.compare.pose.possible(structure.target_symbol)
    : copy.compare.pose.unavailable;
}

function targetsText(candidate: Candidate): string {
  const names = candidate.targets.map((target) => target.name);
  if (names.length === 0) return copy.compare.none;
  if (names.length <= TARGETS_SHOWN) return listOf(names);
  return copy.compare.moreTargets(
    names.slice(0, TARGETS_SHOWN).join(", "),
    names.length - TARGETS_SHOWN,
  );
}

function rank(value: number | null | undefined): ReactNode {
  return value ?? <span className={styles.quiet}>{copy.candidates.notRanked}</span>;
}

/** The jury's decision: one word when the models agree, each model's word when they split. */
function Decision({ jury, candidateId }: { jury: JuryRun; candidateId: string }) {
  const decisions = decisionsFor(jury, candidateId);
  const first = decisions[0];
  if (first === undefined) return <span className={styles.quiet}>{copy.compare.none}</span>;
  if (decisions.every((entry) => entry.decision === first.decision)) {
    return (
      <span className={styles.decision} data-decision={first.decision}>
        {copy.jury.decisions[first.decision]}
      </span>
    );
  }
  return (
    <div className={styles.split}>
      <span className={styles.splitTitle}>
        <span className={styles.swatch} aria-hidden="true" />
        {copy.jury.contestedTitle}
      </span>
      <ul className={styles.splitList}>
        {decisions.map(({ juror, decision }) => (
          <li key={juror.model.id}>
            <Marker index={juror.marker} />
            <span className={styles.hidden}>{juror.model.display_name}: </span>
            <span className={styles.decision} data-decision={decision}>
              {copy.jury.decisions[decision]}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Each drug's 3D model, asked for once per PubChem compound (React Query caches them, so other
 * steps and later visits reuse the answers), and what is known of it.
 */
function useModels(candidates: readonly Candidate[]) {
  const cids = [...new Set(candidates.flatMap((candidate) => candidate.pubchem_cid ?? []))];
  const queries = useQueries({ queries: cids.map((cid) => conformerQuery(cid)) });
  const byCid = new Map(cids.map((cid, index) => [cid, queries[index]]));
  const queryOf = ({ pubchem_cid }: Candidate) =>
    pubchem_cid === null ? undefined : byCid.get(pubchem_cid);
  const conformerOf = (candidate: Candidate): Conformer | undefined =>
    queryOf(candidate)?.data ?? undefined;
  const modelOf = (candidate: Candidate): ModelState => {
    const query = queryOf(candidate);
    // No PubChem compound (antibodies), or PubChem has no 3D conformer for it (the API's 404).
    if (query === undefined || query.data === null) return "none";
    if (query.data !== undefined) return "model";
    return query.isError ? "failed" : "pending";
  };
  return { conformerOf, modelOf };
}

/**
 * Step 6: up to three drugs side by side, each swappable for another on this Experiment's
 * shortlist. Only drugs with a 3D model take part: the others are left out entirely. Each row is
 * labelled once, on the left; the molecules share one canvas, so the step costs a single WebGL
 * context however many columns it draws.
 */
export function CompareStep({ experiment }: { experiment: Experiment }) {
  const { candidates } = experiment;
  const { conformerOf, modelOf } = useModels(candidates);
  const offered = comparableDrugs(candidates, modelOf);
  const title = stepCopy("compare").title;

  // Until every drug's model is known the panel stays empty, as the molecules do while they load.
  if (offered === undefined) {
    return (
      <Panel area="main" label={title}>
        {null}
      </Panel>
    );
  }
  if (offered.length === 0) {
    return (
      <Panel area="main" label={title}>
        <FigureNote>{copy.compare.noModels}</FigureNote>
      </Panel>
    );
  }
  return (
    <CompareTable
      experiment={experiment}
      offered={offered}
      defaults={defaultPicks(candidates, modelOf)}
      conformerOf={conformerOf}
    />
  );
}

interface CompareTableProps {
  experiment: Experiment;
  /** The drugs that can be compared, in shortlist order. */
  offered: readonly Candidate[];
  /** The drugs shown until the reader picks others. */
  defaults: readonly string[];
  conformerOf: (candidate: Candidate) => Conformer | undefined;
}

function CompareTable({ experiment, offered, defaults, conformerOf }: CompareTableProps) {
  const { jury } = experiment;
  const [choice, setChoice] = useState<readonly string[] | null>(null);
  const structures = useStructures();
  const picks = choice ?? defaults;
  const chosen = picks.flatMap((id) => offered.find((c) => c.candidate_id === id) ?? []);

  // Every drug here has a model or failed to load one; the strip draws the first and says so of
  // the second.
  const items: StripItem[] = chosen.map((candidate) => {
    const name = drugName(candidate.name);
    const conformer = conformerOf(candidate);
    return conformer
      ? { key: candidate.candidate_id, name, conformer }
      : { key: candidate.candidate_id, name, message: copy.evidence.modelUnavailable };
  });

  // With no network ranking, the network-rank row says "not ranked" once, across every drug.
  const networkRanked = experiment.ranking_method === "network";
  const rows: {
    label: string;
    cell: (candidate: Candidate) => ReactNode;
    whole?: ReactNode;
  }[] = [
    {
      label: copy.candidates.networkRank,
      cell: (c) => rank(isPlaced(c) ? networkRank(c) : null),
      whole: networkRanked ? undefined : (
        <span className={styles.quiet}>{copy.candidates.notRanked}</span>
      ),
    },
    { label: copy.candidates.evidenceRank, cell: (c) => rank(c.direct_evidence_rank) },
    ...(jury?.status === "done"
      ? [
          {
            label: copy.compare.decision,
            cell: (c: Candidate) => <Decision jury={jury} candidateId={c.candidate_id} />,
          },
        ]
      : []),
    { label: copy.compare.targets, cell: targetsText },
    {
      label: copy.compare.approval,
      cell: (c) => {
        const lines = approvals(c);
        return lines.length > 0 ? (
          lines.join(" ")
        ) : (
          <span className={styles.quiet}>{copy.compare.notRecorded}</span>
        );
      },
    },
    {
      label: copy.evidence.warningTitle,
      cell: (c) =>
        warningSentence(c) ?? <span className={styles.quiet}>{copy.compare.noWarnings}</span>,
    },
    {
      label: copy.compare.dockable,
      cell: (c) => poseText(c, experiment.dock_jobs, structures.data),
    },
  ];

  const pick = (column: number, id: string) => {
    setChoice(chosen.map((candidate, index) => (index === column ? id : candidate.candidate_id)));
  };

  return (
    <Panel area="main" label={stepCopy("compare").title}>
      <div
        role="table"
        aria-label={copy.compare.tableLabel}
        className={styles.table}
        style={{ "--drugs": chosen.length } as CSSProperties}
      >
        <div role="row" className={styles.head}>
          <span role="columnheader" className={styles.corner}>
            <span className={styles.hidden}>{copy.compare.rowsHeader}</span>
          </span>
          {chosen.map((candidate, column) => (
            <span role="columnheader" key={column} className={styles.pick}>
              <DrugPicker
                label={copy.compare.pick}
                value={candidate.candidate_id}
                options={offered.map((option) => ({
                  id: option.candidate_id,
                  name: drugName(option.name),
                  disabled:
                    option.candidate_id !== candidate.candidate_id && chosen.includes(option),
                }))}
                onChange={(id) => {
                  pick(column, id);
                }}
              />
            </span>
          ))}
        </div>
        {/* A table may only contain rows, so the molecule band is a row with one cell spanning
            every column; the 3D molecules inside stay reachable and draggable. */}
        <div className={styles.band} role="row">
          <div role="cell" aria-colspan={chosen.length + 1} className={styles.bandCell}>
            <Suspense fallback={null}>
              <MoleculeStrip items={items} />
            </Suspense>
          </div>
        </div>
        {rows.map((row) => (
          <div role="row" key={row.label} className={styles.row}>
            <span role="rowheader" className={styles.label}>
              {row.label}
            </span>
            {row.whole === undefined ? (
              chosen.map((candidate) => (
                <span role="cell" key={candidate.candidate_id} className={styles.cell}>
                  {row.cell(candidate)}
                </span>
              ))
            ) : (
              <span role="cell" className={styles.cell} data-whole="true">
                {row.whole}
              </span>
            )}
          </div>
        ))}
      </div>
    </Panel>
  );
}
