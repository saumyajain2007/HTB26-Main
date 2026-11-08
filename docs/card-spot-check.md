# Spot check against CARD's web pages (issue #18)

Run 2026-11-07. For each gene, our CARD 4.0.2 tables were compared with the same gene's page at card.mcmaster.ca: AMR gene family, drug classes and resistance mechanisms, compared by name. CARD's download page lists the August 2026 release as the latest, which is the release we built, so the two should agree.

Code: [spotcheck.py](../core/resistance/htb_resistance/spotcheck.py). Rerun with `uv run python -m htb_resistance spotcheck` (the ten genes below, or name any others), or `uv run pytest core/resistance/tests/test_spotcheck.py -m network`.

## Result

**The ten genes: nine match on all three fields. One, mecA, differs on drug classes.**

| Gene | Mechanism group | Result |
| --- | --- | --- |
| mecA (`ARO:3000617`) | target replacement | **Classes differ** |
| PC1 beta-lactamase, blaZ (`ARO:3000621`) | class A beta-lactamase | Match |
| CTX-M-15 (`ARO:3001878`) | ESBL | Match |
| TEM-1 (`ARO:3000873`) | class A beta-lactamase | Match |
| KPC-2 (`ARO:3002312`) | carbapenemase | Match |
| NDM-1 (`ARO:3000589`) | metallo-beta-lactamase | Match |
| OXA-48 (`ARO:3001782`) | class D carbapenemase | Match |
| *S. aureus* gyrA (`ARO:3003296`) | target alteration, variant model | Match |
| adeB (`ARO:3000775`) | efflux pump | Match |
| armA (`ARO:3000858`) | 16S rRNA methyltransferase | Match |

I also ran 16 more genes, the others in the three typical isolates used for the profile tests and a few extras: ErmC, SHV-1, AAC(6')-Ib-cr1, OXA-23, OXA-51, OXA-66, ADC-30, VIM-2, tet(M), vanA, oqxA, *S. aureus* parC, *A. baumannii* gyrA and parC, and *E. coli* gyrA. Fifteen match. **mecC differs in the same way as mecA.** I then checked the other two members of the family, mecB and mecD, and they differ too. In all, 28 genes: 24 match on every field, 4 differ, and all four are the PBP2-like family (mecA, mecB, mecC, mecD).

## The difference

| | Drug classes |
| --- | --- |
| Website, mecA | penicillin beta-lactam, cephalosporin, **carbapenem, monobactam** |
| Our tables, mecA | penicillin beta-lactam, cephalosporin |
| Website, mecC | penicillin beta-lactam, cephalosporin, **carbapenem, monobactam** |
| Our tables, mecC | penicillin beta-lactam |
| Website, mecB and mecD | carbapenem, cephalosporin, monobactam (and nothing else) |
| Our tables, mecB and mecD | penicillin beta-lactam |

What was checked:

- The downloaded files agree with our tables. The raw `card.json` lists two classes for mecA, and `aro.obo` has only two drug-level links for it (methicillin and ceftaroline). So this is not an ingest error.
- The website's page for the whole family, PBP2-like beta-lactam resistant peptidoglycan transpeptidase (`ARO:3009312`), also lists four classes, while the downloaded ontology gives that family only penicillin beta-lactam. The website therefore holds links that the August 2026 download does not.
- I do not know why. It may be a curation change on the live site that is not in the release files, or the site may infer classes the files do not. I have not asked CARD.

Family and mechanism names agree with the website for every gene checked.

## Why it matters

Carbapenems do not treat MRSA, so the website's classes are the clinically expected ones. On our tables alone, a profile with mecA has no carbapenem in `defeated_classes`. A ranking built on that profile would treat carbapenems as unaffected by an MRSA isolate, which is the wrong way round for an evasion score. It only matters for *S. aureus* and other mecA/mecC carriers, and monobactams are irrelevant for Gram-positive organisms anyway.

## What was done about it (#66)

A small curated supplement, [supplement.json](../core/resistance/htb_resistance/supplement.json), now adds classes that a published source supports. It is kept apart from CARD's data, so a rebuild from the downloads still reproduces CARD exactly, and each class it adds appears in the profile with its own evidence item (`source: curated`, release `curated_supplement-1`) and its citations.

- **mecA: carbapenem added.** **mecC: carbapenem and cephalosporin added.** Source: Gajdacs 2019, *Antibiotics* 8(2):52 (PMID 31052511), whose abstract states that MRSA with an altered PBP2a/c is resistant to "all penicillins, cephalosporins, and carbapenems". A network test checks each PubMed id against its title, year, first author and the quoted words.
- **Monobactam not added.** The website lists it, but I found no source, and monobactams have no activity against Gram-positive bacteria, so there is no resistance to attribute.
- **mecB and mecD left as CARD's download has them.** I found no citation for these rarer genes. A profile with them still lacks carbapenem and cephalosporin.
- **The comparison above is unchanged**, because it compares CARD's download with its website, not our profiles.
- If a later CARD release adds these classes, the supplement skips any class CARD already has, and a test reports it so the entry can be removed.

## Added for #17

The profile tests of #17 (see [profiling-known-cases.md](profiling-known-cases.md)) assert expected classes for 17 genes. Seven of them had not been checked above, so on 2026-11-07 I ran the same comparison for them: **tet(K), msrA, OXA-1, oqxB, FosA, ADC-25 and adeJ. All seven match the website on family, drug classes and mechanisms.** With these, every gene in those tests has been compared with its CARD page, which is 35 genes in all (31 match, the same four PBP2-like genes differ).

## Limits

- Names only. Drug-level links and the page's Classification tree were not compared.
- 35 of 6,451 models. The ten were chosen to cover each mechanism group, so a problem confined to a family I did not test would not show up.
- The website is a live page. A later CARD release or site change can shift the result. The network test records the four differences above and fails if a new one appears or one of these disappears.
