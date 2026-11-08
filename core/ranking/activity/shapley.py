"""Per-candidate feature attribution, in readable terms, with its own correctness check.

The `shap` package is not a dependency here, so this is Kernel SHAP implemented directly:
sample coalitions, weight them by the Shapley kernel, and solve the weighted least squares
problem under the constraint that the attributions sum to f(x) - E[f]. For a small feature
set the exact Shapley values are computed by enumerating all 2^n coalitions instead, and
:func:`attribute` says which route it took.

Having both is the point. ``test_kernel_shap_matches_the_exact_values`` checks the sampled
estimator against the enumerated ground truth, so the implementation is verified rather than
trusted. An attribution that is merely plausible is worse than none: it will be read as the
reason a compound was ranked, and nobody checks a plausible number.

**Efficiency is asserted, not assumed.** Shapley values satisfy sum(phi) = f(x) - E[f]. Every
result carries its ``additivity_error``, and :func:`attribute` refuses a result whose error
exceeds the tolerance rather than returning attributions that do not account for the score.

**Readability stops where the mapping does.** Descriptor names are given a readable form.
Fingerprint bits are *not*: mapping a bit back to a substructure needs the fingerprint's own
bit-info from RDKit, and without it the bit is reported as a bit, not as an invented
substructure.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import asdict, dataclass

import numpy as np

MAX_EXACT_FEATURES = 14
DEFAULT_SAMPLES = 2048
ADDITIVITY_TOLERANCE = 1e-6
EXACT, KERNEL = "exact", "kernel"

# Generic cheminformatics descriptors, in words. Extend or override with `readable=`.
DESCRIPTOR_LABELS = {
    "mw": "molecular weight",
    "molecular_weight": "molecular weight",
    "clogp": "lipophilicity (clogP)",
    "logp": "lipophilicity (logP)",
    "tpsa": "polar surface area",
    "hbd": "hydrogen-bond donors",
    "hba": "hydrogen-bond acceptors",
    "rotatable_bonds": "rotatable bonds",
    "aromatic_rings": "aromatic rings",
    "rings": "ring count",
    "fraction_csp3": "sp3 carbon fraction",
    "formal_charge": "formal charge",
    "heavy_atoms": "heavy atom count",
    "qed": "drug-likeness (QED)",
}


class AttributionError(RuntimeError):
    """The attribution could not be computed or does not account for the score."""


def readable_name(name: str, readable: dict | None = None) -> str:
    """A descriptor name in words. A fingerprint bit stays a bit."""
    if readable and name in readable:
        return readable[name]
    key = name.strip().lower()
    if key in DESCRIPTOR_LABELS:
        return DESCRIPTOR_LABELS[key]
    for prefix in ("fp_", "bit_", "ecfp_", "morgan_"):
        if key.startswith(prefix):
            return (f"fingerprint bit {key[len(prefix):]} "
                    f"(no substructure mapping available)")
    return name.replace("_", " ")


@dataclass(frozen=True)
class Attribution:
    """One candidate's attributions, with the check that they add up."""

    candidate: str
    base_value: float          # E[f] over the background set
    prediction: float          # f(x)
    values: dict               # feature name -> contribution
    method: str
    additivity_error: float
    n_background: int
    n_coalitions: int

    def top(self, k: int = 5, readable: dict | None = None) -> list:
        """The k features that moved this prediction most, largest first."""
        ranked = sorted(self.values.items(), key=lambda kv: abs(kv[1]), reverse=True)[:k]
        return [{"feature": name,
                 "label": readable_name(name, readable),
                 "contribution": round(float(value), 4),
                 "direction": "increases" if value > 0 else
                              ("decreases" if value < 0 else "no effect")}
                for name, value in ranked]

    def sentence(self, k: int = 3, readable: dict | None = None) -> str:
        parts = [f"{f['label']} {f['direction']} it by {abs(f['contribution']):.3f}"
                 for f in self.top(k, readable)]
        return f"driven by {'; '.join(parts)}" if parts else "no feature moved the score"

    def as_dict(self) -> dict:
        out = asdict(self)
        out["values"] = {k: round(float(v), 6) for k, v in self.values.items()}
        for key in ("base_value", "prediction", "additivity_error"):
            out[key] = round(float(out[key]), 6)
        return out


def _masked_prediction(predict, x: np.ndarray, background: np.ndarray,
                       mask: np.ndarray) -> float:
    """E[f(x) | features in `mask` kept], by substituting background values elsewhere.

    The interventional (marginal) expectation: rows are built from x on the masked features
    and from each background row on the rest, and the predictions are averaged.
    """
    rows = np.tile(background, (1, 1)).astype(float)
    rows[:, mask] = x[mask]
    out = np.asarray(predict(rows), dtype=float).ravel()
    if out.size != rows.shape[0]:
        raise AttributionError("the model must return one prediction per row")
    return float(out.mean())


def exact_shapley(predict, x, background) -> dict:
    """Exact Shapley values by enumerating every coalition. For small feature sets."""
    x = np.asarray(x, dtype=float).ravel()
    background = np.atleast_2d(np.asarray(background, dtype=float))
    n = x.size
    if n > MAX_EXACT_FEATURES:
        raise AttributionError(f"{n} features is too many to enumerate "
                               f"(limit {MAX_EXACT_FEATURES}); use kernel_shap")
    indices = range(n)
    cache = {}

    def value(subset) -> float:
        key = frozenset(subset)
        if key not in cache:
            mask = np.zeros(n, dtype=bool)
            mask[list(key)] = True
            cache[key] = _masked_prediction(predict, x, background, mask)
        return cache[key]

    phi = np.zeros(n)
    for i in indices:
        others = [j for j in indices if j != i]
        for size in range(len(others) + 1):
            weight = math.factorial(size) * math.factorial(n - size - 1) / math.factorial(n)
            for subset in itertools.combinations(others, size):
                phi[i] += weight * (value(set(subset) | {i}) - value(set(subset)))
    return {"phi": phi, "n_coalitions": len(cache)}


def kernel_shap(predict, x, background, *, n_samples: int = DEFAULT_SAMPLES,
                seed: int = 0) -> dict:
    """Kernel SHAP: weighted least squares over sampled coalitions.

    The empty and full coalitions are handled exactly (they fix the intercept and the sum)
    rather than being given a large finite weight, which is what the Shapley kernel asks for
    and what keeps the additivity error at machine precision.
    """
    x = np.asarray(x, dtype=float).ravel()
    background = np.atleast_2d(np.asarray(background, dtype=float))
    n = x.size
    if n < 1:
        raise AttributionError("no features to attribute")
    base = _masked_prediction(predict, x, background, np.zeros(n, dtype=bool))
    full = _masked_prediction(predict, x, background, np.ones(n, dtype=bool))
    if n == 1:
        return {"phi": np.array([full - base]), "base": base, "prediction": full,
                "n_coalitions": 2}

    rng = np.random.default_rng(seed)
    sizes = np.arange(1, n)
    # Shapley kernel weight for a coalition of size s, before the 1/C(n, s) that the
    # uniform sampling of coalitions of that size already supplies.
    size_weight = np.array([(n - 1) / (s * (n - s)) for s in sizes], dtype=float)
    size_probability = size_weight / size_weight.sum()

    seen = {}
    for _ in range(int(n_samples)):
        size = int(rng.choice(sizes, p=size_probability))
        chosen = tuple(sorted(rng.choice(n, size=size, replace=False)))
        seen[chosen] = seen.get(chosen, 0) + 1

    masks, weights, targets = [], [], []
    for chosen, count in seen.items():
        mask = np.zeros(n, dtype=bool)
        mask[list(chosen)] = True
        masks.append(mask.astype(float))
        weights.append(float(count))
        targets.append(_masked_prediction(predict, x, background, mask) - base)
    design = np.asarray(masks)
    weight = np.asarray(weights)
    target = np.asarray(targets)

    # Impose sum(phi) = full - base exactly by eliminating the last coefficient.
    total = full - base
    reduced = design[:, :-1] - design[:, -1:]
    adjusted = target - design[:, -1] * total
    root = np.sqrt(weight)[:, None]
    solution, *_ = np.linalg.lstsq(reduced * root, adjusted * root.ravel(), rcond=None)
    phi = np.append(solution, total - solution.sum())
    return {"phi": phi, "base": base, "prediction": full, "n_coalitions": len(seen)}


def attribute(candidate: str, predict, x, background, feature_names, *,
              n_samples: int = DEFAULT_SAMPLES, seed: int = 0,
              tolerance: float = ADDITIVITY_TOLERANCE) -> Attribution:
    """Attribute one candidate's prediction, exactly where that is feasible.

    Raises if the attributions do not sum to f(x) - E[f] within ``tolerance``. Attributions
    that do not account for the prediction are not a weaker explanation; they are a wrong one.
    """
    x = np.asarray(x, dtype=float).ravel()
    background = np.atleast_2d(np.asarray(background, dtype=float))
    names = list(feature_names)
    if len(names) != x.size:
        raise AttributionError(f"{len(names)} feature names for {x.size} features")
    if background.shape[1] != x.size:
        raise AttributionError("the background set must have the same features as x")
    if background.shape[0] == 0:
        raise AttributionError("attribution needs a background set to average over")

    if x.size <= MAX_EXACT_FEATURES:
        out = exact_shapley(predict, x, background)
        phi = out["phi"]
        base = _masked_prediction(predict, x, background, np.zeros(x.size, dtype=bool))
        prediction = _masked_prediction(predict, x, background, np.ones(x.size, dtype=bool))
        method, coalitions = EXACT, out["n_coalitions"]
    else:
        out = kernel_shap(predict, x, background, n_samples=n_samples, seed=seed)
        phi, base, prediction = out["phi"], out["base"], out["prediction"]
        method, coalitions = KERNEL, out["n_coalitions"]

    error = abs(float(phi.sum()) - (prediction - base))
    if error > tolerance:
        raise AttributionError(
            f"{candidate}: attributions sum to {phi.sum():.6f} but the prediction moved "
            f"{prediction - base:.6f} (error {error:.2e} > {tolerance:.0e}). The explanation "
            f"does not account for the score, so it is not reported.")
    return Attribution(candidate=candidate, base_value=base, prediction=prediction,
                       values=dict(zip(names, phi.tolist())), method=method,
                       additivity_error=error, n_background=background.shape[0],
                       n_coalitions=coalitions)
