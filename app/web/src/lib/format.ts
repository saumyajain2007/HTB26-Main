/**
 * Display formatting shared by every step, so a name or number reads the same everywhere.
 */

/** Upper-cases the first letter and leaves the rest alone. */
export function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * A drug's name in sentence case. ChEMBL sends preferred names in capitals (BARICITINIB,
 * ACETYLSALICYLIC ACID); they read as shouting next to the rest of the interface. Names that
 * already mix cases are left as they are.
 */
export function drugName(chemblName: string): string {
  const name = chemblName.trim();
  if (name !== name.toUpperCase()) return name;
  return capitalise(name.toLowerCase());
}

/** A signed decimal with a true minus sign, e.g. −3.1, and tabular-friendly digits. */
export function signed(value: number, digits = 1): string {
  const text = Math.abs(value).toFixed(digits);
  if (Number(text) === 0) return text;
  return value < 0 ? `−${text}` : text;
}

/** "a", "a and b", "a, b and c". */
export function listOf(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1] ?? ""}`;
}

const SOURCES: Record<string, string> = {
  opentargets: "Open Targets",
  chembl: "ChEMBL",
  string: "STRING",
  reactome: "Reactome",
};

/** A pinned data release in words, e.g. opentargets-26.09 as "Open Targets 26.09". */
export function releaseName(release: string): string {
  const [source = "", ...version] = release.split("-");
  const name = SOURCES[source];
  return name === undefined ? release : `${name} ${version.join("-")}`;
}

const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/** A moment in the reader's time zone, e.g. "25 Oct 2026, 09:00". */
export function dateTime(iso: string): string {
  return DATE_TIME.format(new Date(iso));
}

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

/** A day in the reader's time zone, e.g. "25 Oct 2026". */
export function date(iso: string): string {
  return DATE.format(new Date(iso));
}
