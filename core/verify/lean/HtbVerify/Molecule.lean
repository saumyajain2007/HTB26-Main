/-!
# Molecule graphs and valence

A Lean 4 port of the useful part of the earlier Rocq `Valency.v` / `Molecules.v`
(potatoesandfrenchfries/ai-expo-2026-code), rebuilt for the heavy-atom graphs that
RDKit produces from a SMILES string.

## What this file proves (in general, for every molecule)

* `handshake`: the per-atom bond-order sums add up to exactly twice the total bond
  order. This is the real content behind the Rocq `bond_contributes_to_both`, which
  only stated `x = x`.
* `valenceOkB_iff`, `allValenceOkB_iff`: the Boolean checkers agree with the logical
  statements.
* `valenceOk_of_sublist`: deleting bonds from a molecule that satisfies the valence
  limits leaves it satisfying them, so every bond-subgraph (fragment) of a valid
  molecule is valid.

## What it does NOT prove

* Not that a molecule is stable, synthesisable, safe or active.
* The check is an UPPER BOUND on each atom's bond-order sum. It says nothing about
  implicit hydrogens, and it is deliberately loose for S and P (which allow expanded
  valence), so "passes" means "no atom has more bonds than it could possibly have".
* The graph comes from RDKit; Lean does not check that RDKit parsed the SMILES
  correctly, only the graph it is handed.

## Deliberate departures from the Rocq version

* Elements: the 12 that occur in organic and antibiotic chemistry, not all 118.
* Bond orders are stored doubled (single 2, double 4, triple 6, aromatic 3) so that
  everything is a natural number. Lean has no useful decision procedure for the
  Rocq version's real numbers, and 1.5 is exactly 3/2.
* Bond kinds: single, double, triple, aromatic, the four RDKit emits.
* Formal charge is a field that moves an atom's valence limit by the isoelectronic
  rule (N+ behaves like C, O- like F). The Rocq `expected_formal_charge` computed
  `V - (V - bo) - bo/2`, which is just `bo/2`; it is not ported.
* Halogens are limited to one bond. The Rocq table allowed Cl 7 and Br 5; those only
  matter for perchlorates and similar, which are out of scope here.
* `bond_order_sum_nonneg` was `Admitted` in Rocq. Over `Nat` it needs no proof.
-/

namespace HtbVerify

inductive Element
  | H | B | C | N | O | F | Si | P | S | Cl | Br | I
  deriving DecidableEq, Repr

inductive BondKind
  | single | double | triple | aromatic
  deriving DecidableEq, Repr

/-- Bond order times two. -/
def BondKind.orderX2 : BondKind → Nat
  | .single => 2
  | .double => 4
  | .triple => 6
  | .aromatic => 3

structure Atom where
  id : Nat
  element : Element
  charge : Int := 0
  deriving DecidableEq, Repr

structure Bond where
  a : Nat
  b : Nat
  kind : BondKind
  deriving DecidableEq, Repr

structure Mol where
  atoms : List Atom
  bonds : List Bond
  deriving Repr

/-- Typical maximum valence of the neutral atom. S and P allow expanded valence. -/
def Element.baseValence : Element → Nat
  | .H => 1 | .B => 3 | .C => 4 | .N => 3 | .O => 2 | .F => 1
  | .Si => 4 | .P => 5 | .S => 6 | .Cl => 1 | .Br => 1 | .I => 1

/-- Valence limit after formal charge, by the isoelectronic rule: groups 15 to 17 gain a
bond with each positive charge, boron gains one with each negative charge, and hydrogen,
carbon and silicon lose one for any charge. -/
def Element.valenceLimit (e : Element) (q : Int) : Nat :=
  match e with
  | .H | .C | .Si => e.baseValence - q.natAbs
  | .B => (Int.ofNat e.baseValence - q).toNat
  | _ => (Int.ofNat e.baseValence + q).toNat

/-- Doubled bond-order sum at atom `i`. -/
def bondSumX2 : List Bond → Nat → Nat
  | [], _ => 0
  | b :: bs, i => (if b.a == i || b.b == i then b.kind.orderX2 else 0) + bondSumX2 bs i

/-- Doubled total bond order, each bond counted once. -/
def totalX2 : List Bond → Nat
  | [] => 0
  | b :: bs => b.kind.orderX2 + totalX2 bs

/-- The atom's bond-order sum does not exceed its valence limit. -/
def Mol.ValenceOk (m : Mol) (a : Atom) : Prop :=
  bondSumX2 m.bonds a.id ≤ 2 * a.element.valenceLimit a.charge

instance (m : Mol) (a : Atom) : Decidable (m.ValenceOk a) := by
  unfold Mol.ValenceOk; infer_instance

def Mol.valenceOkB (m : Mol) (a : Atom) : Bool := decide (m.ValenceOk a)

theorem valenceOkB_iff (m : Mol) (a : Atom) : m.valenceOkB a = true ↔ m.ValenceOk a := by
  simp [Mol.valenceOkB]

/-- Every atom satisfies its valence limit. -/
def Mol.AllValenceOk (m : Mol) : Prop := ∀ a ∈ m.atoms, m.ValenceOk a

def Mol.allValenceOkB (m : Mol) : Bool := m.atoms.all m.valenceOkB

theorem allValenceOkB_iff (m : Mol) : m.allValenceOkB = true ↔ m.AllValenceOk := by
  simp [Mol.allValenceOkB, Mol.AllValenceOk, List.all_eq_true, valenceOkB_iff]

/-- The atoms that break their limit, for a named failure. -/
def Mol.violations (m : Mol) : List Nat :=
  (m.atoms.filter (fun a => !m.valenceOkB a)).map Atom.id

/-! ### Handshake lemma -/

private theorem sum_map_add {α} (f g : α → Nat) (l : List α) :
    (l.map (fun x => f x + g x)).sum = (l.map f).sum + (l.map g).sum := by
  induction l with
  | nil => simp
  | cons x xs ih => simp [ih]; omega

/-- One bond touches exactly its two (distinct, listed) endpoints. -/
private theorem touch_sum (ids : List Nat) (hn : ids.Nodup) (x y o : Nat) (hxy : x ≠ y) :
    (ids.map (fun i => if x == i || y == i then o else 0)).sum
      = (if x ∈ ids then o else 0) + (if y ∈ ids then o else 0) := by
  induction ids with
  | nil => simp
  | cons i is ih =>
    have hi : i ∉ is := (List.nodup_cons.mp hn).1
    have hn' : is.Nodup := (List.nodup_cons.mp hn).2
    have ih := ih hn'
    simp only [List.map_cons, List.sum_cons, ih]
    by_cases h1 : x = i
    · subst h1
      have : y ∉ (x :: is) ∨ y ∈ is := by
        by_cases h : y ∈ is
        · exact Or.inr h
        · exact Or.inl (by simp [h, Ne.symm hxy])
      by_cases hy : y ∈ is
      · simp [hy, hi]
      · simp [hy, hi, Ne.symm hxy]
    · by_cases h2 : y = i
      · subst h2
        by_cases hx : x ∈ is
        · simp [hx, hi, h1]
        · simp [hx, hi, h1]
      · have e1 : (x == i || y == i) = false := by simp [h1, h2]
        have m1 : (x ∈ i :: is) ↔ x ∈ is := by simp [h1]
        have m2 : (y ∈ i :: is) ↔ y ∈ is := by simp [h2]
        simp [e1, m1, m2]

/-- Handshake lemma for molecules: the bond-order sums at the atoms add up to twice the
total bond order, provided atom ids are distinct and every bond joins two different
listed atoms. -/
theorem handshake (ids : List Nat) (bs : List Bond)
    (hn : ids.Nodup)
    (hmem : ∀ b ∈ bs, b.a ∈ ids ∧ b.b ∈ ids)
    (hne : ∀ b ∈ bs, b.a ≠ b.b) :
    (ids.map (bondSumX2 bs)).sum = 2 * totalX2 bs := by
  induction bs with
  | nil =>
    simp only [bondSumX2, totalX2, Nat.mul_zero]
    clear hn hmem hne
    induction ids with
    | nil => rfl
    | cons i is ih => simpa using ih
  | cons b bs ih =>
    have hmem' : ∀ c ∈ bs, c.a ∈ ids ∧ c.b ∈ ids := fun c hc => hmem c (List.mem_cons_of_mem _ hc)
    have hne' : ∀ c ∈ bs, c.a ≠ c.b := fun c hc => hne c (List.mem_cons_of_mem _ hc)
    have ih := ih hmem' hne'
    have hb := hmem b (List.mem_cons_self ..)
    have hbne := hne b (List.mem_cons_self ..)
    have : (ids.map (bondSumX2 (b :: bs))).sum
        = (ids.map (fun i => if b.a == i || b.b == i then b.kind.orderX2 else 0)).sum
          + (ids.map (bondSumX2 bs)).sum := by
      rw [← sum_map_add]
      rfl
    rw [this, touch_sum ids hn b.a b.b _ hbne, ih]
    simp [hb.1, hb.2, totalX2]
    omega

/-! ### Fragments of a valid molecule are valid -/

theorem bondSumX2_sublist {bs bs' : List Bond} (h : bs'.Sublist bs) (i : Nat) :
    bondSumX2 bs' i ≤ bondSumX2 bs i := by
  induction h with
  | slnil => simp [bondSumX2]
  | cons b _ ih => simp only [bondSumX2]; omega
  | cons_cons b _ ih => simp only [bondSumX2]; omega

/-- Deleting bonds never breaks a valence limit. -/
theorem valenceOk_of_sublist {m : Mol} {bs' : List Bond} (h : bs'.Sublist m.bonds)
    {a : Atom} (ha : m.ValenceOk a) : ({ m with bonds := bs' } : Mol).ValenceOk a := by
  unfold Mol.ValenceOk at ha ⊢
  exact Nat.le_trans (bondSumX2_sublist h a.id) ha

theorem allValenceOk_of_sublist {m : Mol} {bs' : List Bond} (h : bs'.Sublist m.bonds)
    (hm : m.AllValenceOk) : ({ m with bonds := bs' } : Mol).AllValenceOk :=
  fun a ha => valenceOk_of_sublist h (hm a ha)

end HtbVerify
