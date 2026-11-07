/-!
# Property rules for candidate molecules

Descriptor values arrive from RDKit as scaled integers, because Lean cannot reason
about floating-point numbers: molecular weight and polar surface area times 10,
logP times 100.

What this file proves, in general (not per molecule):

* `passesB_iff`: the Boolean checker agrees with the logical statement.
* `passes_mono`: if a molecule passes and a second molecule is no larger in every
  descriptor, the second passes too.
* `passes_relax`: loosening every threshold never rejects a molecule that passed.
* `oral_implies_relaxed`: anything passing the oral rules passes the relaxed
  antibiotic rules.

What it does NOT prove: that a molecule is safe, selective or active. A certificate
says the encoded rules hold, and nothing about biology.

The threshold numbers must match `htb_verify/rules.py`; `tests/test_lean_sync.py`
checks that.
-/

namespace HtbVerify

structure Desc where
  mwX10 : Nat
  logpX100 : Int
  hbd : Nat
  hba : Nat
  rotBonds : Nat
  psaX10 : Nat
  deriving Repr

structure Thresholds where
  mwX10 : Nat
  logpX100 : Int
  hbd : Nat
  hba : Nat
  rotBonds : Nat
  psaX10 : Nat
  deriving Repr

/-- Lipinski (2001) and Veber (2002) oral drug-likeness. -/
def oralDruglike : Thresholds :=
  { mwX10 := 5000, logpX100 := 500, hbd := 5, hba := 10, rotBonds := 10, psaX10 := 1400 }

/-- Placeholder limits for antibiotic candidates. To be calibrated on approved antibiotics. -/
def antibioticRelaxed : Thresholds :=
  { mwX10 := 12000, logpX100 := 500, hbd := 12, hba := 20, rotBonds := 15, psaX10 := 2500 }

/-- A molecule passes when every descriptor is within its threshold. -/
def Desc.Passes (t : Thresholds) (d : Desc) : Prop :=
  d.mwX10 ≤ t.mwX10 ∧ d.logpX100 ≤ t.logpX100 ∧ d.hbd ≤ t.hbd ∧
  d.hba ≤ t.hba ∧ d.rotBonds ≤ t.rotBonds ∧ d.psaX10 ≤ t.psaX10

instance (t : Thresholds) (d : Desc) : Decidable (d.Passes t) := by
  unfold Desc.Passes; infer_instance

def Desc.passesB (t : Thresholds) (d : Desc) : Bool := decide (d.Passes t)

theorem passesB_iff (t : Thresholds) (d : Desc) : d.passesB t = true ↔ d.Passes t := by
  simp [Desc.passesB]

/-- Pointwise ordering of descriptors. -/
def Desc.Le (a b : Desc) : Prop :=
  a.mwX10 ≤ b.mwX10 ∧ a.logpX100 ≤ b.logpX100 ∧ a.hbd ≤ b.hbd ∧
  a.hba ≤ b.hba ∧ a.rotBonds ≤ b.rotBonds ∧ a.psaX10 ≤ b.psaX10

/-- Pointwise ordering of thresholds. -/
def Thresholds.Le (s t : Thresholds) : Prop :=
  s.mwX10 ≤ t.mwX10 ∧ s.logpX100 ≤ t.logpX100 ∧ s.hbd ≤ t.hbd ∧
  s.hba ≤ t.hba ∧ s.rotBonds ≤ t.rotBonds ∧ s.psaX10 ≤ t.psaX10

theorem passes_mono {t : Thresholds} {a b : Desc} (hab : a.Le b) (hb : b.Passes t) :
    a.Passes t := by
  unfold Desc.Le at hab
  unfold Desc.Passes at hb ⊢
  omega

theorem passes_relax {s t : Thresholds} {d : Desc} (hst : s.Le t) (hd : d.Passes s) :
    d.Passes t := by
  unfold Thresholds.Le at hst
  unfold Desc.Passes at hd ⊢
  omega

theorem oral_le_relaxed : oralDruglike.Le antibioticRelaxed := by
  unfold Thresholds.Le oralDruglike antibioticRelaxed
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_⟩ <;> decide

theorem oral_implies_relaxed {d : Desc} (h : d.Passes oralDruglike) :
    d.Passes antibioticRelaxed :=
  passes_relax oral_le_relaxed h

end HtbVerify
