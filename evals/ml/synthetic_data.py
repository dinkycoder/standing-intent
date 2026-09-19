"""Synthetic training data for evals/ml/price_classifier.py.

See docs/superpowers/specs/2026-09-19-week7-trained-model-design.md.

Labels are sampled from a logistic function of a price's z-score within its
category -- not a hard cutoff -- specifically so LogisticRegression is the
correct model for this generating process (not an arbitrary baseline pick),
and so calibration has real, checkable content: the trained model's
predicted probabilities can be checked against the TRUE generating
probabilities at a given z-score, not just eyeballed for plausibility.

The exact coefficients below were empirically verified, not guessed -- see
this module's own tests and the implementation plan's Task 5 for why an
earlier candidate set was rejected (it produced a label distribution so
imbalanced a trained classifier barely beat a naive majority-class
baseline).
"""

from __future__ import annotations

import numpy as np

_CATEGORIES = ("weather-data", "news-data", "stock-data")
# Each category's TRUE price distribution -- fixed, not sampled per-row, so
# a category's distribution is a stable thing a classifier can learn from
# repeated observations. (mean, std) in USDC.
_CATEGORY_PRICE_PARAMS = {
    "weather-data": (0.03, 0.01),
    "news-data": (0.05, 0.015),
    "stock-data": (0.10, 0.03),
}
_LABELS = ("accept", "escalate", "reject")
# Logistic log-odds of {escalate, reject} relative to {accept}, as a linear
# function of the price z-score. Verified empirically (see module
# docstring) to produce a non-degenerate 3-class label distribution.
_LOGIT_INTERCEPTS = {"escalate": -0.5, "reject": -4.0}
_LOGIT_SLOPES = {"escalate": 1.0, "reject": 3.0}
_REFERENCE_PRICE_ASSIGNED_FRACTION = 0.7


def generate_offers(n: int, seed: int) -> tuple[list[dict], list[str]]:
    """Returns (features, labels), each of length n. See module docstring
    for the generating process."""
    rng = np.random.default_rng(seed)
    categories = rng.choice(_CATEGORIES, size=n)
    features: list[dict] = []
    labels: list[str] = []

    for category in categories:
        mu, sigma = _CATEGORY_PRICE_PARAMS[category]
        price = float(rng.normal(mu, sigma))
        price = max(price, 0.001)  # a negative/zero price is not a valid offer
        z = (price - mu) / sigma

        logits = {"accept": 0.0}
        for label in ("escalate", "reject"):
            logits[label] = _LOGIT_INTERCEPTS[label] + _LOGIT_SLOPES[label] * z
        exp_logits = {k: np.exp(v) for k, v in logits.items()}
        total = sum(exp_logits.values())
        probs = [exp_logits[label] / total for label in _LABELS]
        label = rng.choice(_LABELS, p=probs)

        has_reference = rng.random() < _REFERENCE_PRICE_ASSIGNED_FRACTION
        if has_reference:
            reference_price = mu  # the category's true mean is the "declared" reference
            reference_price_ratio = price / reference_price
        else:
            reference_price_ratio = 1.0  # placeholder, ignored via the missing flag

        budget_cap = mu * 3  # an arbitrary but fixed-per-row-category budget context
        budget_utilization = price / budget_cap

        features.append({
            "price_usdc": price,
            "category": category,
            "price_zscore_in_category": z,
            "reference_price_ratio": reference_price_ratio,
            "reference_price_missing": not has_reference,
            "budget_utilization": budget_utilization,
        })
        labels.append(str(label))

    return features, labels
