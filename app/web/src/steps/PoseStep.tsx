import { lazy, Suspense, useId, useState, type ReactNode } from "react";
import { ApiError } from "../api/errors";
import { useDockJob, useRequestDock, useStructures } from "../api/queries";
import type { Candidate, DockJob, Experiment, Structure } from "../api/types";
import { DrugPicker } from "../app/DrugPicker";
import { FigureNote, Panel } from "../app/Figure";
import { copy, stepCopy } from "../copy/en";
import { bestScore, defaultDockingChoice, dockingPairs, jobFor } from "../lib/docking";
import { drugName, signed } from "../lib/format";
import styles from "./PoseStep.module.css";

// 3Dmol.js loads only once a pose is shown.
const PoseViewer = lazy(() =>
  import("../three/PoseViewer").then((module) => ({ default: module.PoseViewer })),
);

const LIVE: readonly DockJob["status"][] = ["queued", "running"];

/** The docking score's axis: typical scores run from about −12 (tight fit) to 0. */
const SCORE_AXIS = { min: -12, max: 0, ticks: [-12, -9, -6, -3, 0] };
/** The redock check's axis, in ångströms. */
const REDOCK_AXIS = { min: 0, max: 3, ticks: [0, 1, 2, 3] };

/**
 * Step 7: an optional binding pose (plan.md §7). The pose takes the stage, with its drug picker
 * and structure line; beside it, in one column, how far to trust it (the docking score, the
 * redock check and the caveat). The picker offers only the drugs that can be docked.
 */
export function PoseStep({ experiment }: { experiment: Experiment }) {
  const structures = useStructures();
  const [picked, setPicked] = useState<string | null>(null);
  const title = stepCopy("pose").title;

  if (structures.isPending) {
    return (
      <Panel area="pose" label={title}>
        {null}
      </Panel>
    );
  }
  if (structures.isError) {
    return (
      <Panel area="pose" label={title}>
        <FigureNote>
          <p role="alert">{copy.pose.unavailable}</p>
          <button type="button" className={styles.retry} onClick={() => void structures.refetch()}>
            {copy.retry}
          </button>
        </FigureNote>
      </Panel>
    );
  }

  const pairs = dockingPairs(experiment.candidates, structures.data);
  const chosenId = picked ?? defaultDockingChoice(pairs);
  const chosen = pairs.find(({ candidate }) => candidate.candidate_id === chosenId);
  if (chosen === undefined) {
    return (
      <Panel area="pose" label={title}>
        <FigureNote>{copy.pose.noneDockable}</FigureNote>
      </Panel>
    );
  }
  return (
    <PairView
      key={chosen.candidate.candidate_id}
      experiment={experiment}
      candidate={chosen.candidate}
      structure={chosen.structure}
      picker={
        <DrugPicker
          label={copy.pose.pick}
          value={chosen.candidate.candidate_id}
          options={pairs.map(({ candidate }) => ({
            id: candidate.candidate_id,
            name: drugName(candidate.name),
          }))}
          onChange={setPicked}
        />
      }
    />
  );
}

interface PairViewProps {
  experiment: Experiment;
  candidate: Candidate;
  structure: Structure;
  picker: ReactNode;
}

/** One drug in one structure: its pose, or the way to one, and the numbers that go with it. */
function PairView({ experiment, candidate, structure, picker }: PairViewProps) {
  const request = useRequestDock(experiment.id);
  const job = jobFor(experiment.dock_jobs, candidate.candidate_id, structure.id);
  const unavailable = request.error instanceof ApiError && request.error.unreachable;
  // With docking down, a saved result for this exact pair still stands: the structure's own
  // redocking control is its crystal drug docked back into it.
  const savedId =
    unavailable && structure.ligand.candidate_id === candidate.candidate_id
      ? structure.control.job_id
      : null;
  const saved = useDockJob(savedId);
  const savedJob = saved.data?.status === "done" ? saved.data : undefined;
  const result = job?.status === "done" ? job : savedJob;
  const name = drugName(candidate.name);

  let body: ReactNode;
  if (result !== undefined) {
    body = (
      <>
        {result === savedJob && (
          <p className={styles.notice} role="status">
            {copy.pose.saved}
          </p>
        )}
        {result.files === null ? (
          <div className={styles.stage}>
            <p className={styles.detail}>{copy.pose.noFiles}</p>
          </div>
        ) : (
          <Suspense fallback={<div className={styles.stage} />}>
            <PoseViewer
              files={result.files}
              label={copy.pose.viewerLabel(name, structure.target_symbol)}
            />
          </Suspense>
        )}
      </>
    );
  } else if (job !== undefined && LIVE.includes(job.status)) {
    body = (
      <div className={styles.stage}>
        <p className={styles.progress} role="status" data-state={job.status}>
          <span className={styles.ring} aria-hidden="true" />
          {job.status === "queued" ? copy.pose.queued : copy.pose.running}
        </p>
      </div>
    );
  } else {
    body = (
      <RequestPose
        experiment={experiment}
        failedJob={job?.status === "failed" ? job : undefined}
        error={request.error}
        pending={request.isPending}
        onRequest={() => {
          request.mutate({ candidateId: candidate.candidate_id, structureId: structure.id });
        }}
      />
    );
  }

  return (
    <>
      <Panel
        area="pose"
        title={
          <span className={styles.heading}>
            {picker}
            <span className={styles.structure}>
              {copy.pose.structure(structure.pdb_id, structure.target_symbol, structure.resolution)}
            </span>
          </span>
        }
      >
        {body}
      </Panel>
      <ScoresPanel structure={structure} result={result} />
    </>
  );
}

interface RequestPoseProps {
  experiment: Experiment;
  failedJob: DockJob | undefined;
  error: Error | null;
  pending: boolean;
  onRequest: () => void;
}

/** No pose yet: one button, or why it can't be pressed, or why the last try failed. */
function RequestPose({ experiment, failedJob, error, pending, onRequest }: RequestPoseProps) {
  const reasonId = useId();
  const archived = experiment.archived_at !== null;
  let refusal: string | null = null;
  if (error instanceof ApiError && error.unreachable) refusal = copy.pose.unavailable;
  else if (error instanceof ApiError && error.detail !== null) refusal = error.detail;
  else if (error !== null) refusal = copy.pose.requestFailed;

  return (
    <div className={styles.stage}>
      <div className={styles.request}>
        {failedJob !== undefined && (
          <div role="alert">
            <p className={styles.headline}>{copy.pose.failed}</p>
            {failedJob.error !== null && <p className={styles.detail}>{failedJob.error}</p>}
          </div>
        )}
        <button
          type="button"
          className={styles.show}
          disabled={archived || pending}
          aria-describedby={archived ? reasonId : undefined}
          onClick={onRequest}
        >
          {failedJob === undefined ? copy.pose.show : copy.retry}
        </button>
        {archived && (
          <p id={reasonId} className={styles.detail}>
            {copy.pose.archived}
          </p>
        )}
        {refusal !== null && (
          <p className={styles.detail} role="alert">
            {refusal}
          </p>
        )}
      </div>
    </div>
  );
}

interface AxisProps {
  min: number;
  max: number;
  ticks: readonly number[];
  value: number;
  /** A threshold marked on the axis, such as the redock check's 2 Å. */
  reference?: number;
  format: (value: number) => string;
}

/** A value's place on a short axis: a dot on a ruled line with a few labelled ticks. */
function Axis({ min, max, ticks, value, reference, format }: AxisProps) {
  const at = (v: number) =>
    `${String(((Math.min(max, Math.max(min, v)) - min) / (max - min)) * 100)}%`;
  return (
    <div className={styles.axis} aria-hidden="true">
      {reference !== undefined && (
        <span className={styles.reference} style={{ left: at(reference) }} />
      )}
      <span className={styles.dot} style={{ left: at(value) }} />
      {ticks.map((tick) => (
        <span key={tick} className={styles.tick} style={{ left: at(tick) }}>
          {format(tick)}
        </span>
      ))}
    </div>
  );
}

interface ScoresPanelProps {
  structure: Structure;
  result: DockJob | undefined;
}

/**
 * The docking score and the redock check, each with what it means, then the caveat. One column
 * that scrolls as a whole when the window is short.
 */
function ScoresPanel({ structure, result }: ScoresPanelProps) {
  const noteId = useId();
  const score = result === undefined ? null : bestScore(result);
  const { control } = structure;
  let shown: "pose" | "score" | null = null;
  if (result !== undefined && score !== null) shown = result.files === null ? "score" : "pose";
  const fixture = copy.pose.fixture(
    result?.fixture === true ? shown : null,
    control.fixture && control.rmsd !== null,
  );
  const describedBy = fixture === null ? undefined : noteId;

  return (
    <Panel area="scores">
      <div className={styles.column}>
        <section className={styles.scores} aria-label={copy.pose.scoresLabel}>
          {result !== undefined && score !== null && (
            <section className={styles.measure} aria-labelledby={`${noteId}-score`}>
              <div className={styles.measureHead}>
                <h3 id={`${noteId}-score`} className={styles.label}>
                  {copy.pose.score}
                </h3>
                <p className={styles.reading}>
                  <span
                    className={styles.value}
                    data-fixture={result.fixture || undefined}
                    aria-describedby={result.fixture ? describedBy : undefined}
                  >
                    {signed(score)}
                  </span>
                </p>
              </div>
              <Axis {...SCORE_AXIS} value={score} format={(tick) => signed(tick, 0)} />
              <p className={styles.help}>{copy.pose.scoreHelp}</p>
            </section>
          )}
          <section className={styles.measure} aria-labelledby={`${noteId}-redock`}>
            <div className={styles.measureHead}>
              <h3 id={`${noteId}-redock`} className={styles.label}>
                {copy.pose.redock}
              </h3>
              {control.rmsd === null ? (
                <p className={styles.missing}>{copy.pose.redockStatus.not_measured}</p>
              ) : (
                <p className={styles.reading}>
                  <span className={styles.status}>{copy.pose.redockStatus[control.status]}</span>
                  <span
                    className={styles.value}
                    data-fixture={control.fixture || undefined}
                    aria-describedby={control.fixture ? describedBy : undefined}
                  >
                    {control.rmsd.toFixed(2)}
                    <small> Å</small>
                  </span>
                </p>
              )}
            </div>
            {control.rmsd !== null && (
              <Axis
                {...REDOCK_AXIS}
                value={control.rmsd}
                reference={control.success_threshold}
                format={(tick) => (tick === 0 ? "0" : `${String(tick)} Å`)}
              />
            )}
            <p className={styles.help}>{copy.pose.redockHelp(control.success_threshold)}</p>
          </section>
          {fixture !== null && (
            <p id={noteId} className={styles.fixture}>
              {fixture}
            </p>
          )}
          <p className={styles.caveat}>{copy.pose.caveat}</p>
        </section>
      </div>
    </Panel>
  );
}
