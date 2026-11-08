# Candidate generation with SyntheMol (issue #86)

Candidates come from an existing open-source generator, not one built here (decision in #82). Code: [generate.py](../core/wholecell/htb_wholecell/generate.py); environment: [deploy/synthemol/setup.sh](../deploy/synthemol/setup.sh). Measured 8 November 2026.

## What SyntheMol is

SyntheMol (MIT; Swanson et al., *Nature Machine Intelligence* 2024; github.com/swansonk14/SyntheMol) searches a space of building blocks joined by named reactions, guided by a bioactivity model, with a Monte Carlo tree search. Every molecule it proposes comes with the building blocks and reactions that make it, so a synthesis route is part of the output. The paper applies it to *A. baumannii*. It runs on CPU: its README says a laptop (16 GB, 8 to 16 CPUs) is enough, so no GPU plan is needed and a plain Vultr Cloud Compute VM can host it.

This uses the PyPI release **1.0.4**. The repository's README describes a newer 2.x with reinforcement learning that is not on PyPI; it was not used.

## Why it lives in its own environment

SyntheMol pins an old Chemprop (1.x). The Chemprop 2 ensemble from #85 cannot share an environment with it and cannot load its checkpoints. So:

- SyntheMol runs in its own virtual environment, only ever through subprocess calls.
- **The guide model is not the #85 model.** It is a Chemprop 1.x model trained by the same recipe (RDKit 2D descriptor features, class balancing, 30 epochs, scaffold-based validation carve-out) on the same rows. It was not separately evaluated beyond Chemprop's own validation split, so nothing in this document says how good a guide it is.

## Fixes needed to run SyntheMol 1.0.4 with current libraries

Each one was hit by running it, and `deploy/synthemol/setup.sh` applies all three.

1. `descriptastorus` imports `six` without declaring it: `six` is installed beside it.
2. Chemprop 1.x calls `np.float`, `np.int` and `np.object`, removed in NumPy 1.24. Pinning NumPy below 1.24 breaks pandas, so a small `.pth` shim restores the three aliases, inside that environment only.
3. PyTorch 2.6 and later refuse to load a Chemprop 1.x checkpoint by default. `TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1` is set for those subprocesses. **Only the checkpoint this module has just trained itself is ever loaded this way; never use it on a checkpoint from an untrusted source.**

## Leakage

Before any generation, `assert_generator_inputs_clean` runs the spec's leakage assertion over everything the generator touches: the guide model's training rows and the 139,493 building blocks. For abaucin (RS-102895) and halicin (SU3327) it passed: none of the 5,334 training rows and none of the building blocks is identical to either or above 0.5 Tanimoto of either. No pretrained SyntheMol model is ever used. After generation, molecules identical to or above 0.5 Tanimoto of a held-out compound are removed from the batch and counted.

A different leak to know about: the guide model's training data is `liu_train`, whose active labels come from the abaucin paper's own screen. Abaucin itself is not in that screen (it was found by applying the model to the Hub), which is why this is clean, but the generator is guided toward what that screen called active.

## Building blocks: licence not resolved

The building blocks are Enamine REAL building blocks, shipped inside the PyPI package. SyntheMol's code is MIT; **Enamine's terms of use restrict copying, republishing and distribution and limit products to laboratory research use**, and I found nothing saying whether the shipped list is covered by an exception. So: use the file locally for this run, **do not commit it, and do not publish the building-block list**. Generated molecules and the guide model's scores are ours to show. Verify with Enamine before publishing anything that lists building blocks.

## Running it

```bash
deploy/synthemol/setup.sh ~/.cache/htb/synthemol-env     # once, about a minute
```

```python
from htb_wholecell import generate
held = generate.held_out_smiles(release, ["RS-102895", "SU3327"])
rows, removed = generate.training_rows(release, held)            # purged training rows
generate.assert_generator_inputs_clean(held, [r["smiles"] for r in rows],
                                       generate.building_block_smiles(blocks_csv))
generate.write_guide_csv(guide_csv, rows)
generate.prepare_guide(env, work, guide_csv, seed=0)             # trains the guide, scores every block (slow, cached)
generate.search(env, work, n_rollout=N, seed=0, name="run1")     # one search
generate.import_generated(...); generate.write_batch(...)        # standardise, dedupe, label, record provenance
```

Scoring the building blocks with Chemprop's descriptor features runs at roughly 130 molecules a second on one CPU, so that step takes about 18 minutes; it is done once per guide model and reused by every search.

Every generated molecule is labelled `source: generated`, deduplicated by InChIKey, and carries its novelty (highest Tanimoto to any training molecule and to any training active), its seed, its batch and the building blocks it was built from. Keep them visibly separate from approved drugs wherever they are shown.
