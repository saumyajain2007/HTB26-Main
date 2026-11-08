# Running NVIDIA GenMol on a Vultr GPU

Status on 8 November 2026: **written, not run.** Nothing here has been executed on Vultr. Facts below
are marked *checked* (read from the cited page that day) or *unchecked* (from memory or inferred, to
verify before relying on them).

## Why GenMol, and what it replaces

[GenMol](https://github.com/NVIDIA-Digital-Bio/genmol) is a masked discrete diffusion model over SAFE
molecule strings with fragment remasking ([paper](https://arxiv.org/abs/2501.06158)). It can generate de
novo, complete a molecule from a fragment or scaffold (linker design, motif extension, scaffold
decoration), and optimise toward an oracle score (hit generation, lead optimisation). *Checked.*

We already have SyntheMol ([generation.md](generation.md)), which is CPU-only and returns synthesisable
molecules, but it can only be guided by a Chemprop 1.x model. GenMol takes any Python oracle, so it can use
the better guide from [results/ci_approaches/summary.md](../results/ci_approaches/summary.md) (other
organisms' data, mean per-fold AUC about 0.67 against about 0.58 without).

Two things GenMol is **not**: it gives no synthesis route, and its output is a hypothesis, never an
antibiotic. Keep every molecule it produces labelled `source: generated`, ranked apart from approved drugs.

## Licences *(checked)*

- Code: Apache-2.0. Weights: the NVIDIA Open Model License. Read that licence before any commercial use.
- The NIM container is governed by different terms (NVIDIA Software License Agreement and product-specific
  terms). This guide uses the open code and weights, not the container.

## Leakage: where GenMol may and may not be used

GenMol is pretrained, and the pages read do not describe its training data *(checked: not stated)*. A
hidden-drug test (abaucin, halicin) must not use a generator that may have seen them, which is why the
repo's rule is never to use pretrained generators there. So:

- Demo candidates: GenMol is fine. Label outputs `generated`.
- Hidden-drug test (#91): keep the SyntheMol lane, with its purged guide model.
- Either way, run `htb_wholecell.leakage.find_leaks` on every batch against the held-out compounds before
  showing it (`python -m eval.leakage_audit --only generated` does this for the SyntheMol batch).

## 1. Get API access

The key in `.env` is named `VULTR_INFERENCE_API_KEY`. On 8 November it returned HTTP 200 from Vultr's
inference API but `401 Unauthorized IP address` from the cloud API (`/v2/account`), so it cannot create
servers from the machine it was tried on. *Checked.*

1. In the Vultr portal open Account, then API, and add the public IP of the machine that will call the API
   to the key's access control (or allow all IPv4 for the lifetime of the task).
2. Test, printing only the status code, never the key:

   ```sh
   KEY=$(grep -E '^VULTR_INFERENCE_API_KEY=' .env | cut -d= -f2-)
   curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $KEY" https://api.vultr.com/v2/account
   ```

3. If it still returns 401 after the IP is allowed, the inference key is not a cloud key: create a cloud API
   key in the portal and store it as `VULTR_API_KEY` in `.env`. `.env` is gitignored; never commit it.

## 2. Cost and plan *(public plan list, checked)*

`GET https://api.vultr.com/v2/plans?type=vcg` (no key needed) listed three NVIDIA L40S plans:

| Plan | GPU memory | vCPU | RAM | Price |
| --- | --- | --- | --- | --- |
| `vcg-l40s-16c-180g-48vram` | 48 GB | 16 | 180 GB | about $1.54 per hour |
| `vcg-l40s-32c-375g-96vram` | 96 GB | 32 | 375 GB | about $3.08 per hour |
| `vcg-l40s-64c-750g-192vram` | 192 GB | 64 | 750 GB | about $6.15 per hour |

Use the smallest. The paper ran GenMol on one A100; an L40S should be enough but that is *unchecked*. The
plan list returned no regions, so find where the plan is offered in the portal or with
`GET /v2/regions/{region}/availability?type=vcg` *(unchecked)*. GPU plans may need access requested from
Vultr first *(unchecked)*.

**Billing runs until the instance is destroyed, including while it is stopped.** A working session of a few
hours costs under about $10. Section 7 is the teardown checklist.

## 3. Create the instance

In the portal (simplest), or with the API *(unchecked; confirm field names in Vultr's API reference)*:

```sh
# os ids: curl -s https://api.vultr.com/v2/os | less    (pick Ubuntu 22.04 x64)
curl -s -X POST https://api.vultr.com/v2/instances \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"region":"<region>","plan":"vcg-l40s-16c-180g-48vram","os_id":<ubuntu-22.04-id>,
       "label":"htb-genmol","sshkey_id":["<your-ssh-key-id>"]}'
```

Note the instance id and IP. Then `ssh root@<ip>` and check the GPU: `nvidia-smi`. If the driver is missing,
install NVIDIA's driver for the OS before going on.

## 4. Install GenMol *(from the repo README; not run)*

```sh
git clone https://github.com/NVIDIA-Digital-Bio/genmol && cd genmol
bash env/setup.sh        # the README's troubleshooting paths point to Python 3.10 in a conda environment
```

Documented fixes: a missing `libXrender.so.1` (install the system package that provides it), an import
error from the `safe` package, and a corrupted SA-score pickle that some oracles load.

Download the V2 checkpoint `model_v2.ckpt` from NVIDIA NGC (an NGC account and its CLI are needed;
the resource is `clara/genmol_v2`), place it in the repo's checkpoints directory, and set its path in
`configs/base.yaml`. *The exact CLI command is on the [NGC page](https://catalog.ngc.nvidia.com/orgs/nvidia/teams/clara/resources/genmol_v2).*

## 5. Run it

From the README *(not run)*:

```sh
python scripts/exps/denovo/run.py -c scripts/exps/frag/hparams_v2.yaml   # de novo, V2
python scripts/exps/frag/run.py                                          # fragment / scaffold conditioned
python scripts/exps/pmo/run.py -o <oracle_name>                          # oracle-guided hit generation
python scripts/exps/lead/run.py ...                                      # lead optimisation, with a similarity threshold
```

The paper's goal-directed tasks took about 2 to 4 hours (hit generation) and 10 minutes (lead optimisation)
per task on one A100. *Checked.*

**Plugging in our oracle** is the part to read before writing: open `scripts/exps/pmo/run.py` and see how
`-o <oracle_name>` resolves a scorer, then add ours there or call GenMol's sampler from our own loop. The
oracle to build is:

```
score = P(active)                        # the leak-controlled ensemble, trained with other organisms' data
        - lambda * std                   # disagreement between members: do not trust what they disagree on
        - penalties                      # 3+ halogens, structural alerts, property-rule failures,
                                         # Gram-negative entry heuristics
        - novelty term                   # similarity to the training set above 0.5
```

The penalties are there because the first SyntheMol batch drove halogens up (91.7% of survivors with three or
more) once the search found a weak signal ([generation.md](generation.md)). The oracle must run on the GPU
box without this machine: ship the fitted scikit-learn models and RDKit with it.

## 6. Bring results back and treat them correctly

1. Copy the generated SMILES back (`scp`), not the weights.
2. Run them through the filter cascade (`htb_wholecell.filters`), the leakage check above, and record GPU
   hours and cost in the cost ledger (#88).
3. Write them with `source: generated`, no rank, no activity claim. They are hypotheses.

## 7. Tear down

- [ ] Results copied and checked.
- [ ] Destroy the instance (portal, or `DELETE /v2/instances/<id>`). Stopping does not stop billing.
- [ ] Confirm in the portal that no instance, block storage or reserved IP remains.
- [ ] Remove the IP from the API key's access control if it was opened for this task.
- [ ] Record the actual cost.

## Unchecked, to verify first

Whether the L40S is enough, whether GPU plans need a quota request, which regions stock the plan, the
cloud-API request fields, NGC download steps, GenMol's pretraining data, whether CPU-only inference works
(the docs do not say), and how the repo registers a custom oracle.
