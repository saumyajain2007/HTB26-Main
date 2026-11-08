# Docking test

Runs the repo's real AutoDock Vina worker (`app/worker/htb_worker/dock.py`, Vina 1.2.7, exhaustiveness 8,
seed 42) on 34 jobs and compares the scores with what we already have. It answers two questions:

1. **Reproducibility.** Does Vina give the same scores as the 10 real jobs stored in `data/docking/`
   (JAK2, CRBN, BCL2 candidates and redock controls)? These come from `jobs.json`, group `repro`.
2. **Bacterial calibration.** On the four bacterial structures we prepared (GyrB 3G7B and 3U2K, LpxC
   2VES and 3P3E), how far apart are the structure's own crystal ligand, which should bind, and five
   drug-sized molecules that are not known to bind (ibuprofen, caffeine, aspirin, glucose, paracetamol)?
   This shows where a binding threshold could sit. Group `bacterial`.

`compare.py` writes `results/report.md`. The decoys are not validated non-binders, and there are only four
positives, so the report shows whether the two groups separate. It is not a calibrated cut-off.

## How long it takes

Measured: **606 s (about 10 minutes) for all 34 jobs** on an Apple M5 (10 cores) running the repo's
amd64 docking image under emulation. Venetoclax (6O0K) is the slowest single job (about 2.5 minutes);
most jobs take 5 to 25 seconds. Native Linux x86_64 should be faster. `--only repro` or
`--only bacterial` runs half of it.

## How to run

Vina publishes **Linux x86_64 wheels only**, so on a Mac use Docker, and on Windows use WSL2 or Docker.

```bash
# From the repo root. Any machine with Docker:
docking-test/run.sh docker

# Linux x86_64 or WSL2 (Ubuntu) with python3.11 and python3.11-venv:
docking-test/run.sh native

# Options after the mode: --only repro | --only bacterial, --cpu N
```

Then read `docking-test/results/report.md`. The run can be stopped and restarted; finished jobs are skipped
(`--redo` to start over).

### On a rented server (e.g. Vultr)

Any Linux x86_64 instance with 8 or more vCPUs works. Pick Ubuntu, then:

```bash
sudo apt-get update && sudo apt-get install -y git docker.io
git clone <this repo> && cd HTB26-Main        # use the branch you want to test
sudo docking-test/run.sh docker
```

Copy `docking-test/results/report.md` and `results.json` back when it finishes, then delete the instance
so it stops billing.

## Does a GPU help?

No. AutoDock Vina 1.2.7 runs on the CPU only, so the laptop's GPU would sit idle. GPU docking programs
(Vina-GPU, AutoDock-GPU) are different engines whose scores are not comparable with the Vina scores the
app and its threshold use. More CPU cores is what speeds this up.
