import { useId, type ReactElement } from "react";
import { FigureNote, Panel } from "../app/Figure";
import { copy } from "../copy/en";
import { capitalise, listOf } from "../lib/format";
import type { AntibioticCandidateResult, ResistanceProfile } from "../lib/resistance";
import {
  determinants,
  mapClassRows,
  mapMechanisms,
  releaseLabel,
  statusesInUse,
  unplacedDrugs,
  type MapDrug,
  type MapStatus,
} from "../lib/resistanceMap";
import styles from "./ResistanceMap.module.css";

export interface ResistanceMapProps {
  /** The profile to draw: its `mechanisms`, `defeated_classes` and the genes behind each. */
  profile: ResistanceProfile;
  /**
   * The candidates ranked against the profile, when they have loaded. Their `evasion.status` is
   * the only source for "evaded" and "partly affected"; the profile alone says which classes are
   * defeated. Undefined while the query is in flight, or when it failed.
   */
  candidates?: AntibioticCandidateResult | undefined;
}

const text = copy.resistance.map;

/**
 * The mark for one standing: a shape as well as a colour, so the map survives being read in grey
 * or by a colour-blind reader. Always beside the word it stands for, never on its own.
 */
function Mark({ status }: { status: MapStatus }) {
  return <span className={styles.mark} data-status={status} aria-hidden="true" />;
}

/** One drug where the map puts it: the mark, its name, and its standing for a screen reader. */
function Drug({ drug }: { drug: MapDrug }) {
  return (
    <li className={styles.drug} data-status={drug.status}>
      <Mark status={drug.status} />
      <span>{drug.name}</span>
      <span className={styles.hidden}>, {text.status[drug.status]}</span>
      {drug.generated && <span className={styles.proposed}>{text.proposed}</span>}
    </li>
  );
}

/**
 * Step 2 of the resistance flow, and the figure the whole tool is built around: the resistance
 * mechanisms an isolate carries, set against the drug classes they rule out.
 *
 * The form is a matrix, which is the honest shape for this data. Both axes are small controlled
 * vocabularies, and the empty cells carry as much as the filled ones: they are the classes
 * nothing in this isolate is linked to, which is the only way out of the wall. A flow diagram
 * would draw the links and lose the absences. A matrix is also already a table, so the figure
 * and its text equivalent are one thing rather than a picture with a transcript beside it, and it
 * reflows and scales without SVG text-fitting. Marks are shapes first and colour second.
 *
 * Nothing here is a verdict on a drug. A class is *ruled out*; the rest of the map is the absence
 * of a link in CARD, which the key and the caveats say in so many words.
 */
export const ResistanceMap: (props: ResistanceMapProps) => ReactElement = ({
  profile,
  candidates,
}) => {
  const mechanisms = mapMechanisms(profile);
  const rows = mapClassRows(profile, candidates);
  const unplaced = unplacedDrugs(candidates);
  const genes = determinants(profile);
  const labels = new Map(genes.map((gene) => [gene.aroId, gene.label]));
  const statuses = statusesInUse(rows, unplaced);
  const keyId = useId();
  const determinantsId = useId();
  const readId = useId();
  const fixtureNote = candidates?.fixture_note ?? null;
  const ruledOut = rows.filter((row) => row.status === "ruled_out").length;
  // The drug columns only exist once the ranking has loaded; the classes stand without it.
  const withDrugs = candidates !== undefined;

  if (mechanisms.length === 0 || rows.length === 0) {
    return (
      <Panel area="main" label={text.figureLabel}>
        <FigureNote>{text.nothingMapped}</FigureNote>
      </Panel>
    );
  }

  return (
    <Panel area="main" label={text.figureLabel}>
      <div className={styles.sheet}>
        <p className={styles.summary}>
          {withDrugs
            ? text.summary(mechanisms.length, ruledOut, rows.length)
            : text.summaryProfileOnly(mechanisms.length, ruledOut)}
        </p>

        <div className={styles.scroll}>
          <table className={styles.grid}>
            <caption className={styles.hidden}>{text.caption}</caption>
            <thead>
              <tr>
                <td />
                <th scope="colgroup" colSpan={mechanisms.length} className={styles.group}>
                  {text.mechanismsHead}
                </th>
                {withDrugs && <td />}
              </tr>
              <tr>
                <th scope="col" className={styles.classHead}>
                  {text.classHead}
                </th>
                {mechanisms.map((mechanism) => {
                  const plain = text.mechanismTerms[mechanism.name];
                  return (
                    <th key={mechanism.aroId} scope="col" className={styles.mechanismHead}>
                      <span className={styles.plain}>{plain ?? capitalise(mechanism.name)}</span>
                      {plain !== undefined && (
                        <>
                          {" "}
                          <span className={styles.term}>{text.cardTerm(mechanism.name)}</span>
                        </>
                      )}
                    </th>
                  );
                })}
                {withDrugs && (
                  <th scope="col" className={styles.drugsHead}>
                    {text.drugsHead}
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.aroId} data-status={row.status}>
                  <th scope="row" className={styles.class}>
                    <span className={styles.name}>{capitalise(row.name)}</span>{" "}
                    <span className={styles.standing}>
                      <Mark status={row.status} />
                      {text.status[row.status]}
                    </span>
                  </th>
                  {row.cells.map((cell) => (
                    <td key={cell.mechanismAroId} className={styles.cell}>
                      {cell.geneAroIds.length > 0 ? (
                        <span className={styles.hit}>
                          <Mark status="ruled_out" />
                          <span className={styles.hidden}>
                            {text.status.ruled_out}
                            {", "}
                          </span>
                          {listOf(cell.geneAroIds.map((aroId) => labels.get(aroId) ?? aroId))}
                        </span>
                      ) : (
                        <>
                          <span className={styles.blank} aria-hidden="true" />
                          <span className={styles.hidden}>{text.noMark}</span>
                        </>
                      )}
                    </td>
                  ))}
                  {withDrugs && (
                    <td className={styles.cell}>
                      {row.drugs.length === 0 ? (
                        <span className={styles.none}>{text.noDrugs}</span>
                      ) : (
                        <ul className={styles.drugs}>
                          {row.drugs.map((drug) => (
                            <Drug key={drug.id} drug={drug} />
                          ))}
                        </ul>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <section className={styles.key} aria-labelledby={keyId}>
          <h2 id={keyId} className={styles.keyTitle}>
            {text.keyTitle}
          </h2>
          <dl className={styles.keyList}>
            {statuses.map((status) => (
              <div key={status} className={styles.keyItem}>
                <dt className={styles.keyTerm}>
                  <Mark status={status} />
                  {text.status[status]}
                </dt>
                <dd className={styles.keyHelp}>{text.statusHelp[status]}</dd>
              </div>
            ))}
          </dl>
        </section>

        <div className={styles.band}>
          <section aria-labelledby={determinantsId}>
            <h2 id={determinantsId} className={styles.sectionTitle}>
              {text.determinantsTitle}
            </h2>
            <ul className={styles.genes}>
              {genes.map((gene) => (
                <li key={gene.aroId} className={styles.gene}>
                  <p className={styles.geneLabel}>{gene.label}</p>
                  {/* CARD's own name, unless the short label already is it. */}
                  {gene.cardName !== gene.label && (
                    <p className={styles.geneName}>{gene.cardName}</p>
                  )}
                  <p className={styles.geneSource}>
                    {text.determinantSource(gene.aroId, gene.modelType)}
                  </p>
                  <p>{text.rulesOut(gene.classCount)}</p>
                  <p>
                    {gene.affectedTarget === null
                      ? text.noTarget
                      : text.affects(gene.affectedTarget)}
                  </p>
                  {gene.evidence.map((item) => (
                    <p key={item.id} className={styles.statement}>
                      <span className={styles.cite}>{item.id}</span>
                      {item.statement}
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          </section>

          <section aria-labelledby={readId}>
            <h2 id={readId} className={styles.sectionTitle}>
              {text.readTitle}
            </h2>
            <div className={styles.notes}>
              {profile.caveats.map((caveat) => (
                <p key={caveat}>{caveat}</p>
              ))}
              <p>
                <b className={styles.level}>{text.confidence[profile.confidence.level]}</b>
                {profile.confidence.basis}
              </p>
              {!withDrugs && <p>{text.withoutCandidates}</p>}
              {fixtureNote !== null && <p>{fixtureNote}</p>}
              {unplaced.length > 0 && (
                <>
                  <p>{text.unplaced}</p>
                  <ul className={styles.drugs}>
                    {unplaced.map((drug) => (
                      <Drug key={drug.id} drug={drug} />
                    ))}
                  </ul>
                </>
              )}
              {profile.unresolved_inputs.map((input) => (
                <p key={input.text}>{text.unresolved(input.text, input.reason)}</p>
              ))}
              <p>{text.built(listOf(profile.releases.map(releaseLabel)))}</p>
            </div>
          </section>
        </div>
      </div>
    </Panel>
  );
};
