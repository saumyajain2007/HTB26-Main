import unittest
from dataclasses import replace
from docking_support import DockingObservation, supporting_signal

H = 'a' * 64

def obs(variant='wild_type', **changes):
    base = DockingObservation('candidate1', 'PBP', 'PDB_A', variant, 'S123A' if variant == 'mutant' else None, -7.0, 'vina', '1.2.7', 'job1', H, H, 1.5)
    return replace(base, **changes)

class DockingSupportTests(unittest.TestCase):
    def test_separate_from_primary_rank(self):
        result = supporting_signal([obs(), obs('mutant', affinity_kcal_mol=-6.0)])
        self.assertFalse(result['included_in_primary_rank'])
        self.assertEqual(result['comparisons'][0]['delta_score_mutant_minus_wt_kcal_mol'], 1.0)
    def test_fixture_cannot_be_compared(self):
        result = supporting_signal([obs(is_fixture=True), obs('mutant')])
        self.assertIsNone(result['comparisons'][0]['delta_score_mutant_minus_wt_kcal_mol'])
    def test_failed_redock_cannot_be_compared(self):
        result = supporting_signal([obs(), obs('mutant', redock_rmsd_angstrom=2.1)])
        self.assertEqual(result['comparisons'][0]['status'], 'not_comparable')
    def test_requires_mutation_identity(self):
        with self.assertRaises(ValueError):
            supporting_signal([obs('mutant', mutation=None)])
    def test_rejects_mismatched_target(self):
        with self.assertRaises(ValueError):
            supporting_signal([obs(), obs('mutant', target_id='OTHER')])
    def test_rejects_nonfinite(self):
        with self.assertRaises(ValueError):
            supporting_signal([obs(affinity_kcal_mol=float('nan'))])
    def test_missing_wild_type_not_comparable(self):
        result = supporting_signal([obs('mutant')])
        self.assertIsNone(result['comparisons'][0]['delta_score_mutant_minus_wt_kcal_mol'])

if __name__ == '__main__':
    unittest.main()
