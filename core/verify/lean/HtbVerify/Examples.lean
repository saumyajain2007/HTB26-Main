import HtbVerify.Substructure

/-!
# Worked certificates

Concrete molecules, checked by `decide`. If any of these stop holding, `lake build`
fails, so the claims below cannot silently rot.

Graphs are heavy-atom graphs as RDKit gives them (hydrogens implicit), which is why the
valence check is an upper bound.
-/

namespace HtbVerify
open Element BondKind

private def at' (i : Nat) (e : Element) (q : Int := 0) : Atom := { id := i, element := e, charge := q }
private def bd (a b : Nat) (k : BondKind) : Bond := { a := a, b := b, kind := k }

/-- Benzylpenicillin, `CC1(C)SC2C(NC(=O)Cc3ccccc3)C(=O)N2C1C(=O)O`. -/
def penicillinG : Mol where
  atoms :=
    [ at' 0 C, at' 1 C, at' 2 C, at' 3 S, at' 4 C, at' 5 C, at' 6 N, at' 7 C, at' 8 O
    , at' 9 C, at' 10 C, at' 11 C, at' 12 C, at' 13 C, at' 14 C, at' 15 C
    , at' 16 C, at' 17 O, at' 18 N, at' 19 C, at' 20 C, at' 21 O, at' 22 O ]
  bonds :=
    [ bd 0 1 single, bd 1 2 single, bd 1 3 single, bd 3 4 single, bd 4 5 single
    , bd 5 6 single, bd 6 7 single, bd 7 8 double, bd 7 9 single, bd 9 10 single
    , bd 10 11 aromatic, bd 11 12 aromatic, bd 12 13 aromatic, bd 13 14 aromatic
    , bd 14 15 aromatic, bd 15 10 aromatic
    , bd 5 16 single, bd 16 17 double, bd 16 18 single, bd 18 4 single
    , bd 18 19 single, bd 19 1 single, bd 19 20 single, bd 20 21 double, bd 20 22 single ]

/-- Every atom of benzylpenicillin is within its valence limit. -/
theorem penicillinG_valence : penicillinG.AllValenceOk :=
  (allValenceOkB_iff _).mp (by decide)

/-- The 2-azetidinone (beta-lactam) ring: N1, C2(=O), C3, C4. -/
def betaLactam : Mol where
  atoms := [ at' 0 N, at' 1 C, at' 2 O, at' 3 C, at' 4 C ]
  bonds := [ bd 0 1 single, bd 1 2 double, bd 1 3 single, bd 3 4 single, bd 4 0 single ]

/-- A match, as RDKit would report it: pattern atom to penicillin atom. -/
def betaLactamMatch : List (Nat × Nat) := [(0, 18), (1, 16), (2, 17), (3, 5), (4, 4)]

theorem betaLactam_valence : betaLactam.AllValenceOk :=
  (allValenceOkB_iff _).mp (by decide)

/-- Benzylpenicillin contains a beta-lactam ring, certified by a checked embedding. -/
theorem penicillinG_has_betaLactam : Embeds betaLactam penicillinG betaLactamMatch :=
  embedsB_sound (by decide)

/-- Mapping the lactam carbonyl onto the wrong atom is rejected: the checker is not
vacuous. -/
theorem betaLactam_bad_match :
    embedsB betaLactam penicillinG [(0, 18), (1, 20), (2, 17), (3, 5), (4, 4)] = false := by
  decide

/-- Nitromethane with charge-separated nitro, `C[N+](=O)[O-]`, is within its limits. -/
def nitromethane : Mol where
  atoms := [ at' 0 C, at' 1 N 1, at' 2 O, at' 3 O (-1) ]
  bonds := [ bd 0 1 single, bd 1 2 double, bd 1 3 single ]

theorem nitromethane_valence : nitromethane.AllValenceOk :=
  (allValenceOkB_iff _).mp (by decide)

/-- The same atoms with the charges dropped give N a bond order of 4 against a limit of
3, and the failure is named. -/
def nitromethaneNoCharge : Mol where
  atoms := [ at' 0 C, at' 1 N, at' 2 O, at' 3 O ]
  bonds := nitromethane.bonds

theorem nitromethaneNoCharge_rejected :
    nitromethaneNoCharge.allValenceOkB = false ∧ nitromethaneNoCharge.violations = [1] := by
  decide

/-- Pentavalent carbon is rejected. -/
def pentavalentCarbon : Mol where
  atoms := [ at' 0 C, at' 1 C, at' 2 C, at' 3 C, at' 4 C, at' 5 C ]
  bonds := [ bd 0 1 single, bd 0 2 single, bd 0 3 single, bd 0 4 single, bd 0 5 single ]

theorem pentavalentCarbon_rejected :
    pentavalentCarbon.allValenceOkB = false ∧ pentavalentCarbon.violations = [0] := by
  decide

/-- Dropping bonds from penicillin G keeps it valid, an instance of `allValenceOk_of_sublist`. -/
example : ({ penicillinG with bonds := penicillinG.bonds.tail } : Mol).AllValenceOk :=
  allValenceOk_of_sublist (List.tail_sublist _) penicillinG_valence

end HtbVerify
