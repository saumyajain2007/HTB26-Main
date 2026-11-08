# Structural Lean proofs over molecule graphs (#49)

Source: `core/verify/lean/HtbVerify/{Molecule,Substructure,Examples}.lean`. Build with `cd core/verify/lean && lake build`.

This is a port of the useful part of `Valency.v` and `Molecules.v` from the earlier Rocq project (potatoesandfrenchfries/ai-expo-2026-code), rebuilt for the heavy-atom graphs RDKit produces.

## What is proved

| Theorem | Statement |
| --- | --- |
| `handshake` | For distinct atom ids and bonds joining two different listed atoms, the per-atom bond-order sums add to exactly twice the total bond order. |
| `valenceOkB_iff`, `allValenceOkB_iff` | The Boolean valence checkers agree with the logical statements. |
| `valenceOk_of_sublist`, `allValenceOk_of_sublist` | Deleting bonds from a molecule within its valence limits leaves it within them, so every bond-subgraph of a valid molecule is valid. |
| `embedsB_sound` | If the substructure checker accepts a mapping, the mapping is a real embedding: injective, element and charge preserving, and every pattern bond lands on a molecule bond of the same kind. |

`Examples.lean` applies these to real structures, checked by `decide`:

- Benzylpenicillin is within its valence limits.
- Benzylpenicillin contains a beta-lactam ring, by a checked embedding. A deliberately wrong mapping is rejected.
- Nitromethane passes with charges and fails without them, with the failing atom named.
- Pentavalent carbon is rejected, with the failing atom named.

The proofs use only Lean's standard axioms (`propext`, `Classical.choice`, `Quot.sound`) and no `sorry`.

## What is not proved

- Nothing here says a molecule is stable, synthesisable, safe or active.
- The valence check is an upper bound on each atom's bond-order sum. It ignores implicit hydrogens, and it is loose for S and P, which allow expanded valence.
- Lean checks the graph it is given, not that RDKit parsed the SMILES correctly.
- The substructure checker verifies a match found elsewhere (RDKit). It does not search, so `false` means "this mapping is not an embedding", not "the motif is absent". Aromatic bonds match only aromatic bonds.
- Not yet connected to `htb_verify/certify.py`, so the running pipeline does not call these proofs.

## How it differs from the Rocq version

- 12 organic-chemistry elements, not 118.
- Bond orders are stored doubled as natural numbers, instead of reals.
- Formal charge shifts the valence limit by the isoelectronic rule. The Rocq `expected_formal_charge` reduced to `bo/2` and is not ported.
- Halogens allow one bond (Rocq allowed Cl 7, Br 5).
- The Rocq `bond_order_sum_nonneg` was `Admitted` and `bond_contributes_to_both` was `x = x`. Neither is ported; `handshake` replaces the second.

## Suggested wording

"Valence limits and substructure matches can be machine-checked in Lean 4 over molecule graphs, including proofs that the check is monotone under deleting bonds and that a substructure certificate is sound." Avoid "formally verified molecule" or "verified safe".

## Next step if time allows

Add a `certify_structure` path in `htb_verify/certify.py`: export the RDKit graph and the SMARTS match as a Lean file that imports `HtbVerify.Examples`-style definitions, so valence and the beta-lactam motif appear next to the property-rule certificate.
