import type { NetworkWarning } from "../copy/en";

/** One drug in the slope chart. */
export interface SlopeRow {
  id: string;
  /** Display name, already formatted. */
  name: string;
  networkRank: number;
  /** Network z-score; null when it could not be measured (distance_only). */
  closeness: number | null;
  /** Why closeness is missing; null when measured. */
  warning: NetworkWarning | null;
  /** Rank by direct evidence only; null when there was no Disease evidence. */
  evidenceRank: number | null;
  /** The known-answer drug: drawn in ink. */
  emphasis: boolean;
}

/** A run of consecutive rows without closeness that share one reason. */
export interface MissingGroup {
  first: number;
  last: number;
  warning: NetworkWarning;
}

/**
 * Where each row's evidence rank lands on the right axis. Both axes are ordinal: rows sit in
 * network-rank order on the left, and the right axis lists the same drugs in evidence-rank order,
 * labelled with their true ranks. Rows without an evidence rank get no slot.
 */
export function evidenceSlots(rows: readonly SlopeRow[]): Map<string, number> {
  const ranked = rows
    .filter((row) => row.evidenceRank !== null)
    .sort((a, b) => (a.evidenceRank ?? 0) - (b.evidenceRank ?? 0));
  return new Map(ranked.map((row, slot) => [row.id, slot]));
}

/** Consecutive rows whose closeness is missing for the same reason, so each reason shows once. */
export function missingGroups(rows: readonly SlopeRow[]): MissingGroup[] {
  const groups: MissingGroup[] = [];
  rows.forEach((row, index) => {
    if (row.warning === null) return;
    const last = groups.at(-1);
    if (last?.last === index - 1 && last.warning === row.warning) last.last = index;
    else groups.push({ first: index, last: index, warning: row.warning });
  });
  return groups;
}

/** The closeness axis domain: always includes 0 and every value, in half steps. */
export function closenessDomain(values: readonly number[]): [number, number] {
  const low = Math.min(-1, ...values.map((value) => Math.floor(value * 2) / 2));
  const high = Math.max(0, ...values.map((value) => Math.ceil(value * 2) / 2));
  return [low, high];
}

/** Indices `i` where ranks[i] and ranks[i + 1] are not consecutive: the axis breaks there. */
export function rankBreaks(ranks: readonly number[]): number[] {
  return ranks.flatMap((rank, i) => {
    const next = ranks[i + 1];
    return next !== undefined && next - rank > 1 ? [i] : [];
  });
}
