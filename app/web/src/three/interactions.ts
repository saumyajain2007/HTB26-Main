/**
 * Close polar contacts between a drug and its protein, found from coordinates alone.
 *
 * A nitrogen or oxygen of the drug within POLAR_ANGSTROM of a nitrogen or oxygen of the protein
 * is a possible hydrogen bond. Only the distance is checked, not the angle or the hydrogens, so
 * these are candidates for hydrogen bonds, never confirmed ones.
 */

/** The heavy-atom distance (Å) within which two N or O atoms can share a hydrogen bond. */
export const POLAR_ANGSTROM = 3.5;

/** The fields of a 3Dmol atom this module reads. */
export interface ContactAtom {
  x?: number;
  y?: number;
  z?: number;
  elem?: string;
  /** The atom's name in its structure, such as "OD1" or "N". */
  atom?: string;
  /** The residue's three-letter code, such as "ASP". */
  resn?: string;
  resi?: number;
  chain?: string;
}

export interface Contact {
  /** The protein residue, such as "Asp73". */
  residue: string;
  chain: string;
  proteinAtom: string;
  ligandAtom: string;
  /** Heavy-atom distance in ångströms. */
  distance: number;
  /** Where the line is drawn from (the drug) and to (the protein), in structure coordinates. */
  ligandPoint: [number, number, number];
  proteinPoint: [number, number, number];
}

const POLAR = new Set(["N", "O"]);

/** "ASP" becomes "Asp"; a two-letter nucleotide or ion keeps its own shape. */
export function residueName(resn: string | undefined, resi: number | undefined): string {
  const name = (resn ?? "").trim();
  const pretty = name.length === 3 ? name.charAt(0) + name.slice(1).toLowerCase() : name;
  return `${pretty}${resi === undefined ? "" : String(resi)}`;
}

const isPolar = (atom: ContactAtom) => POLAR.has((atom.elem ?? "").toUpperCase());

/**
 * The drug's close polar contacts with the protein, closest first. Water is not a residue and
 * is skipped, and the drug's own atoms are never matched with each other.
 */
export function polarContacts(
  drug: readonly ContactAtom[],
  protein: readonly ContactAtom[],
  limit = POLAR_ANGSTROM,
): Contact[] {
  const found: Contact[] = [];
  const reach = limit * limit;
  const donors = protein.filter((atom) => isPolar(atom) && atom.resn !== "HOH");
  for (const own of drug) {
    if (!isPolar(own)) continue;
    for (const other of donors) {
      const dx = (own.x ?? 0) - (other.x ?? 0);
      const dy = (own.y ?? 0) - (other.y ?? 0);
      const dz = (own.z ?? 0) - (other.z ?? 0);
      const squared = dx * dx + dy * dy + dz * dz;
      if (squared > reach) continue;
      found.push({
        residue: residueName(other.resn, other.resi),
        chain: other.chain ?? "",
        proteinAtom: (other.atom ?? other.elem ?? "").trim(),
        ligandAtom: (own.atom ?? own.elem ?? "").trim(),
        distance: Math.sqrt(squared),
        ligandPoint: [own.x ?? 0, own.y ?? 0, own.z ?? 0],
        proteinPoint: [other.x ?? 0, other.y ?? 0, other.z ?? 0],
      });
    }
  }
  return found.sort((a, b) => a.distance - b.distance);
}
