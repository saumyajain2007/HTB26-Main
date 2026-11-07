# Curated combinations table (WS1)

A small table of well-known beta-lactam / beta-lactamase-inhibitor pairs, every row with a
citation and a record of how that citation was checked. Data:
[combinations.json](../core/resistance/htb_resistance/data/combinations.json). Code:
[combinations.py](../core/resistance/htb_resistance/combinations.py). Tests:
[test_combinations.py](../core/resistance/tests/test_combinations.py).

```
uv run python -m htb_resistance.combinations                      # structure and citations present
uv run python -m htb_resistance.combinations --citations          # resolve every citation online
uv run python -m htb_resistance.combinations --release-dir data/card/releases/<version>
uv run pytest core/resistance/tests/test_combinations.py          # add -m network for the online check
```

11 pairs: 7 approved in the US, 4 investigational.

| Pair | Inhibitor class | Inhibits | Does not inhibit | Status |
| --- | --- | --- | --- | --- |
| ceftazidime-avibactam | diazabicyclooctane | A, C, D (OXA-48) | B; OXA-23 minimal | approved |
| aztreonam-avibactam | DBO + MBL-stable partner | A, B, C, D | — | approved 2025-02-07 |
| sulbactam-durlobactam | diazabicyclooctane | A, C, D (OXA-23, OXA-24/40, OXA-48) | B unclear | approved 2023-05-23 |
| meropenem-vaborbactam | cyclic boronate | A (mainly KPC), C | B, D | approved |
| imipenem-cilastatin-relebactam | diazabicyclooctane | A, C | B, D (OXA-48, OXA-23/24/58) | approved |
| cefepime-enmetazobactam | penicillanic acid sulfone | A (ESBL), D (OXA-48) | B | approved |
| ceftolozane-tazobactam | penicillanic acid sulfone | A (not KPC), C partial, D | B, KPC | approved |
| cefepime-taniborbactam | bicyclic boronate | A, B, C, D | IMP, NDM-9/30, VIM-83 | investigational |
| cefepime-zidebactam | diazabicyclooctane | A, C | D | investigational |
| meropenem-nacubactam | diazabicyclooctane | A, C | B, D | investigational |
| meropenem-xeruborbactam | bicyclic boronate | A, B, C, D | none stated | investigational |

## The source check

Run 2026-11-07. Coverage claims for all 11 rows come from one article, read directly
rather than cited from memory:

> Cercenado E, Candel FJ. Classification and applicability of new beta-lactamase
> inhibitors. *Rev Esp Quimioter*. 2025 Oct 24;38(Suppl 1):21-26.
> DOI 10.37201/req/s01.03.2025, PMID 41159226.

| What | How it was checked | Result |
| --- | --- | --- |
| Coverage claims, all 11 rows | The article's full text was fetched and read (PMC12584905) | Taken from its narrative text |
| DOI and PMID for that article | Read off the article's own citation block on the page | Not independently resolved; see the gap below |
| Sulbactam-durlobactam approval | FDA press announcement fetched and read | Xacduro, 23 May 2023, HABP/VABP from *A. baumannii-calcoaceticus* complex |
| Aztreonam-avibactam approval | AbbVie news release fetched and read | Emblaveo, 7 February 2025, complicated intra-abdominal infections |
| Cefepime-taniborbactam status | Drugs.com approval history fetched and read | **Not approved.** Complete Response Letter 23 February 2024, requesting chemistry, manufacturing and controls data; reportedly no safety or efficacy concerns and no new trials requested |
| Table structure, vocabulary, contradictions | `check_table`, offline | 11 pairs, 0 problems |

### Where the cited article contradicts itself

Its Table 1 and its narrative text disagree in three places. The text is the more cautious
of the two and is what the data file follows; each case is recorded in that row's
`source_conflicts` rather than being quietly resolved.

- **Enmetazobactam and class C.** Table 1 lists class C as inhibited, the text says it is
  not. Class C is left out.
- **Zidebactam and classes B and D.** Table 1 lists both, the text says class D is not
  inhibited and does not clearly state class B. Only A and C are claimed.
- **Durlobactam and class B.** The text reports activity against some NDM-producing
  *E. coli* and Table 1 lists some NDMs, but class B inhibition is not clearly asserted. It
  is left out rather than claimed.

## Why no ARO or ChEMBL ids

[ontology-check.md](ontology-check.md) records that two candidate drug classes had
`aro_id: null` with a name only, which would have made them invisible to the evasion rule,
and that a guessed id is worse than no id. So no ids are written into this table from
memory. `resolve_against_card(table, release_dir)` maps every partner and inhibitor name
onto a real release's `aro_terms` and returns `None` where CARD holds no such name, so the
ids can be added once looked up. Until then a join from this table to CARD has to go
through names, which the contract warns against.

## Gaps, in the order worth closing

1. **No citation has been resolved online yet.** `--citations` does it, and
   `pytest -m network` runs the same check, but this environment's egress proxy refused
   doi.org, pubmed, fda.gov, news.abbvie.com and businesswire with 403, so it has not
   actually been executed. Run it once on a normal network before the table is trusted.
2. **Six approval dates are missing.** Only the two confirmed against a primary source are
   recorded; the rest are `null` rather than filled from memory. Add each from its FDA
   label or approval history, with an `approval_source`.
3. **One source for coverage.** Every row leans on the same review. A second independent
   source per row, ideally each product's FDA label, would make a disagreement visible
   instead of invisible.
4. **No ARO ids**, as above.
5. **The classic pairs are absent**: amoxicillin-clavulanate, ampicillin-sulbactam,
   piperacillin-tazobactam and ticarcillin-clavulanate. They are the best known of all, but
   the article read here does not cover them, and the rule for this table is that a row
   cites a source that was actually read. They should be added from their labels.
6. **Xeruborbactam's profile claims all four Ambler classes with no exclusions.** An
   unqualified claim that broad deserves a second source before anything relies on it.

## What it is for

WS4's evasion rule: if a profile's defeated classes include an enzyme an inhibitor covers,
the pair may restore the partner beta-lactam, which is the difference between "this
cephalosporin is defeated" and "this cephalosporin plus avibactam is not". `defeats(table,
"KPC")` and `defeats(table, "B")` answer that by enzyme or by Ambler class.

The table says nothing about dose, breakpoints or clinical outcome, and an inhibitor
covering an enzyme in vitro does not mean the pair works in a patient.
