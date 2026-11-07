"""The AutoDock Vina docking worker (plan.md section 7, docs/engineering/build-reference.md C1-C9).

Two Pythons are involved:

- The docking venv (`$DOCKING_VENV`: Vina, Meeko, RDKit, gemmi, PoseBusters; Linux
  x86_64 wheels only) runs `prepare`, `dock` and `control`. They import nothing from
  the project, so they run there with only this folder on `PYTHONPATH`.
- The project venv (`uv run`) runs `queue`: it claims `dock_jobs` from Postgres and
  starts `dock` in the docking venv as a subprocess, so a job can be killed at its
  time limit.

Importing this package imports neither side's dependencies.
"""

__version__ = "0.1.0"
