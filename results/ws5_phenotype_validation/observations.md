# Observations (exploratory, not pre-registered)

Written after the frozen run, to explain it. Nothing here is a headline, and nothing here changed the
protocol, the code or the result.

## Where the false "ruled out" calls come from

For pairs the laboratory called susceptible but the rule ruled out (arm B, primary scope), the genes
behind the verdict, by number of isolate-drug pairs:

| Species | Drug | Verdict | Gene(s) | Pairs |
| --- | --- | --- | --- | ---: |
| *K. pneumoniae* | amikacin | defeated | AAC(6')-Ib-cr5 | 290 |
| *K. pneumoniae* | tigecycline | partly affected | OqxA, OqxB | 262 |
| *K. pneumoniae* | ceftazidime | partly affected | SHV-11 | 209 |
| *K. pneumoniae* | ceftazidime | partly affected | SHV-1 | 206 |
| *A. baumannii* | amikacin | partly affected | ANT(3'')-IIa | 134 |
| *A. baumannii* | tobramycin | partly affected | AAC(3)-Ia, ANT(3'')-IIa, APH(3'')-Ib | 117 |
| *A. baumannii* | doripenem | partly affected | OXA-66 | 81 |
| *S. aureus* | oxacillin | partly affected | blaR1 | 522 |
| *S. aureus* | ceftaroline | defeated | mecA | 106 |

Most are determinants that are chromosomal, intrinsic or regulatory (SHV-1 and OqxAB in *K.
pneumoniae*, OXA-66 in *A. baumannii*, the blaR1 sensor in *S. aureus*), or that CARD links to a
whole class although the allele acts on a narrow set of its drugs. The rule reads "CARD links this
gene to this class" as "the drug is probably affected", and for these genes that is often wrong.

## Per-drug pattern

From the per-drug table in [results.md](results.md): fluoroquinolones, clindamycin and erythromycin
in *S. aureus*, and ciprofloxacin and levofloxacin in *A. baumannii*, have 0–32% sensitivity as
shipped and 94–100% with the bridge, because their determinants are point mutations or spelled
differently from CARD. Daptomycin, linezolid and vancomycin in *S. aureus* stay at 0–18% in both:
their resistance mechanisms are not represented by the genes AMRFinderPlus reports for these isolates.
Most *A. baumannii* beta-lactams and aminoglycosides have specificity of 0–20% under the class rule,
because almost every isolate carries some determinant linked to the class.

## Still unresolved after the bridge

`blaZ` and `blaI` (*S. aureus*; CARD holds them as a family and a regulator, not a detection model),
bare allele families (`blaTEM`, `blaOXA`, `blaSHV`, `blaADC`), `oqxA`/`oqxB` allele numbers, and
`mrx(A)`. Closing these needs a cited alias table, not a mechanical rule.
