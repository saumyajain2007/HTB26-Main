import { isBuilding } from "../api/queries";
import { BuildLine } from "../app/ExperimentStatus";
import type { DiseaseTarget, Experiment, TargetExcludedReason } from "../api/types";
import { Panel } from "../app/Figure";
import { useNetworkHover } from "../app/networkHover";
import { copy } from "../copy/en";
import { capitalise } from "../lib/format";
import styles from "./BiologyTargets.module.css";

const TICKS = [0, 0.25, 0.5, 0.75, 1];
const percent = (value: number) => `${String(value * 100)}%`;
const tick = (value: number) => (value === 0 || value === 1 ? String(value) : value.toFixed(2));

/**
 * Step 2: the Disease's proteins by link strength. Proteins the network can't use are named once,
 * under the chart, with the reason; the rule sentence says how many were used.
 */
export function BiologyTargets({ experiment }: { experiment: Experiment }) {
  const setHover = useNetworkHover();
  const used = experiment.targets.filter((target) => target.retained);
  // The proteins left out, by reason, in rank order: one sentence per reason.
  const excluded = new Map<TargetExcludedReason, string[]>();
  for (const target of experiment.targets) {
    if (target.excluded_reason === null) continue;
    excluded.set(target.excluded_reason, [
      ...(excluded.get(target.excluded_reason) ?? []),
      target.symbol,
    ]);
  }

  const point = (target: DiseaseTarget | null) => {
    setHover(target ? { highlight: [target.target_id], focus: [target.target_id] } : null);
  };

  return (
    <Panel area="targets" label={copy.biology.targetsLabel}>
      {isBuilding(experiment) && <BuildLine experiment={experiment} />}
      {used.length > 0 && (
        <div className={styles.chart}>
          {/* Focusable so keyboard users can scroll it when the list is longer than the panel. */}
          {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
          <ol className={styles.bars} aria-label={copy.biology.targetsLabel} tabIndex={0}>
            {used.map((target) => (
              <li
                key={target.target_id}
                className={styles.row}
                onPointerEnter={() => {
                  point(target);
                }}
                onPointerLeave={() => {
                  point(null);
                }}
              >
                <span className={styles.label}>
                  <b>{target.symbol}</b>
                  <span>{capitalise(target.name)}</span>
                </span>
                <span className={styles.track}>
                  <i style={{ width: percent(target.evidence_only_score) }} />
                  <em style={{ left: `calc(${percent(target.evidence_only_score)} + 8px)` }}>
                    {target.evidence_only_score.toFixed(2)}
                  </em>
                </span>
              </li>
            ))}
          </ol>
          <div className={styles.axis}>
            <div className={styles.ticks} aria-hidden="true">
              {TICKS.map((value) => (
                <span key={value} style={{ left: percent(value) }}>
                  {tick(value)}
                </span>
              ))}
            </div>
            <p className={styles.axisTitle}>{copy.biology.strength}</p>
          </div>
        </div>
      )}
      <div className={styles.notes}>
        {experiment.network === null ? (
          <>
            <p>{copy.biology.ruleNoNetwork(experiment.targets.length)}</p>
            <p>{copy.biology.noNetwork}</p>
          </>
        ) : (
          <p>{copy.biology.rule(experiment.targets.length, used.length)}</p>
        )}
        {[...excluded].map(([reason, symbols]) => (
          <p key={reason}>{copy.biology.excluded[reason](symbols)}</p>
        ))}
      </div>
    </Panel>
  );
}
