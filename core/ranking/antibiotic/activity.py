"""Activity feature: measured MIC of each drug against the profile's pathogen, from ChEMBL.

For every pool drug this collects ChEMBL ``MIC`` records whose assay organism is the pathogen
(by NCBI taxid, or by name for strains such as "Staphylococcus aureus subsp. aureus Mu50"), and
summarises them as one median MIC in mg/L. A drug with too few usable records gets no activity
value; it is reported as missing, never as zero.

What is kept:

    units       ``ug.mL-1`` (equal to mg/L) and ``nM`` (converted with the molecule's freebase mass).
                Every other unit is dropped and counted.
    relations   ``=`` and the censored ``<``, ``<=``, ``>``, ``>=``. A censored value enters the median
                at its stated number and is counted in the evidence, because "> 64 mg/L" is real
                evidence of poor activity and dropping it would make inactive drugs look untested.
    validity    records with a ChEMBL data-validity comment or flagged as potential duplicates are dropped.
    parents     records on salts and other forms count toward their parent drug.

What this is not: a susceptibility call. It is a species-level median across papers, with no
breakpoint and no knowledge of the isolate's resistance. Comparing raw MICs between different
drugs is crude, because potency and clinical breakpoints differ by drug. The ranking uses it as
evidence that a drug has been measured against the species, and the explanation says so.
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .rank import Activity

MIN_RECORDS = 3
UNIT = "mg/L (median MIC)"
RELATIONS = ("=", "<", "<=", ">", ">=")
CENSORED = {"<", "<=", ">", ">="}

# Parents plus every form (salt, hydrate) that ChEMBL groups under them.
_QUERY = """
SELECT p.chembl_id, ac.activity_id, ac.assay_id, ac.doc_id, ac.standard_value, ac.standard_units,
       ac.standard_relation, cp.mw_freebase
FROM molecule_dictionary p
JOIN molecule_hierarchy h ON h.parent_molregno = p.molregno
JOIN activities ac ON ac.molregno = h.molregno
JOIN assays a ON a.assay_id = ac.assay_id
LEFT JOIN compound_properties cp ON cp.molregno = ac.molregno
WHERE p.chembl_id = ?
  AND ac.standard_type = 'MIC'
  AND ac.data_validity_comment IS NULL
  AND COALESCE(ac.potential_duplicate, 0) = 0
  AND ac.standard_value > 0
  AND (a.assay_tax_id = ? OR a.assay_organism = ? OR a.assay_organism LIKE ? || ' %')
"""


@dataclass(frozen=True)
class Summary:
    """What was kept and dropped for one drug. Returned alongside the Activity for the log."""

    chembl_id: str
    kept: int
    censored: int
    assays: int
    documents: int
    dropped_unit: int
    dropped_relation: int
    dropped_mass: int


def to_mg_per_l(value: float, units: str, mw: float | None) -> float | None:
    if units == "ug.mL-1":
        return value
    if units == "nM":
        return None if not mw else value * mw / 1e6  
    return None


def summarise(rows: Sequence[tuple], chembl_id: str) -> tuple[Summary, list[float]]:
    values, assays, docs = [], set(), set()
    censored = dropped_unit = dropped_rel = dropped_mass = 0
    for _, _, assay_id, doc_id, value, units, relation, mw in rows:
        if relation not in RELATIONS:
            dropped_rel += 1
            continue
        if units not in ("ug.mL-1", "nM"):
            dropped_unit += 1
            continue
        mg_l = to_mg_per_l(float(value), units, mw)
        if mg_l is None:
            dropped_mass += 1
            continue
        values.append(mg_l)
        censored += relation in CENSORED
        assays.add(assay_id)
        docs.add(doc_id)
    return Summary(chembl_id, len(values), censored, len(assays), len(docs), dropped_unit, dropped_rel,
                   dropped_mass), values


def load_activity(
    database: Path | str,
    chembl_ids: Sequence[str],
    species: dict,
    *,
    min_records: int = MIN_RECORDS,
) -> tuple[dict[str, Activity], list[Summary]]:
    """Median MIC per drug against `species` ({"name", "ncbi_taxid"}), plus a summary per drug.

    Opens the database read-only. Drugs with fewer than `min_records` usable records are absent
    from the first result.
    """
    name, taxid = species["name"], species["ncbi_taxid"]
    found: dict[str, Activity] = {}
    summaries: list[Summary] = []
    con = sqlite3.connect(f"file:{Path(database).resolve()}?mode=ro", uri=True)
    try:
        for chembl_id in chembl_ids:
            rows = con.execute(_QUERY, (chembl_id, taxid, name, name)).fetchall()
            summary, values = summarise(rows, chembl_id)
            summaries.append(summary)
            if summary.kept < min_records:
                continue
            median = statistics.median(values)
            statement = (
                f"Median MIC {median:.3g} mg/L over {summary.kept} ChEMBL records against {name} "
                f"({summary.assays} assays, {summary.documents} documents"
                + (f"; {summary.censored} censored values counted at their stated number" if summary.censored else "")
                + "). Species-level, not specific to this isolate."
            )
            found[chembl_id] = Activity(round(median, 4), UNIT, statement)
    finally:
        con.close()
    return found, summaries
