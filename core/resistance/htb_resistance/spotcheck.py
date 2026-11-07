"""Spot check mapped genes against CARD's published web pages (issue #18).

For each gene, compares the AMR gene family, drug classes and resistance mechanisms in our CARD
tables with the same three rows on the gene's page at card.mcmaster.ca. A difference is reported,
never smoothed over. The result of the run recorded in docs/card-spot-check.md came from this
module.

Needs the network (one request per gene, one second apart). Pages are untrusted text: only the
three rows below are read, and only as plain text.
"""

from __future__ import annotations

import html
import re
import time
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Callable

from .card import CardError, read_table

PAGE_URL = "https://card.mcmaster.ca/aro/{number}"
FIELDS = {"family": "AMR Gene Family", "classes": "Drug Class", "mechanisms": "Resistance Mechanism"}

# The ten genes of issue #18: beta-lactamases of each Ambler class and target replacement, a
# target-alteration variant model, an efflux pump and an rRNA methyltransferase.
TEN_GENES = [
    "mecA", "PC1 beta-lactamase (blaZ)", "CTX-M-15", "TEM-1", "KPC-2", "NDM-1", "OXA-48",
    "Staphylococcus aureus gyrA conferring resistance to fluoroquinolones", "adeB", "armA",
]

# Differences found on 2026-11-07 and explained in docs/card-spot-check.md. The check fails on
# anything else, and also if one of these stops differing, so the record cannot go stale unnoticed.
KNOWN_DIFFERENCES = {
    ("ARO:3000617", "classes"): {"only_web": ["carbapenem", "monobactam"], "only_ours": []},  # mecA
    ("ARO:3001209", "classes"): {"only_web": ["carbapenem", "cephalosporin", "monobactam"], "only_ours": []},  # mecC
}


def fetch_page(aro_id: str, timeout: float = 30.0) -> str:
    request = urllib.request.Request(PAGE_URL.format(number=aro_id.split(":")[1]),
                                     headers={"User-Agent": "Mozilla/5.0 (HTB26 spot check)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(4_000_000).decode("utf-8", "ignore")


def parse_page(page: str) -> dict:
    """Accession and the three classification rows of a CARD page, as plain-text names."""
    accession = re.search(r"Accession\s*</td>\s*<td>\s*(ARO:\d+)", page)
    if accession is None:
        raise CardError("page has no ARO accession")
    out = {"accession": accession.group(1)}
    for key, label in FIELDS.items():
        row = re.search(r"<tr><td>" + re.escape(label) + r"</td><td>(.*?)</td></tr>", page, flags=re.S)
        out[key] = sorted(html.unescape(name).strip() for name in re.findall(r"<a [^>]*>(.*?)</a>", row.group(1))) if row else []
    return out


def local_record(card_release: Path | str, aro_id: str) -> dict:
    """The same three fields from our CARD tables."""
    release = Path(card_release)
    names = {r["aro_accession"]: r["name"] for r in read_table(release, "aro_terms")}
    found = defaultdict(set)
    kinds = {"AMR Gene Family": "family", "Drug Class": "classes", "Resistance Mechanism": "mechanisms"}
    for row in read_table(release, "model_categories"):
        if row["aro_accession"] == aro_id:
            found[kinds[row["category_class"]]].add(names[row["category_aro_accession"]])
    return {key: sorted(found[key]) for key in FIELDS}


def compare(web: dict, ours: dict) -> dict:
    """{field: {"only_web": [...], "only_ours": [...]}} for each field that differs."""
    diff = {}
    for key in FIELDS:
        only_web, only_ours = sorted(set(web[key]) - set(ours[key])), sorted(set(ours[key]) - set(web[key]))
        if only_web or only_ours:
            diff[key] = {"only_web": only_web, "only_ours": only_ours}
    return diff


def resolve(card_release: Path | str, gene: str) -> str:
    """An ARO id, or the exact name of a CARD detection model."""
    if re.fullmatch(r"ARO:\d{7}", gene):
        return gene
    matches = [r["aro_accession"] for r in read_table(card_release, "models") if r["name"] == gene]
    if len(matches) != 1:
        raise CardError(f"{gene!r} matches {len(matches)} CARD models; give an ARO id")
    return matches[0]


def spot_check(card_release: Path | str, genes: list[str], *, fetch: Callable[[str], str] = fetch_page,
               delay: float = 1.0) -> list[dict]:
    rows = []
    for n, gene in enumerate(genes):
        aro_id = resolve(card_release, gene)
        if n:
            time.sleep(delay)
        web = parse_page(fetch(aro_id))
        if web["accession"] != aro_id:
            raise CardError(f"asked for {aro_id}, the page is {web['accession']}")
        ours = local_record(card_release, aro_id)
        rows.append({"gene": gene, "aro_id": aro_id, "ours": ours, "web": web, "diff": compare(web, ours)})
    return rows


def unexpected(rows: list[dict]) -> list[str]:
    """Differences not recorded in KNOWN_DIFFERENCES, and recorded ones that no longer occur."""
    problems, seen = [], set()
    for row in rows:
        for field, diff in row["diff"].items():
            key = (row["aro_id"], field)
            seen.add(key)
            if KNOWN_DIFFERENCES.get(key) != diff:
                problems.append(f"{row['gene']} {field}: web has {diff['only_web']}, we have {diff['only_ours']}")
    checked = {row["aro_id"] for row in rows}
    problems += [f"{aro_id} {field}: recorded difference no longer present"
                 for (aro_id, field) in KNOWN_DIFFERENCES if aro_id in checked and (aro_id, field) not in seen]
    return problems


def format_rows(rows: list[dict]) -> str:
    lines = []
    for row in rows:
        status = "match" if not row["diff"] else "DIFFERS"
        lines.append(f"{row['aro_id']}  {row['gene'][:48]:48}  {status}")
        for field, diff in row["diff"].items():
            lines.append(f"    {field}: only on the web {diff['only_web']}, only in our tables {diff['only_ours']}")
    return "\n".join(lines)
