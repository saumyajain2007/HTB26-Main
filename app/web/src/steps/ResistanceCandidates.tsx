import {
  lazy,
  Suspense,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
} from "react";
import type { Structure } from "../api/types";
import { FigureNote, Panel } from "../app/Figure";
import { copy } from "../copy/en";
import {
  bacterialStructures,
  dockFilesForStructure,
  structureForAntibiotic,
  structuresForAntibiotic,
} from "../lib/docking";
import { capitalise, listOf } from "../lib/format";
import type { AntibioticCandidateResult, Certificate, ResistanceProfile } from "../lib/resistance";
import {
  PROPERTY_RULE_KEYS,
  splitCandidates,
  type CandidateEntry,
  type PropertyRuleKey,
} from "../lib/resistanceCandidates";
import { releaseLabel, type MapStatus } from "../lib/resistanceMap";
import styles from "./ResistanceCandidates.module.css";

// 3Dmol.js loads only once a pose is shown.
const PoseViewer = lazy(() =>
  import("../three/PoseViewer").then((module) => ({ default: module.PoseViewer })),
);

export interface ResistanceCandidatesProps {
  profile: ResistanceProfile;
  candidates: AntibioticCandidateResult | undefined;
  certificates?: readonly Certificate[] | undefined;
  structures?: readonly Structure[] | undefined;
  loading?: boolean | undefined;
  onRetry?: (() => void) | undefined;
}

const text = copy.resistance.candidates;
const mapText = copy.resistance.map;

function isPropertyRuleKey(value: string): value is PropertyRuleKey {
  return (PROPERTY_RULE_KEYS as readonly string[]).includes(value);
}

function formatRuleQuantity(rule: PropertyRuleKey, value: number): string {
  const unit = text.ruleUnits[rule];
  return unit !== "" ? `${String(value)} ${unit}` : String(value);
}

function Mark({ status }: { status: MapStatus }) {
  return <span className={styles.mark} data-status={status} aria-hidden="true" />;
}

function RuleMark({ passed }: { passed: boolean | undefined }) {
  return (
    <span
      className={styles.ruleMark}
      data-passed={passed === undefined ? undefined : String(passed)}
      aria-hidden="true"
    />
  );
}

function mechanismPhrase(cardTerm: string): string {
  const plain = mapText.mechanismTerms[cardTerm];
  return plain !== undefined ? `${plain} (${mapText.cardTerm(cardTerm)})` : capitalise(cardTerm);
}

/**
 * Step 3 of the resistance flow (issues #31 and #40): approved antibiotics in rank order, generated
 * molecule proposals kept visibly apart from them, and a reading pane with the picked molecule's
 * explanation, separate features, per-candidate smoke-test panel and Lean 4 certificate view,
 * cited evidence, model jury status and caveats.
 */
export const ResistanceCandidates: (props: ResistanceCandidatesProps) => ReactElement = ({
  profile,
  candidates,
  certificates,
  structures,
  loading = false,
  onRetry,
}) => {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const buttonRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  const approvedTitleId = useId();
  const generatedTitleId = useId();
  const readingId = useId();

  if (candidates === undefined) {
    return (
      <Panel area="main" label={text.figureLabel}>
        <FigureNote>
          <p>{loading ? text.loading : text.unavailable}</p>
          {!loading && onRetry !== undefined && (
            <button type="button" className={styles.retry} onClick={onRetry}>
              {copy.retry}
            </button>
          )}
        </FigureNote>
      </Panel>
    );
  }

  const { approved, generated } = splitCandidates(profile, candidates, certificates);
  const allEntries = [...approved, ...generated];
  const [first] = allEntries;
  if (first === undefined) {
    return (
      <Panel area="main" label={text.figureLabel}>
        <FigureNote>{text.empty}</FigureNote>
      </Panel>
    );
  }

  const current = allEntries.find((entry) => entry.id === selectedId) ?? first;

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, currentId: string) => {
    const index = allEntries.findIndex((entry) => entry.id === currentId);
    if (index === -1) return;
    const nextIndex = {
      ArrowDown: index + 1,
      ArrowUp: index - 1,
      Home: 0,
      End: allEntries.length - 1,
    }[event.key];
    if (nextIndex === undefined) return;
    event.preventDefault();
    const target = allEntries[Math.min(Math.max(nextIndex, 0), allEntries.length - 1)];
    if (target === undefined) return;
    setSelectedId(target.id);
    buttonRefs.current.get(target.id)?.focus();
  };

  const setButtonRef = (id: string) => (node: HTMLButtonElement | null) => {
    if (node === null) {
      buttonRefs.current.delete(id);
    } else {
      buttonRefs.current.set(id, node);
    }
  };

  const orderLabels = listOf(candidates.ranking.order);

  return (
    <Panel area="main" label={text.figureLabel}>
      <div className={styles.sheet}>
        <div className={styles.split}>
          <div className={styles.leftColumn}>
            <section className={styles.section} aria-labelledby={approvedTitleId}>
              <h2 id={approvedTitleId} className={styles.sectionTitle}>
                {text.approvedTitle}
              </h2>
              <p className={styles.ruleNote}>
                {text.rankingRule(candidates.ranking.method, orderLabels)}
                {candidates.ranking.note !== null ? ` ${candidates.ranking.note}` : ""}
              </p>
              <div className={styles.scroll}>
                <table className={styles.table} aria-label={text.approvedTableLabel}>
                  <thead>
                    <tr>
                      <th scope="col" className={styles.rankHead}>
                        <span aria-hidden="true">{text.rankHead}</span>
                        <span className={styles.hidden}>{text.rankHeadLabel}</span>
                      </th>
                      <th scope="col">{text.drugHead}</th>
                      <th scope="col">{text.evasionHead}</th>
                      <th scope="col">{text.activityHead}</th>
                      <th scope="col">{text.verifyHead}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {approved.map((entry) => {
                      const on = entry.id === current.id;
                      return (
                        <tr key={entry.id} className={styles.row} data-selected={on || undefined}>
                          <td className={styles.rankCell}>{entry.rank}</td>
                          <th scope="row" className={styles.drugCell}>
                            <button
                              ref={setButtonRef(entry.id)}
                              type="button"
                              className={styles.pick}
                              tabIndex={on ? 0 : -1}
                              aria-current={on ? "true" : undefined}
                              aria-controls={readingId}
                              onClick={() => {
                                setSelectedId(entry.id);
                              }}
                              onKeyDown={(event) => {
                                onKeyDown(event, entry.id);
                              }}
                            >
                              <span className={styles.drugName}>{entry.name}</span>
                              <span className={styles.drugClass}>
                                {entry.drugClass !== null
                                  ? capitalise(entry.drugClass.name)
                                  : text.noClass}
                              </span>
                            </button>
                          </th>
                          <td>
                            <span className={styles.standing}>
                              <Mark status={entry.evasionStatus} />
                              {mapText.status[entry.evasionStatus]}
                            </span>
                          </td>
                          <td className={styles.metaCell}>
                            {entry.activitySummary ?? text.notMeasured}
                          </td>
                          <td className={styles.metaCell}>
                            {text.certificateStatus[entry.certificateStatus]}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>

            {generated.length > 0 && (
              <section className={styles.generatedSection} aria-labelledby={generatedTitleId}>
                <h2 id={generatedTitleId} className={styles.sectionTitle}>
                  {text.generatedTitle}
                </h2>
                <p className={styles.ruleNote}>{text.generatedNote}</p>
                <ul className={styles.generatedList} aria-label={text.generatedListLabel}>
                  {generated.map((entry) => {
                    const on = entry.id === current.id;
                    return (
                      <li
                        key={entry.id}
                        className={styles.generatedItem}
                        data-selected={on || undefined}
                      >
                        <button
                          ref={setButtonRef(entry.id)}
                          type="button"
                          className={styles.pick}
                          tabIndex={on ? 0 : -1}
                          aria-current={on ? "true" : undefined}
                          aria-controls={readingId}
                          onClick={() => {
                            setSelectedId(entry.id);
                          }}
                          onKeyDown={(event) => {
                            onKeyDown(event, entry.id);
                          }}
                        >
                          <span className={styles.drugName}>{entry.name}</span>
                          {entry.generated !== null && (
                            <span className={styles.drugClass}>
                              {entry.generated.parentCandidateName !== null
                                ? `${text.derivedFrom(entry.generated.parentCandidateName)} · ${entry.generated.model}`
                                : entry.generated.model}
                            </span>
                          )}
                        </button>
                        <span className={styles.standing}>
                          <Mark status={entry.evasionStatus} />
                          {mapText.status[entry.evasionStatus]}
                        </span>
                        <span className={styles.proposalBadge}>{text.proposalBadge}</span>
                      </li>
                    );
                  })}
                </ul>
              </section>
            )}
          </div>

          <CandidateReadingPane id={readingId} entry={current} structures={structures} />
        </div>

        <footer className={styles.footBand}>
          {candidates.fixture_note !== null && <p>{candidates.fixture_note}</p>}
          {profile.caveats.map((caveat) => (
            <p key={caveat}>{caveat}</p>
          ))}
          <p>{mapText.built(listOf(candidates.releases.map(releaseLabel)))}</p>
        </footer>
      </div>
    </Panel>
  );
};

function CandidateReadingPane({
  id,
  entry,
  structures,
}: {
  id: string;
  entry: CandidateEntry;
  structures: readonly Structure[] | undefined;
}) {
  return (
    <section id={id} className={styles.reading} aria-label={text.readingLabel(entry.name)}>
      <header className={styles.readingHead}>
        <p className={styles.kicker}>
          {entry.source === "approved" && entry.rank !== null
            ? text.approvedKicker(entry.rank)
            : text.generatedKicker}
        </p>
        <h2 className={styles.readingTitle}>{entry.name}</h2>
        <dl className={styles.metaList}>
          <dt>{text.classLabel}</dt>
          <dd>{entry.drugClass !== null ? capitalise(entry.drugClass.name) : text.noClass}</dd>
          {entry.target !== null && (
            <>
              <dt>{text.targetLabel}</dt>
              <dd>
                {entry.target.name}
                {entry.target.geneLabels.length > 0 &&
                  ` (${text.targetAffectedBy(listOf(entry.target.geneLabels))})`}
              </dd>
            </>
          )}
          {entry.mechanismOfAction !== null && (
            <>
              <dt>{text.mechanismLabel}</dt>
              <dd>{entry.mechanismOfAction}</dd>
            </>
          )}
        </dl>
      </header>

      {entry.generated !== null && (
        <div className={styles.block}>
          <h3 className={styles.subhead}>{text.provenanceTitle}</h3>
          <ul className={styles.bulletList}>
            <li>
              {text.generatorModel(
                entry.generated.model,
                entry.generated.modelVersion,
                entry.generated.seed,
              )}
            </li>
            {entry.generated.parentCandidateName !== null && (
              <li>{text.derivedFrom(entry.generated.parentCandidateName)}</li>
            )}
            {entry.generated.pocketPdbId !== null && (
              <li>{text.pocketUsed(entry.generated.pocketPdbId)}</li>
            )}
          </ul>
        </div>
      )}

      <div className={styles.block}>
        <h3 className={styles.subhead}>{text.whyTitle}</h3>
        <p className={styles.summary}>{entry.explanation.summary}</p>
        <p className={styles.standing}>
          <Mark status={entry.evasionStatus} />
          <span>
            <b>{mapText.status[entry.evasionStatus]}:</b> {entry.evasionRationale}
          </span>
        </p>

        {entry.defeatedBy.length > 0 && (
          <div>
            <p className={styles.rationale}>{text.defeatedByTitle}</p>
            <ul className={styles.bulletList}>
              {entry.defeatedBy.map((hit) => (
                <li key={`${hit.geneAroId}-${hit.mechanismAroId}`}>
                  <b>{hit.geneLabel}</b> — {mechanismPhrase(hit.mechanismName)}
                </li>
              ))}
            </ul>
          </div>
        )}

        {entry.explanation.mechanismsEvaded.length > 0 && (
          <div>
            <p className={styles.rationale}>{text.evadedTitle}</p>
            <ul className={styles.bulletList}>
              {entry.explanation.mechanismsEvaded.map((mechanism) => (
                <li key={mechanism}>{mechanismPhrase(mechanism)}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className={styles.block}>
        <h3 className={styles.subhead}>{text.featuresTitle}</h3>
        <p className={styles.rationale}>{text.featuresNote}</p>
        <dl className={styles.featureGrid}>
          {entry.features.map((feature) => (
            <div key={feature.key} style={{ display: "contents" }}>
              <dt className={styles.featureName}>{text.featureNames[feature.key]}</dt>
              <dd className={styles.featureValue}>
                {feature.available && feature.displayValue !== null ? (
                  <>
                    {feature.displayValue}
                    {feature.evidenceIds.length > 0 && (
                      <>
                        {" "}
                        <span className={styles.cite}>{feature.evidenceIds.join(", ")}</span>
                      </>
                    )}
                  </>
                ) : (
                  <span className={styles.featureMissing}>{text.featureUnavailable}</span>
                )}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <div className={styles.block}>
        <h3 className={styles.subhead}>{text.poseTitle}</h3>
        <CandidatePosePanel key={entry.id} entry={entry} structures={structures} />
      </div>

      <div className={styles.block}>
        <h3 className={styles.subhead}>{text.verifyTitle}</h3>
        <SmokeAndCertificatePanel entry={entry} />
      </div>

      {entry.evidence.length > 0 && (
        <div className={styles.block}>
          <h3 className={styles.subhead}>{text.evidenceTitle}</h3>
          <ul className={styles.evidenceList}>
            {entry.evidence.map((item) => (
              <li key={item.id} className={styles.evidenceItem}>
                <p>
                  <span className={styles.cite}>{item.id}</span>
                  {item.statement}
                </p>
                <p className={styles.evidenceMeta}>
                  {item.source} · {item.release}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className={styles.block}>
        <h3 className={styles.subhead}>{text.juryTitle}</h3>
        <p className={styles.rationale}>{text.juryPending}</p>
      </div>

      {(entry.explanation.caveats.length > 0 || entry.explanation.missing.length > 0) && (
        <div className={styles.block}>
          <h3 className={styles.subhead}>{text.caveatsTitle}</h3>
          <ul className={styles.bulletList}>
            {entry.explanation.caveats.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
            {entry.explanation.missing.map((missing) => (
              <li key={missing}>
                <b>{text.missingLabel}:</b> {missing}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function SmokeAndCertificatePanel({ entry }: { entry: CandidateEntry }) {
  const ruleSetDescription = text.ruleSetDescriptions[entry.smokeTest.rule_set];
  const certMarkPassed =
    entry.certificateStatus === "certified"
      ? true
      : entry.certificateStatus === "failed"
        ? false
        : undefined;
  const inchikey = entry.certificate?.inchikey ?? entry.inchikey;
  const failedRules = entry.certificate?.failed_rules ?? [];

  return (
    <div className={styles.verifyPanel}>
      <div className={styles.smokeSummary}>
        <p className={styles.standing}>
          <RuleMark passed={entry.smokeTest.valid ? entry.smokeTest.passed : false} />
          <span>
            <b>
              {!entry.smokeTest.valid
                ? text.smokeInvalid
                : entry.smokeTest.passed
                  ? text.smokePassed
                  : text.smokeFailed(entry.failedRuleCount)}
            </b>{" "}
            ({text.ruleSetLabel(entry.smokeTest.rule_set)}
            {entry.propertyRules.length > 0
              ? ` · ${text.ruleCounts(entry.passedRuleCount, entry.propertyRules.length)}`
              : ""}
            )
          </span>
        </p>
        {ruleSetDescription !== undefined && (
          <p className={styles.rationale}>{ruleSetDescription}</p>
        )}
      </div>

      {entry.propertyRules.length > 0 && (
        <div className={styles.scroll}>
          <table className={styles.ruleTable} aria-label={text.rulesTableLabel(entry.name)}>
            <thead>
              <tr>
                <th scope="col">{text.ruleHead}</th>
                <th scope="col">{text.valueHead}</th>
                <th scope="col">{text.limitHead}</th>
                <th scope="col">{text.marginHead}</th>
                <th scope="col">{text.statusHead}</th>
              </tr>
            </thead>
            <tbody>
              {entry.propertyRules.map((rule) => (
                <tr
                  key={rule.rule}
                  className={styles.ruleRow}
                  data-rule={rule.rule}
                  data-passed={String(rule.passed)}
                >
                  <th scope="row" className={styles.ruleNameCell}>
                    <span className={styles.ruleLabel}>{text.ruleNames[rule.rule]}</span>
                    <span className={styles.ruleCode}>{rule.rule}</span>
                  </th>
                  <td className={styles.ruleNumCell}>
                    {formatRuleQuantity(rule.rule, rule.value)}
                  </td>
                  <td className={styles.ruleNumCell}>
                    ≤ {formatRuleQuantity(rule.rule, rule.limit)}
                  </td>
                  <td className={styles.ruleMarginCell} data-passed={String(rule.passed)}>
                    {rule.signedMargin}
                  </td>
                  <td className={styles.ruleStatusCell}>
                    <span className={styles.ruleStatus} data-passed={String(rule.passed)}>
                      <RuleMark passed={rule.passed} />
                      {rule.passed
                        ? rule.leanChecked
                          ? text.ruleConfirmed
                          : text.rulePassed
                        : text.ruleFailed}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ul className={styles.bulletList}>
        <li>
          {entry.smokeTest.alerts.length > 0 ? (
            <>
              {text.alertsLabel(listOf(entry.smokeTest.alerts))} —{" "}
              <span className={styles.rationale}>
                {entry.smokeTest.strict_alerts ? text.alertsStrictNote : text.alertsWarningNote}
              </span>
            </>
          ) : (
            text.noAlerts
          )}
        </li>
        {entry.smokeTest.sa_score !== null && (
          <li>
            {text.saScore(entry.smokeTest.sa_score)}
            {entry.saExceedsSoftLimit &&
              entry.saSoftLimit !== null &&
              ` — ${text.saAboveCeiling(entry.saSoftLimit)}`}
          </li>
        )}
        {entry.smokeTest.descriptors !== null && (
          <li>{text.heavyAtoms(entry.smokeTest.descriptors.heavy_atoms)}</li>
        )}
      </ul>

      <div className={styles.certificateCard} data-status={entry.certificateStatus}>
        <p className={styles.standing}>
          <RuleMark passed={certMarkPassed} />
          <span>
            <b>{text.certificateStatus[entry.certificateStatus]}</b>
            {entry.certificate?.ran === true &&
              entry.certificate.lean_version !== null &&
              entry.certificate.seconds !== null &&
              ` · ${text.leanProvenance(entry.certificate.lean_version, entry.certificate.seconds)}`}
          </span>
        </p>
        <dl className={styles.metaList}>
          <dt>{text.leanRanLabel}</dt>
          <dd>
            {entry.certificate?.ran === true
              ? entry.certificate.certified
                ? text.leanRanCertified(entry.propertyRules.length)
                : text.leanRanFailed(listOf(failedRules))
              : text.leanNotRun}
          </dd>
          {inchikey !== "" && (
            <>
              <dt>{text.inchikeyLabel}</dt>
              <dd className={styles.mono}>{inchikey}</dd>
            </>
          )}
          {failedRules.length > 0 && (
            <>
              <dt>{text.leanFailedRulesLabel}</dt>
              <dd>
                {listOf(
                  failedRules.map((rule) =>
                    isPropertyRuleKey(rule) ? `${text.ruleNames[rule]} (${rule})` : rule,
                  ),
                )}
              </dd>
            </>
          )}
          {entry.certificate?.detail !== null && entry.certificate?.detail !== undefined && (
            <>
              <dt>{text.leanDetailLabel}</dt>
              <dd className={styles.certDetail}>{entry.certificate.detail}</dd>
            </>
          )}
        </dl>
        <p className={styles.rationale}>
          {entry.certificate?.ran === true
            ? text.certificateScopeConfirmed
            : text.certificateScopeSmokeOnly}
        </p>
      </div>
    </div>
  );
}

function CandidatePosePanel({
  entry,
  structures,
}: {
  entry: CandidateEntry;
  structures: readonly Structure[] | undefined;
}) {
  const selectId = useId();
  const matched = structures !== undefined ? structuresForAntibiotic(entry, structures) : [];
  const primaryMatch =
    structures !== undefined ? structureForAntibiotic(entry, structures) : undefined;
  const bacterial = structures !== undefined ? bacterialStructures(structures) : [];

  const options: Structure[] = [];
  const seen = new Set<string>();
  for (const structure of [...matched, ...bacterial]) {
    if (!seen.has(structure.id)) {
      seen.add(structure.id);
      options.push(structure);
    }
  }

  const [pickedStructureId, setPickedStructureId] = useState<string | null>(null);
  const [poseOpen, setPoseOpen] = useState(false);

  const activeStructure =
    options.find((s) => s.id === pickedStructureId) ?? primaryMatch ?? options[0];
  const isMatched =
    activeStructure !== undefined && matched.some((s) => s.id === activeStructure.id);
  const dockingFeature = entry.features.find((f) => f.key === "docking");

  return (
    <div className={styles.posePanel}>
      <p className={styles.rationale}>
        {primaryMatch !== undefined
          ? text.poseMatchedSummary(
              primaryMatch.pdb_id,
              primaryMatch.target_symbol,
              primaryMatch.target_id,
            )
          : entry.target !== null
            ? text.poseNoTargetStructure(entry.target.name)
            : text.poseNoTargetRecorded}
      </p>

      {activeStructure === undefined ? (
        <p className={styles.rationale}>{text.poseNoStructures}</p>
      ) : (
        <div className={styles.poseCard}>
          <div className={styles.poseControlsRow}>
            {options.length > 1 && (
              <label htmlFor={selectId} className={styles.posePicker}>
                <span className={styles.posePickerLabel}>{text.posePickerLabel}</span>
                <select
                  id={selectId}
                  className={styles.poseSelect}
                  value={activeStructure.id}
                  onChange={(event) => {
                    setPickedStructureId(event.target.value);
                  }}
                >
                  {options.map((structure) => (
                    <option key={structure.id} value={structure.id}>
                      {text.poseStructureOption(
                        structure.pdb_id,
                        structure.target_symbol,
                        structure.resolution,
                        structure.ligand.comp_id,
                      )}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <button
              type="button"
              className={styles.poseToggle}
              aria-expanded={poseOpen}
              onClick={() => {
                setPoseOpen((open) => !open);
              }}
            >
              {poseOpen ? text.poseHide : text.poseShow}
            </button>
          </div>

          <p className={styles.poseStructureLine}>
            {copy.pose.structure(
              activeStructure.pdb_id,
              activeStructure.target_symbol,
              activeStructure.resolution,
            )}
          </p>

          <dl className={styles.metaList}>
            <dt>{text.poseTargetAccessionLabel}</dt>
            <dd className={styles.mono}>{activeStructure.target_id}</dd>
            <dt>{text.poseCrystalLigandLabel}</dt>
            <dd>
              {text.poseCrystalLigandValue(
                activeStructure.ligand.name,
                activeStructure.ligand.comp_id,
              )}
            </dd>
            {isMatched &&
              dockingFeature?.available === true &&
              dockingFeature.displayValue !== null && (
                <>
                  <dt>{copy.pose.score}</dt>
                  <dd className={styles.mono}>{dockingFeature.displayValue}</dd>
                </>
              )}
          </dl>

          {poseOpen && (
            <>
              <div className={styles.poseStage}>
                <Suspense fallback={<p className={styles.rationale}>{copy.pose.loading}</p>}>
                  <PoseViewer
                    files={dockFilesForStructure(activeStructure)}
                    label={copy.pose.viewerLabel(
                      isMatched ? entry.name : activeStructure.ligand.name,
                      activeStructure.target_symbol,
                    )}
                  />
                </Suspense>
              </div>
              <p className={styles.rationale}>{copy.pose.caveat}</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
