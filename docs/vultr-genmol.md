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

The key in `.env` is named `VULTR_INFERENCE_API_KEY`. On 8 November it first returned `401 Unauthorized IP
address` from the cloud API, because the key's access control did not include this machine; after the
IP was allowed, `GET /v2/account` returned 200 with full account permissions (`root`, `provisioning`,
`billing` and others), a $100 credit and no instances, bare-metal servers or SSH keys. *Checked.*

1. If it returns 401 again, add the calling machine's public IP to the key's access control in the Vultr
   portal (Account, then API).
2. Test, printing only the status code, never the key:

   ```sh
   KEY=$(grep -E '^VULTR_INFERENCE_API_KEY=' .env | cut -d= -f2-)
   curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $KEY" https://api.vultr.com/v2/account
   ```

3. The key can do anything on the account, including spend and delete. Treat it as a secret (`.env` is
   gitignored; never commit it), and consider a key restricted to provisioning for this task.
4. Check whose account and credit it is before spending from it.

## 2. Cost and plan *(checked 8 November 2026, with the key)*

The L40S plans in Vultr's public list (`vcg-l40s-*`) were **not stocked in any region**. These GPU plans
were (hourly is the monthly price divided by 730; billing is hourly, capped monthly):

| Plan | GPU memory | vCPU | RAM | About | Regions with stock |
| --- | --- | --- | --- | --- | --- |
| `vcg-a16-6c-60g-16vram` | 16 GB | 6 | 60 GB | $0.47 per hour | atl, blr, ewr, fra, lhr, nrt, ord, sgp, sjc |
| `vcg-a16-12c-120g-32vram` | 32 GB | 12 | 120 GB | $0.94 per hour | blr, ewr, fra, lhr, nrt, ord, sgp, sjc |
| `vcg-a40-24c-120g-48vram` | 48 GB | 24 | 120 GB | $1.71 per hour | lax |
| `vcg-a100-12c-120g-80vram` | 80 GB | 12 | 120 GB | $2.40 per hour | ewr |

GenMol is an 89M-parameter model, so memory is not the constraint; the paper ran it on one A100. The
suggested plan is `vcg-a16-12c-120g-32vram` in `ewr` (the 12 vCPUs and 120 GB help the scoring oracle,
and an A100 is in the same region if the A16 is too slow). Whether an A16 is fast enough is *unchecked*.
Availability changes, so re-query before creating:

```sh
curl -s -H "Authorization: Bearer $KEY" "https://api.vultr.com/v2/regions/ewr/availability?type=vcg"
```

**Billing runs until the instance is destroyed, including while it is stopped.** A working session of a few
hours is a few dollars. Section 7 is the teardown checklist.

## 3. Create the instance

In the portal (simplest), or with the API *(unchecked; confirm field names in Vultr's API reference)*:

```sh
# Ubuntu 22.04 LTS x64 is os_id 1743 (checked). No SSH key is registered on the account yet:
# create one first with POST /v2/ssh-keys (name, ssh_key), or add one in the portal.
curl -s -X POST https://api.vultr.com/v2/instances \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"region":"ewr","plan":"vcg-a16-12c-120g-32vram","os_id":1743,
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

Whether an A16 is fast enough, whether the create call needs a GPU quota request, the exact
cloud-API request fields, NGC download steps, GenMol's pretraining data, whether CPU-only inference works
(the docs do not say), and how the repo registers a custom oracle.
