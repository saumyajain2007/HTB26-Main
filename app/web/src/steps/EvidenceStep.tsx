import { lazy, Suspense } from "react";
import { useSearchParams } from "react-router";
import { useConformer } from "../api/queries";
import type { Candidate, EvidenceItem, Experiment } from "../api/types";
import { FigureNote, Panel } from "../app/Figure";
import { useNetworkHover } from "../app/networkHover";
import { copy, unscorableReasonText } from "../copy/en";
import { focusCandidate, listedEvidence, noModelText, warningSentence } from "../lib/candidates";
import { drugName } from "../lib/format";
import styles from "./EvidenceStep.module.css";

/** The query parameter that picks which Candidate the Evidence step is about. */
export const DRUG_PARAM = "drug";

const MoleculeFigure = lazy(() =>
  import("../three/MoleculeFigure").then((module) => ({ default: module.MoleculeFigure })),
);

const escapeRegExp = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Link text for a source record: the database, or DailyMed for drug labels. */
function sourceLabel(item: EvidenceItem): string {
  try {
    if (new URL(item.url).hostname.endsWith("dailymed.nlm.nih.gov")) return "DailyMed";
  } catch {
    // Not a URL we can read; name the database instead.
  }
  return copy.evidence.sources[item.source];
}

/** One fact: a summary said once, with one link per source that records it. */
interface Fact {
  summary: string;
  links: { label: string; url: string }[];
}

/**
 * Facts merged by summary: several records can say the same thing ("Blocks JAK2."), so each
 * summary is listed once, linking the first record of each distinct source.
 */
function mergeFacts(items: readonly EvidenceItem[]): Fact[] {
  const facts = new Map<string, Fact>();
  for (const item of items) {
    const fact = facts.get(item.summary) ?? { summary: item.summary, links: [] };
    const label = sourceLabel(item);
    if (!fact.links.some((link) => link.label === label)) fact.links.push({ label, url: item.url });
    facts.set(item.summary, fact);
  }
  return [...facts.values()];
}

function MoleculePanel({ candidate }: { candidate: Candidate }) {
  const name = drugName(candidate.name);
  const conformer = useConformer(candidate.pubchem_cid);
  let body;
  if (candidate.pubchem_cid === null || conformer.data === null) {
    body = <FigureNote>{noModelText(candidate)}</FigureNote>;
  } else if (conformer.isError) {
    body = (
      <FigureNote>
        <p>{copy.evidence.modelUnavailable}</p>
        <button type="button" className={styles.retry} onClick={() => void conformer.refetch()}>
          {copy.retry}
        </button>
      </FigureNote>
    );
  } else if (conformer.data === undefined) {
    body = null;
  } else {
    body = (
      <Suspense fallback={null}>
        <MoleculeFigure conformer={conformer.data} name={name} />
      </Suspense>
    );
  }
  return (
    <Panel area="molecule" title={name}>
      {body}
    </Panel>
  );
}

function WarningBox({ candidate }: { candidate: Candidate }) {
  if (candidate.warnings.length === 0) return null;
  const cited = new Set(candidate.warnings.map((warning) => warning.evidence_id));
  const sources = new Map<string, EvidenceItem>();
  for (const item of candidate.evidence) {
    // One link per source name: several warnings often cite different pages of one label.
    if (cited.has(item.id) && !sources.has(sourceLabel(item))) sources.set(sourceLabel(item), item);
  }
  return (
    <div className={styles.warning} role="note" aria-labelledby="label-warning-title">
      <p id="label-warning-title" className={styles.warningTitle}>
        {copy.evidence.warningTitle}
      </p>
      <div className={styles.warningText}>
        <p>{warningSentence(candidate)}</p>
      </div>
      <div className={styles.warningSources}>
        {[...sources.values()].map((item) => (
          <a key={item.url} href={item.url} target="_blank" rel="noreferrer">
            {sourceLabel(item)}
          </a>
        ))}
      </div>
    </div>
  );
}

/**
 * The evidence step: one drug's evidence. The molecule in 3D (or a plain line for antibodies), the sourced
 * facts with links, and its label warnings, said once in the warning box and never repeated as
 * a fact. Hovering a fact points at the proteins it names in the network.
 */
export function EvidenceStep({ experiment }: { experiment: Experiment }) {
  const [params] = useSearchParams();
  const setHover = useNetworkHover();
  const candidate = focusCandidate(experiment.candidates, params.get(DRUG_PARAM));
  if (candidate === undefined) return null;

  const facts = mergeFacts(listedEvidence(candidate, experiment.network));
  // Without a network there is no route panel; the drug's reason is said here, once.
  const noRoute =
    experiment.network === null && candidate.unscorable_reason !== null
      ? unscorableReasonText(candidate.unscorable_reason)
      : null;
  const symbols = experiment.network?.nodes ?? [];
  const point = (fact: Fact | null) => {
    if (fact === null) {
      setHover(null);
      return;
    }
    const named = symbols
      .filter((node) => new RegExp(`\\b${escapeRegExp(node.symbol)}\\b`).test(fact.summary))
      .map((node) => node.id);
    setHover(named.length > 0 ? { highlight: named, focus: named } : null);
  };

  return (
    <>
      <MoleculePanel key={candidate.candidate_id} candidate={candidate} />
      <Panel area="evidence" label={copy.evidence.listLabel}>
        <div className={styles.scroll}>
          {noRoute !== null && <p className={styles.noRoute}>{noRoute}</p>}
          {facts.length > 0 && (
            <ul className={styles.facts} aria-label={copy.evidence.listLabel}>
              {facts.map((fact) => (
                <li
                  key={fact.summary}
                  onPointerEnter={() => {
                    point(fact);
                  }}
                  onPointerLeave={() => {
                    point(null);
                  }}
                >
                  <span>{fact.summary}</span>
                  <span className={styles.links}>
                    {fact.links.map((link) => (
                      <a key={link.label} href={link.url} target="_blank" rel="noreferrer">
                        {link.label}
                      </a>
                    ))}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <WarningBox candidate={candidate} />
        </div>
      </Panel>
    </>
  );
}
