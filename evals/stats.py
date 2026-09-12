"""Confidence intervals for the harness's binomial rate metrics.

pass^1, pass^k, and best_price_capture_rate are all point estimates of a
binomial proportion computed from n_trials <= 8 by default (see
evals/harness.py: _PASS_K_VALUES). At that sample size a bare rate is exactly
the kind of unverified-looking-precise number CLAUDE.md's "no unverified
constants" and "tests must catch wrong-but-plausible output" rules exist to
flag elsewhere in this repo -- pass^1 = 0.75 at n=8 could plausibly be
anywhere from ~0.35 to ~0.97. This module is the fix: report the interval
alongside the point estimate, always.

Quantic "Mathematics for AI Engineering" -- Probability Distributions,
"Z-Scores and the Standard Normal Distribution."
"""

from __future__ import annotations

import math


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (~95% coverage at z=1.96).

    Preferred over the naive Wald interval (p_hat +/- z*sqrt(p_hat*(1-p_hat)/n))
    because Wald badly under-covers exactly where this harness lives: small n
    (n_trials defaults to 8) and p_hat near 0 or 1 (a stub agent scoring
    pass^1 = 0, or a tuned agent scoring pass^1 = 1.0 -- Wald returns a
    zero-width interval at both, which is never honest). Wilson stays inside
    [0, 1] and widens instead of collapsing at those extremes.
    """
    if n <= 0:
        raise ValueError(f"n must be >= 1, got {n}")
    if not (0 <= successes <= n):
        raise ValueError(f"successes={successes} out of range for n={n}")
    p_hat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2 * n)) / denom
    half_width = (z * math.sqrt(p_hat * (1 - p_hat) / n + z2 / (4 * n * n))) / denom
    lo = max(0.0, center - half_width)
    hi = min(1.0, center + half_width)
    return (lo, hi)


def pass_k_interval(
    successes: int, n_trials: int, k: int, z: float = 1.96
) -> tuple[float, float]:
    """Approximate CI for pass^k, by transforming the Wilson interval on p.

    pass_k() (evals/harness.py) estimates p**k, where p is the true per-trial
    success probability -- see its docstring. x -> x**k is monotone increasing
    on [0, 1], so bounding p bounds p**k the same way: (p_lo**k, p_hi**k) is a
    valid interval for p**k at (approximately) the same confidence level as the
    underlying Wilson interval on p. This is NOT an exact interval for the
    hypergeometric point estimator pass_k() returns -- that estimator and p**k
    coincide only asymptotically -- but it is honest about what it bounds, and
    that beats reporting no interval at all.
    """
    lo, hi = wilson_interval(successes, n_trials, z)
    return (lo**k, hi**k)
