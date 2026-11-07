import { Link } from "react-router";
import type { BuildStage, Experiment } from "../api/types";
import { copy } from "../copy/en";
import styles from "./ExperimentStatus.module.css";
import { EXPLORE_PATH } from "./steps";

const STAGES: readonly BuildStage[] = ["targets", "ranking", "evidence", "saving"];

/** The calm progress shown while an Experiment is queued or building, stage by stage. */
export function BuildProgress({ experiment }: { experiment: Experiment }) {
  const current = experiment.stage === null ? -1 : STAGES.indexOf(experiment.stage);
  return (
    <div className={styles.status}>
      {experiment.status === "queued" && (
        <p className={styles.detail} role="status">
          {copy.experiment.queued}
        </p>
      )}
      <ol className={styles.stages} aria-label={copy.experiment.buildLabel}>
        {STAGES.map((stage, index) => {
          const state = index < current ? "done" : index === current ? "current" : "pending";
          return (
            <li
              key={stage}
              className={styles.stage}
              data-state={state}
              aria-current={state === "current" ? "step" : undefined}
            >
              <span className={styles.marker} aria-hidden="true" />
              {copy.experiment.stages[stage]}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * One line while the rest of an Experiment builds beside what is already drawn: the stage in
 * progress, with the same slowly turning ring as the full list.
 */
export function BuildLine({ experiment }: { experiment: Experiment }) {
  const stage = experiment.stage ?? "targets";
  return (
    <p className={styles.line} role="status">
      <span className={styles.marker} data-state="current" aria-hidden="true" />
      {copy.experiment.stages[stage]}
    </p>
  );
}

/** A build that failed: the API's plain reason, and the way back to choosing a Disease. */
export function BuildFailed({ experiment }: { experiment: Experiment }) {
  return (
    <div className={styles.status} role="alert">
      <p className={styles.headline}>{copy.experiment.failed}</p>
      {experiment.error !== null && <p className={styles.detail}>{experiment.error}</p>}
      <Link to={EXPLORE_PATH} className={styles.action}>
        {copy.experiment.chooseAnother}
      </Link>
    </div>
  );
}

/** The API could not be reached: say so plainly and offer to ask again. */
export function Unavailable({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className={styles.status} role="alert">
      <p className={styles.headline}>{message}</p>
      <button type="button" className={styles.retry} onClick={onRetry}>
        {copy.retry}
      </button>
    </div>
  );
}

export function Loading({ message }: { message: string }) {
  return (
    <div className={styles.status}>
      <p className={styles.detail} role="status">
        {message}
      </p>
    </div>
  );
}
