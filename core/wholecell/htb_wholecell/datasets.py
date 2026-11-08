"""Readers for the three raw sources. Each yields plain dicts; nothing here filters or labels."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Iterator

A_BAUMANNII_TAXON = 470

_MIC_QUERY = """
select a.activity_id, md.chembl_id, cs.canonical_smiles, a.standard_relation,
       a.standard_value, a.standard_units, cp.mw_freebase, d.year
from assays s
join activities a on a.assay_id = s.assay_id
join molecule_dictionary md on md.molregno = a.molregno
join compound_structures cs on cs.molregno = a.molregno
left join compound_properties cp on cp.molregno = a.molregno
left join docs d on d.doc_id = a.doc_id
where s.assay_tax_id = ?
  and a.standard_type = 'MIC'
  and a.standard_units in ('ug.mL-1', 'nM')
  and a.standard_value is not null
  and a.data_validity_comment is null
  and coalesce(a.potential_duplicate, 0) = 0
"""


def read_liu_sd1(path: Path) -> Iterator[dict]:
    """Liu et al. 2023, Supplementary Data 1. Two title rows, then ``SMILES,Name,Rep 1,Rep 2,Mean``."""
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle)
        next(rows)  # the title row
        header = [h.strip() for h in next(rows)]
        if header != ["SMILES", "Name", "Rep 1", "Rep 2", "Mean"]:
            raise ValueError(f"unexpected SD1 header: {header}")
        for number, row in enumerate(rows, start=3):
            yield {"line": number, "smiles": row[0], "name": row[1].strip(),
                   "rep1": row[2], "rep2": row[3], "mean": row[4]}


def read_liu_sd2(path: Path) -> Iterator[dict]:
    """Liu et al. 2023, Supplementary Data 2: the Hub compounds the model was applied to."""
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.reader(handle)
        next(rows)
        header = [h.strip() for h in next(rows)]
        if header != ["SMILES", "Sample"]:
            raise ValueError(f"unexpected SD2 header: {header}")
        for number, row in enumerate(rows, start=3):
            yield {"line": number, "smiles": row[0], "sample": row[1]}


def read_hub_samples(path: Path) -> Iterator[dict]:
    """Broad Drug Repurposing Hub sample table (tab separated, ``!`` comment lines)."""
    with Path(path).open(encoding="utf-8", newline="") as handle:
        lines = (line for line in handle if not line.startswith("!"))
        yield from csv.DictReader(lines, delimiter="\t")


def read_chembl_mic(db_path: Path, taxon: int = A_BAUMANNII_TAXON) -> Iterator[dict]:
    """MIC records for one organism from a local ChEMBL SQLite file, opened read-only."""
    con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        for row in con.execute(_MIC_QUERY, (taxon,)):
            yield dict(zip(
                ("activity_id", "chembl_id", "smiles", "relation", "value", "units", "mw", "year"), row))
    finally:
        con.close()
