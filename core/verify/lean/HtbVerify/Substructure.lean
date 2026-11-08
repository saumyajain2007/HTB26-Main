import HtbVerify.Molecule

/-!
# Substructure certificates

RDKit finds a substructure match; Lean checks it. A match is a mapping from pattern
atom ids to molecule atom ids. `embedsB` checks the mapping and `embedsB_sound` proves
that when it says `true`, the mapping really is a structure-preserving embedding.

So a certificate "this molecule contains a beta-lactam ring" is a mapping plus a
Lean-checked proof that every pattern atom lands on an atom with the same element and
charge, every pattern bond lands on a bond of the same kind, and no two pattern atoms
share an image.

Limits: this verifies a match that someone else found. It does not search, so a
`false` result means "this mapping is not an embedding", not "the motif is absent".
Aromatic bonds only match aromatic bonds, so a pattern written in Kekule form will not
match an RDKit graph. It says nothing about biological activity.
-/

namespace HtbVerify

/-- The molecule has a bond of kind `k` between atoms `x` and `y`, in either direction. -/
def Mol.HasBond (m : Mol) (x y : Nat) (k : BondKind) : Prop :=
  ∃ b ∈ m.bonds, b.kind = k ∧ ((b.a = x ∧ b.b = y) ∨ (b.a = y ∧ b.b = x))

/-- `f` embeds pattern `p` into molecule `m`. -/
structure Embeds (p m : Mol) (f : List (Nat × Nat)) : Prop where
  injective : ∀ x y v, f.lookup x = some v → f.lookup y = some v → x = y
  atoms : ∀ a ∈ p.atoms, ∃ y, f.lookup a.id = some y ∧
    ∃ a' ∈ m.atoms, a'.id = y ∧ a'.element = a.element ∧ a'.charge = a.charge
  bonds : ∀ b ∈ p.bonds, ∃ x y, f.lookup b.a = some x ∧ f.lookup b.b = some y ∧
    m.HasBond x y b.kind

def hasBondB (m : Mol) (x y : Nat) (k : BondKind) : Bool :=
  m.bonds.any fun b => b.kind == k && ((b.a == x && b.b == y) || (b.a == y && b.b == x))

def atomMatchB (m : Mol) (a : Atom) (y : Nat) : Bool :=
  m.atoms.any fun a' => a'.id == y && a'.element == a.element && a'.charge == a.charge

def embedsB (p m : Mol) (f : List (Nat × Nat)) : Bool :=
  decide (f.map Prod.snd).Nodup
    && p.atoms.all (fun a => match f.lookup a.id with
        | none => false
        | some y => atomMatchB m a y)
    && p.bonds.all (fun b => match f.lookup b.a, f.lookup b.b with
        | some x, some y => hasBondB m x y b.kind
        | _, _ => false)

theorem hasBondB_sound {m : Mol} {x y : Nat} {k : BondKind} (h : hasBondB m x y k = true) :
    m.HasBond x y k := by
  unfold hasBondB at h
  rw [List.any_eq_true] at h
  obtain ⟨b, hb, hk⟩ := h
  refine ⟨b, hb, ?_⟩
  simp at hk
  obtain ⟨hk1, hk2⟩ := hk
  exact ⟨hk1, hk2⟩

private theorem mem_of_lookup {f : List (Nat × Nat)} {k v : Nat} (h : f.lookup k = some v) :
    (k, v) ∈ f := by
  obtain ⟨l₁, l₂, rfl, _⟩ := List.lookup_eq_some_iff.mp h
  simp

private theorem pair_snd_inj {f : List (Nat × Nat)} (hnd : (f.map Prod.snd).Nodup)
    {x y v : Nat} (hx : (x, v) ∈ f) (hy : (y, v) ∈ f) : x = y := by
  induction f with
  | nil => simp at hx
  | cons p rest ih =>
    obtain ⟨a, c⟩ := p
    have hc : c ∉ rest.map Prod.snd := (List.nodup_cons.mp hnd).1
    have hr := (List.nodup_cons.mp hnd).2
    simp only [List.mem_cons, Prod.mk.injEq] at hx hy
    have back : ∀ z, (z, c) ∈ rest → False := fun z hz =>
      hc (List.mem_map.mpr ⟨(z, c), hz, rfl⟩)
    rcases hx with ⟨h1, h2⟩ | hx <;> rcases hy with ⟨h3, h4⟩ | hy
    · omega
    · subst h2; exact (back y hy).elim
    · subst h4; exact (back x hx).elim
    · exact ih hr hx hy

theorem embedsB_sound {p m : Mol} {f : List (Nat × Nat)} (h : embedsB p m f = true) :
    Embeds p m f := by
  unfold embedsB at h
  simp only [Bool.and_eq_true, decide_eq_true_eq, List.all_eq_true] at h
  obtain ⟨⟨hnd, hat⟩, hbd⟩ := h
  refine ⟨?_, ?_, ?_⟩
  · intro x y v hx hy
    exact pair_snd_inj hnd (mem_of_lookup hx) (mem_of_lookup hy)
  · intro a ha
    have := hat a ha
    cases hl : f.lookup a.id with
    | none => simp [hl] at this
    | some y =>
      simp only [hl, atomMatchB, List.any_eq_true] at this
      obtain ⟨a', ha', hm⟩ := this
      simp only [Bool.and_eq_true, beq_iff_eq] at hm
      exact ⟨y, rfl, a', ha', hm.1.1, hm.1.2, hm.2⟩
  · intro b hb
    have := hbd b hb
    cases hx : f.lookup b.a with
    | none => simp [hx] at this
    | some x =>
      cases hy : f.lookup b.b with
      | none => simp [hx, hy] at this
      | some y =>
        simp only [hx, hy] at this
        exact ⟨x, y, rfl, rfl, hasBondB_sound this⟩

end HtbVerify
