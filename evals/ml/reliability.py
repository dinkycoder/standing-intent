"""Beta-Binomial vendor-reliability tracking.

See docs/superpowers/specs/2026-09-19-week7-trained-model-design.md.

A vendor's reliability is a Beta(alpha, beta) posterior over "does this
vendor's settlement verify when paid" -- built from EvalReport.vendor_outcomes,
which evals.harness.run_eval already populates from
ExecutedPurchase.verified. This module never scans a directory itself;
vendor_reliability_from_reports takes an explicit list of paths, so it's
testable against fixture files without touching the real (git-ignored,
machine-local) evals/results/.
"""

from __future__ import annotations

from pathlib import Path

from evals.models import EvalReport

# Uniform prior: no vendor is assumed reliable or unreliable before any
# evidence exists.
_PRIOR_ALPHA = 1.0
_PRIOR_BETA = 1.0


def beta_update(alpha: float, beta: float, success: bool) -> tuple[float, float]:
    """One Beta-Binomial posterior update: a success increments alpha, a
    failure increments beta."""
    if success:
        return (alpha + 1, beta)
    return (alpha, beta + 1)


def posterior_mean(alpha: float, beta: float) -> float:
    return alpha / (alpha + beta)


def vendor_reliability_from_reports(report_paths: "list[Path]") -> dict[str, dict]:
    """Folds every EvalReport.vendor_outcomes entry in report_paths through
    beta_update per vendor_id, starting from the uniform prior."""
    posteriors: dict[str, tuple[float, float]] = {}
    for path in report_paths:
        report = EvalReport.model_validate_json(Path(path).read_text(encoding="utf-8"))
        for vendor_id, outcome in report.vendor_outcomes.items():
            alpha, beta = posteriors.get(vendor_id, (_PRIOR_ALPHA, _PRIOR_BETA))
            for _ in range(outcome.successes):
                alpha, beta = beta_update(alpha, beta, success=True)
            for _ in range(outcome.failures):
                alpha, beta = beta_update(alpha, beta, success=False)
            posteriors[vendor_id] = (alpha, beta)

    return {
        vendor_id: {
            "alpha": alpha,
            "beta": beta,
            "mean": posterior_mean(alpha, beta),
            "successes": int(alpha - _PRIOR_ALPHA),
            "failures": int(beta - _PRIOR_BETA),
            "n_observations": int(alpha + beta - _PRIOR_ALPHA - _PRIOR_BETA),
        }
        for vendor_id, (alpha, beta) in posteriors.items()
    }
