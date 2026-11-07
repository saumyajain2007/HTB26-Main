import { useId, useState } from "react";
import { Link } from "react-router";
import { useEvaluation } from "../../api/queries";
import type {
  ConfidenceInterval,
  Evaluation,
  EvaluationDisease,
  EvaluationResult,
  EvaluationScope,
} from "../../api/types";
import { copy } from "../../copy/en";
import { capitalise, date, releaseName } from "../../lib/format";
import { Loading, Unavailable } from "../ExperimentStatus";
import { FigureGrid, FigureNote, Panel } from "../Figure";
import { PageBody, PageFrame } from "../PageFrame";
import { EXPLORE_PATH } from "../steps";
import styles from "./EvaluationPage.module.css";

const text = copy.evaluation;

/** The app's main ranking first, the random baseline last; unknown methods in between. */
const METHOD_ORDER = ["degree_matched_z", "direct_evidence", "shared_targets", "raw_proximity"];
const OURS = "degree_matched_z";
const BASELINE = "random";

const METRICS = ["recall_at_5", "recall_at_10", "recall_at_20", "mrr"] as const;
type Metric = (typeof METRICS)[number];

const SCOPES: readonly EvaluationScope[] = ["full_eligible", "common_scorable"];

/** The research pilot needs ten Diseases (plan.md, M3); fewer is said plainly. */
const PILOT_DISEASES = 10;

function methodRank(method: string): number {
  if (method === BASELINE) return METHOD_ORDER.length + 1;
  const index = METHOD_ORDER.indexOf(method);
  return index === -1 ? METHOD_ORDER.length : index;
}

/** A share as a whole percent; a small share that rounds to nothing still reads as found. */
function percent(value: number): string {
  if (value > 0 && value < 0.005) return "<1%";
  return `${String(Math.round(value * 100))}%`;
}

function score(value: number): string {
  if (value > 0 && value < 0.005) return "<0.01";
  return value.toFixed(2);
}

function formatted(metric: Metric, value: number): string {
  return metric === "mrr" ? score(value) : percent(value);
}

/** Every value is a share or score from 0 to 1; clamp so a whisker never leaves its track. */
function position(value: number): string {
  return `${String(Math.min(1, Math.max(0, value)) * 100)}%`;
}

function MetricCell({
  metric,
  value,
  interval,
}: {
  metric: Metric;
  value: number | undefined;
  interval: ConfidenceInterval | undefined;
}) {
  if (value === undefined) {
    return (
      <td className={styles.cell}>
        <span className={styles.missing}>{text.missing}</span>
      </td>
    );
  }
  const range =
    interval && text.range(formatted(metric, interval.low), formatted(metric, interval.high));
  return (
    <td className={styles.cell}>
      <span className={styles.value}>
        {formatted(metric, value)}
        {range !== undefined && <span className={styles.hidden}>, {range}</span>}
      </span>
      <span className={styles.track} aria-hidden="true">
        {interval && (
          <span
            className={styles.whisker}
            style={{
              left: position(interval.low),
              right: `calc(100% - ${position(interval.high)})`,
            }}
          />
        )}
        <span className={styles.dot} style={{ left: position(value) }} />
      </span>
    </td>
  );
}

function ResultsTable({ results }: { results: EvaluationResult[] }) {
  const rows = [...results].sort(
    (a, b) => methodRank(a.method) - methodRank(b.method) || a.method.localeCompare(b.method),
  );
  return (
    <div className={styles.scroll}>
      <table className={styles.table} aria-label={text.resultsTitle}>
        <thead>
          <tr>
            <th scope="col" className={styles.methodHead}>
              {text.method}
            </th>
            {METRICS.map((metric) => (
              <th key={metric} scope="col">
                {text.metrics[metric]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.method}
              data-ours={row.method === OURS ? "" : undefined}
              data-baseline={row.method === BASELINE ? "" : undefined}
            >
              <th scope="row" className={styles.method}>
                {text.methods[row.method] ?? row.method}
                {row.method === OURS && <span className={styles.ours}>{text.ours}</span>}
              </th>
              {METRICS.map((metric) => (
                <MetricCell
                  key={metric}
                  metric={metric}
                  value={row.metrics[metric]}
                  interval={row.confidence_intervals?.[metric]}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DiseaseList({ diseases }: { diseases: EvaluationDisease[] }) {
  return (
    <ul className={styles.diseases}>
      {diseases.map((disease) => (
        <li key={disease.disease_id} className={styles.disease} data-status={disease.status}>
          <p className={styles.diseaseName}>
            {disease.name === null ? disease.disease_id : capitalise(disease.name)}
          </p>
          <p className={styles.diseaseMeta}>
            {disease.status === "evaluated"
              ? text.found(disease.known ?? 0, disease.candidates)
              : text.leftOut[disease.status]}
          </p>
        </li>
      ))}
    </ul>
  );
}

function Figure({ evaluation }: { evaluation: Evaluation }) {
  const retrieval = evaluation.results.filter((result) => result.experiment === "retrieval");
  const available = SCOPES.filter((scope) => retrieval.some((result) => result.scope === scope));
  const [chosen, setChosen] = useState<EvaluationScope | null>(null);
  const limitsId = useId();
  const scope = chosen !== null && available.includes(chosen) ? chosen : available[0];

  if (scope === undefined) {
    return (
      <FigureGrid layout="single">
        <Panel area="main" label={text.resultsTitle}>
          <FigureNote>
            <p>{text.empty}</p>
          </FigureNote>
        </Panel>
      </FigureGrid>
    );
  }

  const results = retrieval.filter((result) => result.scope === scope);
  const diseases = evaluation.diseases.filter((disease) => disease.scope === scope);
  const counted = Math.max(...results.map((result) => result.coverage.diseases ?? 0));
  const hasRanges = results.some((result) => result.confidence_intervals !== null);
  const first = results[0];
  const versions = first ? first.data_releases.map(releaseName) : [];

  const toggle = available.length > 1 && (
    <div className={styles.toggle} role="group" aria-label={text.scopeLabel}>
      {available.map((option) => (
        <button
          key={option}
          type="button"
          className={styles.tab}
          aria-pressed={scope === option}
          onClick={() => {
            setChosen(option);
          }}
        >
          {text.scopes[option]}
        </button>
      ))}
    </div>
  );

  return (
    <FigureGrid layout="evaluation">
      <Panel area="results" title={text.resultsTitle}>
        <div className={styles.results}>
          {evaluation.fixture_note !== null && <p className={styles.example}>{text.example}</p>}
          {toggle}
          <ResultsTable results={results} />
          <ul className={styles.notes}>
            {text.howToRead.map((line) => (
              <li key={line}>{line}</li>
            ))}
            {hasRanges && <li className={styles.rangeNote}>{text.rangeNote}</li>}
          </ul>
        </div>
      </Panel>
      <Panel area="tested" title={text.testedTitle}>
        <div className={styles.tested}>
          <DiseaseList diseases={diseases} />
          <section className={styles.limits} aria-labelledby={limitsId}>
            <h3 id={limitsId} className={styles.limitsTitle}>
              {text.limitsTitle}
            </h3>
            <ul>
              {counted < PILOT_DISEASES && <li>{text.tooFew(counted)}</li>}
              {text.limits.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </section>
          {first && (
            <p className={styles.record}>
              {text.record(first.manifest_hash, versions, date(first.created_at))}
            </p>
          )}
        </div>
      </Panel>
    </FigureGrid>
  );
}

/**
 * `/evaluation`: the frozen retrospective test (plan.md section 6). For Diseases with approved
 * treatments, how high each ranking puts them, beside the random baseline; which Diseases were
 * tested and why any were left out; and what the test can't show.
 */
export function EvaluationPage() {
  const evaluation = useEvaluation();
  let figure;
  if (evaluation.data !== undefined) {
    figure = <Figure evaluation={evaluation.data} />;
  } else if (evaluation.isError) {
    figure = <Unavailable message={text.unavailable} onRetry={() => void evaluation.refetch()} />;
  } else {
    figure = <Loading message={text.loading} />;
  }
  return (
    <PageFrame
      flow="document"
      header={
        <Link to={EXPLORE_PATH} className={styles.start}>
          {text.start}
        </Link>
      }
    >
      <PageBody title={text.title} intro={text.intro}>
        {figure}
      </PageBody>
    </PageFrame>
  );
}
