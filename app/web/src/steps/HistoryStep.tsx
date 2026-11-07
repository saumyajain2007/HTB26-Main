import { useState } from "react";
import { Link } from "react-router";
import { ApiError } from "../api/errors";
import { useArchive, useHistory } from "../api/queries";
import type { Experiment, ExperimentSummary } from "../api/types";
import { Unavailable } from "../app/ExperimentStatus";
import { FigureNote, Panel } from "../app/Figure";
import { stepPath } from "../app/steps";
import { copy, stepCopy } from "../copy/en";
import { dateTime, releaseName } from "../lib/format";
import styles from "./HistoryStep.module.css";

type View = "active" | "archived";

/** The API's plain reason for a refusal (e.g. docking still running), else a plain line. */
function failureText(error: Error): string {
  if (error instanceof ApiError && !error.unreachable && error.detail !== null) return error.detail;
  return copy.history.actionFailed;
}

function dataLine(item: ExperimentSummary): string {
  return copy.history.data(item.data_releases.map(releaseName));
}

/**
 * Step 8, History: saved experiments, newest first, with archived ones one switch away. Archiving hides
 * an experiment from the saved list and keeps it whole; Restore brings it back. When every
 * listed experiment used the same data, the data line is said once, under the list.
 */
export function HistoryStep({ current }: { current: Experiment | undefined }) {
  const [chosen, setChosen] = useState<View | null>(null);
  const [failure, setFailure] = useState<{ id: string; message: string } | null>(null);
  // The list opens where the open experiment is, once it has loaded. Archiving it afterwards
  // keeps the reader on the saved list, where they just watched it leave.
  const [opening, setOpening] = useState<View | null>(null);
  if (opening === null && current !== undefined) {
    setOpening(current.archived_at === null ? "active" : "archived");
  }
  const view: View = chosen ?? opening ?? "active";
  const lists = { active: useHistory(false), archived: useHistory(true) };
  const list = lists[view];
  const action = useArchive();

  const items = list.data ?? [];
  const lines = new Set(items.map(dataLine));
  const shared = lines.size === 1 ? [...lines][0] : undefined;

  const run = (item: ExperimentSummary) => {
    setFailure(null);
    action.mutate(
      { id: item.id, archive: item.archived_at === null },
      {
        onError: (error) => {
          setFailure({ id: item.id, message: failureText(error) });
        },
      },
    );
  };

  let body;
  if (list.isError && list.data === undefined) {
    body = <Unavailable message={copy.history.unavailable} onRetry={() => void list.refetch()} />;
  } else if (list.data === undefined) {
    body = (
      <FigureNote>
        <p role="status">{copy.history.loading}</p>
      </FigureNote>
    );
  } else if (items.length === 0) {
    body = (
      <FigureNote>
        <p>{view === "active" ? copy.history.emptyActive : copy.history.emptyArchived}</p>
      </FigureNote>
    );
  } else {
    body = (
      <>
        <ul className={styles.list} aria-label={copy.history.listLabel}>
          {items.map((item) => {
            const open = item.id === current?.id;
            const busy = action.isPending && action.variables.id === item.id;
            const path = stepPath(item.id, "biology") ?? "/";
            return (
              <li key={item.id} className={styles.item} aria-current={open ? "true" : undefined}>
                <div className={styles.what}>
                  <p className={styles.name}>
                    <Link to={path}>{item.disease.name}</Link>
                    {open && <span className={styles.open}>{copy.history.current}</span>}
                  </p>
                  <p className={styles.meta}>
                    <span>{dateTime(item.created_at)}</span>
                    <span>{copy.history.counts(item.candidate_count, item.docked_count)}</span>
                    {shared === undefined && <span>{dataLine(item)}</span>}
                  </p>
                </div>
                <button
                  type="button"
                  className={styles.button}
                  disabled={busy}
                  onClick={() => {
                    run(item);
                  }}
                >
                  {item.archived_at === null ? copy.history.archive : copy.history.restore}
                </button>
                {failure?.id === item.id && (
                  <p className={styles.failure} role="alert">
                    {failure.message}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
        {shared !== undefined && <p className={styles.data}>{shared}</p>}
      </>
    );
  }

  return (
    <Panel area="main" label={stepCopy("history").title}>
      <div className={styles.history}>
        <div className={styles.toggle} role="group" aria-label={copy.history.viewLabel}>
          {(["active", "archived"] as const).map((option) => (
            <button
              key={option}
              type="button"
              className={styles.tab}
              aria-pressed={view === option}
              onClick={() => {
                setChosen(option);
                setFailure(null);
              }}
            >
              {copy.history[option]}
              {lists[option].data !== undefined && (
                <span className={styles.count}>{lists[option].data.length}</span>
              )}
            </button>
          ))}
        </div>
        {body}
      </div>
    </Panel>
  );
}
