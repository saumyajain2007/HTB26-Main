/**
 * The resistance map's derivations (issue #30), kept apart from the drawing so they can be read
 * and tested on their own, as `charts/slopeLayout.ts` is.
 *
 * Everything here joins on ARO IDs, never on names (`docs/contracts.md`). Two rules it keeps:
 *
 * - `defeated_classes` is class-level. A class in the profile is **ruled out**, which is not the
 *   same as every drug in it being dead, so nothing here turns a class into a verdict on a drug.
 * - `evasion.status` is the only source for how a drug stands. `unaffected` means CARD links
 *   nothing in this isolate to the drug's class, and `unknown` means CARD cannot say; the two are
 *   different, and neither is a measured result, so they keep separate names below.
 */
import { drugName, releaseName } from "./format";
import type {
  AntibioticCandidate,
  AntibioticCandidateResult,
  EvasionStatus,
  ResistanceProfile,
} from "./resistance";

type ProfileGene = ResistanceProfile["genes"][number];

/**
 * How a drug class, or one drug, stands against the mechanisms in a profile. The names are the
 * map's own, so a reader of this module cannot mistake "no known link in CARD" for "unaffected
 * by this isolate".
 */
export type MapStatus = "ruled_out" | "partly_affected" | "no_known_link" | "unknown";

/** Every status, in the order the key lists them. */
export const MAP_STATUSES: readonly MapStatus[] = [
  "ruled_out",
  "partly_affected",
  "unknown",
  "no_known_link",
];

const FROM_EVASION: Record<EvasionStatus, MapStatus> = {
  defeated: "ruled_out",
  partly_affected: "partly_affected",
  unaffected: "no_known_link",
  unknown: "unknown",
};

/** A candidate's `evasion.status` in the map's words. */
export function mapStatus(status: EvasionStatus): MapStatus {
  return FROM_EVASION[status];
}

const SEVERITY = new Map(MAP_STATUSES.map((status, index) => [status, index]));

function severity(status: MapStatus): number {
  return SEVERITY.get(status) ?? MAP_STATUSES.length;
}

/** One mechanism column: a mechanism the isolate carries, and the determinants behind it. */
export interface MapMechanism {
  aroId: string;
  /** CARD's own term. */
  name: string;
  geneAroIds: readonly string[];
}

/** One drug on the map: where it falls, and how it stands. */
export interface MapDrug {
  id: string;
  /** Display name, already formatted. */
  name: string;
  status: MapStatus;
  /** A proposal from the generator, never an approved drug. */
  generated: boolean;
  /** The class CARD gives it, or null when it has none and the map cannot place it. */
  className: string | null;
}

/** One cell: the determinants that link this class to this mechanism, or none. */
export interface MapCell {
  mechanismAroId: string;
  geneAroIds: readonly string[];
}

/** One row of the map: a drug class, across the mechanism columns. */
export interface MapClassRow {
  aroId: string;
  /** CARD's own term. */
  name: string;
  status: MapStatus;
  /** One cell per mechanism column, in column order. */
  cells: readonly MapCell[];
  /** The ranked drugs CARD puts in this class, in the order they were ranked. */
  drugs: readonly MapDrug[];
  /** The profile evidence behind the class being ruled out. */
  evidenceIds: readonly string[];
}

/** One determinant, for the list that names what the isolate carries. */
export interface MapDeterminant {
  aroId: string;
  /** Short label, e.g. "mecA" or "gyrA S84L". */
  label: string;
  /** CARD's own name for the model, which the short label is cut from. */
  cardName: string;
  modelType: string;
  /** CARD's mechanism terms for this determinant. */
  mechanisms: readonly string[];
  /** The sensitive target CARD names, or null where it names none. */
  affectedTarget: string | null;
  /** How many drug classes CARD links to it. */
  classCount: number;
  /** The cited statements behind the row, in the profile's own order. */
  evidence: readonly { id: string; statement: string }[];
}

/** The mechanism columns, in the profile's roll-up order. */
export function mapMechanisms(profile: ResistanceProfile): MapMechanism[] {
  return profile.mechanisms.map((mechanism) => ({
    aroId: mechanism.aro_id,
    name: mechanism.name,
    geneAroIds: mechanism.gene_aro_ids,
  }));
}

function toDrug(candidate: AntibioticCandidate): MapDrug {
  return {
    id: candidate.candidate_id,
    name: drugName(candidate.name),
    status: mapStatus(candidate.evasion.status),
    generated: candidate.source === "generated",
    className: candidate.drug_class?.name ?? null,
  };
}

/** True when CARD gives the drug a class the map can join on. */
function placeable(candidate: AntibioticCandidate): boolean {
  return candidate.drug_class !== null && candidate.drug_class.aro_id !== "";
}

interface RowDraft {
  aroId: string;
  name: string;
  ruledOut: boolean;
  /** Determinants per mechanism column, by mechanism ARO ID. */
  hits: Map<string, string[]>;
  drugs: MapDrug[];
  evidenceIds: readonly string[];
}

/**
 * The map's rows: every drug class the profile rules out, plus every class the ranked drugs sit
 * in. A row the profile rules out is `ruled_out` whatever the drugs on it say; any other row
 * takes the standing of the worst drug on it, since `evasion.status` is the only source for that.
 *
 * Rows are grouped by standing, worst first, then by the column they are first marked in, so the
 * marks gather into blocks instead of scattering. Classes with nothing against them come last:
 * what is left after the wall.
 */
export function mapClassRows(
  profile: ResistanceProfile,
  candidates: AntibioticCandidateResult | undefined,
): MapClassRow[] {
  const mechanisms = mapMechanisms(profile);
  const column = new Map(mechanisms.map((mechanism, index) => [mechanism.aroId, index]));
  // The mechanisms each determinant carries, so a determinant's mark lands in the right columns.
  const carried = new Map(
    profile.genes.map((gene) => [gene.aro_id, gene.mechanisms.map((term) => term.aro_id)]),
  );
  const drafts = new Map<string, RowDraft>();
  const draft = (aroId: string, name: string): RowDraft => {
    const existing = drafts.get(aroId);
    if (existing !== undefined) return existing;
    const made: RowDraft = {
      aroId,
      name,
      ruledOut: false,
      hits: new Map(),
      drugs: [],
      evidenceIds: [],
    };
    drafts.set(aroId, made);
    return made;
  };

  for (const klass of profile.defeated_classes) {
    const row = draft(klass.aro_id, klass.name);
    row.ruledOut = true;
    row.evidenceIds = klass.evidence_ids;
    for (const geneAroId of klass.gene_aro_ids) {
      for (const mechanismAroId of carried.get(geneAroId) ?? []) {
        if (!column.has(mechanismAroId)) continue;
        const genes = row.hits.get(mechanismAroId) ?? [];
        if (!genes.includes(geneAroId)) genes.push(geneAroId);
        row.hits.set(mechanismAroId, genes);
      }
    }
  }

  for (const candidate of candidates?.candidates ?? []) {
    const klass = candidate.drug_class;
    if (klass === null || !placeable(candidate)) continue;
    draft(klass.aro_id, klass.name).drugs.push(toDrug(candidate));
  }

  const rows = [...drafts.values()].map((row): MapClassRow => {
    const worst = row.drugs.reduce<MapStatus | null>(
      (status, drug) =>
        status === null || severity(drug.status) < severity(status) ? drug.status : status,
      null,
    );
    return {
      aroId: row.aroId,
      name: row.name,
      // A class the profile rules out stays ruled out; otherwise the worst drug on the row speaks
      // for it, and a row with no drugs at all can only be left as not said.
      status: row.ruledOut ? "ruled_out" : (worst ?? "unknown"),
      cells: mechanisms.map((mechanism) => ({
        mechanismAroId: mechanism.aroId,
        geneAroIds: row.hits.get(mechanism.aroId) ?? [],
      })),
      drugs: row.drugs,
      evidenceIds: row.evidenceIds,
    };
  });

  const firstMark = (row: MapClassRow) => {
    const index = row.cells.findIndex((cell) => cell.geneAroIds.length > 0);
    return index === -1 ? mechanisms.length : index;
  };
  return rows.sort(
    (a, b) =>
      severity(a.status) - severity(b.status) ||
      firstMark(a) - firstMark(b) ||
      a.name.localeCompare(b.name),
  );
}

/**
 * The ranked drugs CARD gives no joinable drug class, so the map cannot place them: every
 * generated proposal, and any approved drug whose class has no ARO ID.
 */
export function unplacedDrugs(candidates: AntibioticCandidateResult | undefined): MapDrug[] {
  return (candidates?.candidates ?? []).filter((candidate) => !placeable(candidate)).map(toDrug);
}

const CONFERRING = " conferring resistance to ";

/**
 * A determinant's short label: CARD's model name cut back to the gene, with its point mutations
 * after it, e.g. "Staphylococcus aureus gyrA conferring resistance to fluoroquinolones" and S84L
 * becoming "gyrA S84L". The cut is CARD's own phrasing and the species the profile was asked
 * about, so nothing is guessed; a name that does not match is left whole.
 */
export function geneLabel(gene: ProfileGene, speciesName: string): string {
  const cut = gene.name.indexOf(CONFERRING);
  let name = cut > 0 ? gene.name.slice(0, cut) : gene.name;
  const prefix = `${speciesName} `;
  if (speciesName !== "" && name.toLowerCase().startsWith(prefix.toLowerCase())) {
    name = name.slice(prefix.length);
  }
  name = name.trim();
  if (name === "") name = gene.name;
  return [name, ...gene.variants.map((variant) => variant.mutation)].join(" ");
}

/** The determinants, in the profile's own order, with the statements cited for each. */
export function determinants(profile: ResistanceProfile): MapDeterminant[] {
  const statements = new Map(profile.evidence.map((item) => [item.id, item.statement]));
  return profile.genes.map((gene) => ({
    aroId: gene.aro_id,
    label: geneLabel(gene, profile.input.species.name),
    cardName: gene.name,
    modelType: gene.model_type,
    mechanisms: gene.mechanisms.map((term) => term.name),
    affectedTarget: gene.affected_target?.name ?? null,
    classCount: gene.defeated_classes.length,
    evidence: gene.evidence_ids.flatMap((id) => {
      const statement = statements.get(id);
      return statement === undefined ? [] : [{ id, statement }];
    }),
  }));
}

/** Which keys the map's status key needs: the standings actually on screen, in a fixed order. */
export function statusesInUse(
  rows: readonly MapClassRow[],
  unplaced: readonly MapDrug[],
): MapStatus[] {
  const used = new Set<MapStatus>();
  for (const row of rows) {
    used.add(row.status);
    for (const drug of row.drugs) used.add(drug.status);
  }
  for (const drug of unplaced) used.add(drug.status);
  return MAP_STATUSES.filter((status) => used.has(status));
}

/** A pinned release in words, e.g. card-4.0.2 as "CARD 4.0.2". */
export function releaseLabel(release: string): string {
  const [source = "", ...rest] = release.split("-");
  const version = rest.join("-");
  if (source.toLowerCase() === "card" && version !== "") return `CARD ${version}`;
  return releaseName(release);
}
