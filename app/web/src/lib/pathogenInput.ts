/**
 * Tidying a typed list of resistance determinants, before anything is sent anywhere.
 *
 * Only the shape of the text is handled here. What an entry *means* is CARD's business and the
 * server's: this file never decides whether a name is a real gene, so nothing it returns may be
 * shown as "known" or "unknown". A determinant can carry a point mutation (`gyrA S84L`), so a
 * space never separates two entries; commas, semicolons and line breaks do.
 */

/** A typed list of determinants, split and tidied, in the order they were typed. */
export interface ParsedGeneList {
  /** The entries, each with its whitespace collapsed, blanks dropped and each one unique. */
  entries: string[];
  /** Entries typed more than once, listed once each. They appear in `entries` once. */
  repeated: string[];
}

/**
 * Splits `text` into determinant entries on commas, semicolons and line breaks, collapses the
 * whitespace inside each one, drops the blanks, and keeps the first of any repeat. Matching is
 * exact: `mecA` and `MECA` stay two entries, because only CARD can say they are the same term.
 */
export function parseGeneList(text: string): ParsedGeneList {
  const entries: string[] = [];
  const repeated: string[] = [];
  const seen = new Set<string>();
  for (const piece of text.split(/[,;\r\n]+/)) {
    const entry = piece.trim().replace(/\s+/g, " ");
    if (entry === "") continue;
    if (seen.has(entry)) {
      if (!repeated.includes(entry)) repeated.push(entry);
      continue;
    }
    seen.add(entry);
    entries.push(entry);
  }
  return { entries, repeated };
}
