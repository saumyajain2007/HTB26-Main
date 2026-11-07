import {
  Fragment,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type Ref,
} from "react";
import { ApiError } from "../api/errors";
import { useAskJury } from "../api/queries";
import type { Experiment, JuryRun, JuryVote } from "../api/types";
import { Panel } from "../app/Figure";
import { Marker } from "../charts/Marker";
import { copy } from "../copy/en";
import { drugName, listOf } from "../lib/format";
import {
  countedJurors,
  DECISIONS,
  decisionCounts,
  excludedJurors,
  failedCheck,
  juryRows,
  lastRank,
  retriedCount,
  type Juror,
  type JuryRow,
} from "../lib/jury";
import styles from "./JuryStep.module.css";

/**
 * Step 5: the Model jury. Before it is asked, one button; while it reviews, each model's
 * progress; once done, the ballot board (every model's rank and decision for every drug) and a
 * reading pane with what each model said about the drug picked on the board. A failed review
 * says so plainly, shows how each model fared and never shows votes it doesn't have.
 */
export function JuryStep({ experiment }: { experiment: Experiment }) {
  const { jury } = experiment;
  if (jury === null) return <AskJury experiment={experiment} />;
  if (jury.status === "failed") {
    return (
      <Panel area="main" label={copy.jury.unavailable}>
        <div className={styles.status} role="alert">
          <p className={styles.headline}>{copy.jury.unavailable}</p>
          {jury.error !== null && <p className={styles.detail}>{jury.error}</p>}
          <JurorList jury={jury} />
        </div>
      </Panel>
    );
  }
  if (jury.status !== "done") {
    return (
      <Panel area="main" label={copy.jury.progressLabel}>
        <JuryProgress jury={jury} />
      </Panel>
    );
  }
  return <JuryResult experiment={experiment} jury={jury} />;
}

/** The API's own reason for a refusal (already archived, already asked), else a plain line. */
function askError(error: Error): string {
  if (error instanceof ApiError && !error.unreachable && error.detail !== null) return error.detail;
  return copy.jury.askFailed;
}

function AskJury({ experiment }: { experiment: Experiment }) {
  const ask = useAskJury(experiment.id);
  const reasonId = useId();
  const archived = experiment.archived_at !== null;
  const names = experiment.jury_config.models.map((model) => model.display_name);
  return (
    <Panel area="main" label={copy.jury.ask}>
      <div className={styles.status}>
        <p className={styles.lede}>{copy.jury.panel(listOf(names))}</p>
        <button
          type="button"
          className={styles.ask}
          disabled={archived || ask.isPending}
          aria-describedby={archived ? reasonId : undefined}
          onClick={() => {
            ask.mutate();
          }}
        >
          {copy.jury.ask}
        </button>
        {archived && (
          <p id={reasonId} className={styles.detail}>
            {copy.jury.archived}
          </p>
        )}
        {ask.error !== null && (
          <p className={styles.detail} role="alert">
            {askError(ask.error)}
          </p>
        )}
      </div>
    </Panel>
  );
}

/** Each model's progress while the jury reviews, in plain words. */
function JuryProgress({ jury }: { jury: JuryRun }) {
  return (
    <div className={styles.status}>
      {jury.status === "queued" && (
        <p className={styles.detail} role="status">
          {copy.jury.queued}
        </p>
      )}
      <JurorList jury={jury} />
    </div>
  );
}

/** One line per model: its state, and for answers that failed the checks, which check. */
function JurorList({ jury }: { jury: JuryRun }) {
  return (
    <ol className={styles.jurors} aria-label={copy.jury.progressLabel} aria-live="polite">
      {jury.models.map((model) => {
        const juror = jury.jurors.find((j) => j.model_id === model.id);
        const status = juror?.status ?? "pending";
        const check = status === "invalid" && juror ? failedCheck(juror.errors) : null;
        return (
          <li key={model.id} className={styles.juror} data-state={status}>
            <span className={styles.ring} aria-hidden="true" />
            <span className={styles.jurorName}>{model.display_name}</span>
            <span className={styles.jurorStatus}>
              {check === null
                ? copy.jury.jurorStatus[status]
                : copy.jury.invalidBecause(copy.jury.failedCheck[check])}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * The finished review: the ballot board, and the reading pane for the drug picked on it (the
 * consensus favourite until another is picked).
 */
function JuryResult({ experiment, jury }: { experiment: Experiment; jury: JuryRun }) {
  const jurors = countedJurors(jury);
  const rows = juryRows(jury, experiment.candidates);
  const [picked, setPicked] = useState<string | null>(null);
  const row = rows.find((r) => r.candidate.candidate_id === picked) ?? rows[0];
  const readingRef = useRef<HTMLDivElement>(null);
  const readingId = useId();
  const retried = retriedCount(jury);
  const excluded = excludedJurors(jury);
  const voted = jurors.length > 0 && row !== undefined;
  // Notes line up with the text of a model's note, when there is one, not with its marker.
  const indent = excluded.length > 0 && <span className={styles.indent} aria-hidden="true" />;

  /** On one column (narrow screens) the pane sits under the board: bring it into view. */
  const reveal = () => {
    const pane = readingRef.current;
    if (pane === null || pane.getBoundingClientRect().top < window.innerHeight) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    pane.scrollIntoView({ block: "start", behavior: still ? "auto" : "smooth" });
  };

  return (
    <>
      <Panel area="ballot" label={copy.jury.tableLabel}>
        <div className={styles.board}>
          <BallotKey jury={jury} contested={rows.some((r) => r.contested)} />
          {voted && (
            <BallotTable
              jurors={jurors}
              rows={rows}
              selected={row.candidate.candidate_id}
              lastRank={lastRank(jury, experiment.candidates)}
              controls={readingId}
              onSelect={setPicked}
              onPick={reveal}
            />
          )}
          {(jury.agreement !== null || retried > 0 || excluded.length > 0) && (
            <div className={styles.notes}>
              {excluded.map(({ juror, status }) => (
                <p key={juror.model.id} className={styles.note}>
                  <Marker index={juror.marker} />
                  <span>{copy.jury.excluded[status](juror.model.display_name)}</span>
                </p>
              ))}
              {jury.agreement !== null && (
                <p className={styles.note}>
                  {indent}
                  <span>{copy.jury.agreementHelp}</span>
                </p>
              )}
              {retried > 0 && (
                <p className={styles.note}>
                  {indent}
                  <span>{copy.jury.retried(retried)}</span>
                </p>
              )}
            </div>
          )}
        </div>
      </Panel>
      {voted && (
        <Panel area="reading" label={copy.jury.readingLabel(drugName(row.candidate.name))}>
          <ReadingPane ref={readingRef} id={readingId} row={row} jurors={jurors} />
        </Panel>
      )}
    </>
  );
}

/** The board's key: how much the models agree, then what a tile's look and number mean. */
function BallotKey({ jury, contested }: { jury: JuryRun; contested: boolean }) {
  return (
    <div className={styles.key}>
      {jury.agreement === null ? (
        <p className={styles.keyNote}>{copy.jury.agreementMissing}</p>
      ) : (
        <p className={styles.agreement}>
          <span>{copy.jury.agreement}</span>
          <b>{jury.agreement.toFixed(2)}</b>
          <span className={styles.agreementBar} aria-hidden="true">
            <span style={{ width: `${String(jury.agreement * 100)}%` }} />
          </span>
        </p>
      )}
      <ul className={styles.legend}>
        {DECISIONS.map((decision) => (
          <li key={decision}>
            <span className={styles.swatch} data-decision={decision} aria-hidden="true" />
            {copy.jury.decisions[decision]}
          </li>
        ))}
        {contested && (
          <li>
            <span className={styles.splitSwatch} aria-hidden="true" />
            {copy.jury.contestedTitle}
          </li>
        )}
        <li className={styles.keyNote}>{copy.jury.rankHelp}</li>
      </ul>
    </div>
  );
}

interface BallotTableProps {
  jurors: readonly Juror[];
  rows: readonly JuryRow[];
  selected: string;
  /** The lowest rank a model could give: the widest spread is this minus one. */
  lastRank: number;
  /** The reading pane's id, which the drug buttons control. */
  controls: string;
  onSelect: (candidateId: string) => void;
  /** A pointer or Enter picked a drug, rather than the arrow keys moving through them. */
  onPick: () => void;
}

/**
 * One row per drug in consensus order, one column per counted model. Each drug is a button that
 * covers its row; only the picked one is in the tab order, and the arrow keys move between them.
 */
function BallotTable({
  jurors,
  rows,
  selected,
  lastRank,
  controls,
  onSelect,
  onPick,
}: BallotTableProps) {
  const widest = Math.max(1, lastRank - 1);

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const next = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: rows.length - 1 }[
      event.key
    ];
    if (next === undefined) return;
    // Handled here, so the page's arrow keys don't change step.
    event.preventDefault();
    const target = rows[Math.min(Math.max(next, 0), rows.length - 1)];
    if (target === undefined) return;
    onSelect(target.candidate.candidate_id);
    const buttons = event.currentTarget.closest("tbody")?.querySelectorAll("button");
    buttons?.[rows.indexOf(target)]?.focus();
  };

  return (
    <div className={styles.scroll}>
      <table className={styles.table} aria-label={copy.jury.tableLabel}>
        <thead>
          <tr>
            <th scope="col" className={styles.rankHead}>
              <span aria-hidden="true">{copy.jury.consensusHead}</span>
              <span className={styles.hidden}>{copy.jury.consensusHeadLabel}</span>
            </th>
            <th scope="col">{copy.jury.drug}</th>
            {jurors.map((juror) => (
              <th key={juror.model.id} scope="col" className={styles.modelHead}>
                <span className={styles.model}>
                  <Marker index={juror.marker} />
                  <ModelName name={juror.model.display_name} />
                </span>
              </th>
            ))}
            <th scope="col" className={styles.spreadHead}>
              {copy.jury.spread}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const id = row.candidate.candidate_id;
            const on = id === selected;
            return (
              <tr
                key={id}
                className={styles.row}
                data-testid={`jury-row-${id}`}
                data-contested={row.contested || undefined}
                data-selected={on || undefined}
              >
                <td className={styles.rank}>
                  {row.consensusRank ?? (
                    <span className={styles.hidden}>{copy.jury.notInConsensus}</span>
                  )}
                </td>
                <th scope="row" className={styles.drug}>
                  <button
                    type="button"
                    className={styles.pick}
                    tabIndex={on ? 0 : -1}
                    aria-current={on || undefined}
                    aria-controls={controls}
                    onClick={() => {
                      onSelect(id);
                      onPick();
                    }}
                    onKeyDown={(event) => {
                      onKeyDown(event, index);
                    }}
                  >
                    <span className={styles.drugName}>{drugName(row.candidate.name)}</span>
                    {row.candidate.known_answer && (
                      <span className={styles.known}>{copy.jury.knownTreatment}</span>
                    )}
                  </button>
                </th>
                {row.votes.map((vote, column) => (
                  <td key={jurors[column]?.model.id ?? column} className={styles.vote}>
                    <Tile vote={vote} />
                  </td>
                ))}
                <td className={styles.spread}>
                  {row.spread !== null && (
                    <>
                      {row.spread > 0 && (
                        <span
                          className={styles.spreadBar}
                          style={{ "--share": row.spread / widest } as CSSProperties}
                          aria-hidden="true"
                        />
                      )}
                      <span>{row.spread}</span>
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A model's name for a narrow column: it may wrap between words, never inside one, so "GPT-5.4"
 * doesn't break at its hyphen.
 */
function ModelName({ name }: { name: string }) {
  const words = name.split(" ");
  return (
    <span>
      {words.map((word, index) => (
        <Fragment key={index}>
          {index > 0 && " "}
          <span className={styles.word}>{word}</span>
        </Fragment>
      ))}
    </span>
  );
}

/** One model's rank for one drug, filled, outlined or light by its decision. */
function Tile({ vote }: { vote: JuryVote | null }) {
  if (vote === null) {
    return (
      <span className={styles.tile} data-decision="none">
        <span className={styles.hidden}>{copy.jury.noRank}</span>
      </span>
    );
  }
  return (
    <span className={styles.tile} data-decision={vote.decision}>
      {vote.rank}
      <span className={styles.hidden}>, {copy.jury.decisions[vote.decision]}</span>
    </span>
  );
}

interface ReadingPaneProps {
  ref: Ref<HTMLDivElement>;
  id: string;
  row: JuryRow;
  jurors: readonly Juror[];
}

/** One drug: its place in the consensus, the verdict in plain words, then each model's case. */
function ReadingPane({ ref, id, row, jurors }: ReadingPaneProps) {
  const counts = decisionCounts(row.votes);
  return (
    <div ref={ref} id={id} className={styles.reading}>
      <header className={styles.readingHead}>
        <p className={styles.kicker}>
          {row.consensusRank === null
            ? copy.jury.notInConsensus
            : copy.jury.consensusRank(row.consensusRank)}
        </p>
        <h2 className={styles.readingTitle}>{drugName(row.candidate.name)}</h2>
        {counts.length > 0 && (
          <p className={styles.verdict} data-contested={row.contested || undefined}>
            {copy.jury.verdict(
              counts,
              row.votes.every((vote) => vote !== null),
            )}
          </p>
        )}
      </header>
      {/* Keyed by drug, so a newly picked drug is read from the top. */}
      <ul key={row.candidate.candidate_id} className={styles.calls}>
        {jurors.map((juror, index) => {
          const vote = row.votes[index] ?? null;
          return (
            <li key={juror.model.id} className={styles.call}>
              <h3 className={styles.callHead}>
                <Marker index={juror.marker} />
                <span className={styles.callModel}>{juror.model.display_name}</span>
                <span className={styles.callDecision} data-decision={vote?.decision}>
                  {vote === null ? copy.jury.noVote : copy.jury.call(vote.decision, vote.rank)}
                </span>
              </h3>
              {vote !== null && vote.rationale.trim() !== "" && (
                <p className={styles.rationale}>{vote.rationale}</p>
              )}
              {vote !== null && vote.objection.trim() !== "" && (
                <p className={styles.objection}>
                  <b>{copy.jury.objection}</b> {vote.objection}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
