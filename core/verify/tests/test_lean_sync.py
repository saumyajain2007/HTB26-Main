"""The thresholds in rules.py and in Rules.lean must be identical."""

import re
from pathlib import Path

from htb_verify.certify import LEAN_THRESHOLDS
from htb_verify.rules import RULE_SETS

RULES_LEAN = Path(__file__).resolve().parents[1] / "lean" / "HtbVerify" / "Rules.lean"
FIELDS = {"mwX10": "mw_x10", "logpX100": "logp_x100", "hbd": "hbd", "hba": "hba",
          "rotBonds": "rot_bonds", "psaX10": "psa_x10"}


def _lean_block(const: str) -> dict[str, int]:
    text = RULES_LEAN.read_text(encoding="utf-8")
    m = re.search(rf"def {const} : Thresholds :=\s*\{{(.*?)\}}", text, re.S)
    assert m, f"{const} not found in Rules.lean"
    return {k: int(v) for k, v in re.findall(r"(\w+) := (-?\d+)", m.group(1))}


def test_python_and_lean_thresholds_match():
    for py_name, const in LEAN_THRESHOLDS.items():
        lean = _lean_block(const)
        py = RULE_SETS[py_name]
        for lean_field, py_field in FIELDS.items():
            assert lean[lean_field] == getattr(py, py_field), (py_name, lean_field)
