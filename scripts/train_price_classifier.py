"""Generate synthetic offers, train the price classifier, report metrics,
and save the trained artifact.

See docs/superpowers/specs/2026-09-19-week7-trained-model-design.md.

LOCAL TRAINING RUN -- deterministic given the fixed seed (42): re-running
this script reproduces the committed evals/ml/price_classifier.joblib.
Not gated in CI as a training step; the already-committed artifact is what
evals.ml.price_classifier.load() reads at import/use time elsewhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python scripts/train_price_classifier.py` from the repo root --
# same shim as scripts/run_claude_planner_evals.py, same reason.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sklearn.calibration import calibration_curve  # noqa: E402
from sklearn.metrics import classification_report  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

from evals.ml.price_classifier import DEFAULT_ARTIFACT_PATH, train  # noqa: E402
from evals.ml.synthetic_data import generate_offers  # noqa: E402

# Both fixed and recorded here -- see the implementation plan's Global
# Constraints for why these exact values, and Task 5's note on why an
# earlier set of label-generation constants was rejected.
_N = 5000
_SEED = 42


def main(artifact_path: Path = DEFAULT_ARTIFACT_PATH) -> dict:
    features, labels = generate_offers(n=_N, seed=_SEED)
    x_train, x_test, y_train, y_test = train_test_split(
        features, labels, test_size=0.2, random_state=_SEED, stratify=labels
    )

    clf = train(x_train, y_train, seed=_SEED)

    y_pred = [max((p := clf.predict_proba(f)), key=p.get) for f in x_test]
    report_text = classification_report(y_test, y_pred, digits=3)
    accuracy = sum(1 for yp, yt in zip(y_pred, y_test) if yp == yt) / len(y_test)

    # Calibration: is predicted P(escalate) close to the empirical
    # escalate-rate, binned by decile? escalate (not accept or reject) is
    # the one class with real ambiguity on both sides -- it's the
    # interesting calibration question.
    escalate_proba = [clf.predict_proba(f)["escalate"] for f in x_test]
    escalate_true = [1 if y == "escalate" else 0 for y in y_test]
    prob_true, prob_pred = calibration_curve(
        escalate_true, escalate_proba, n_bins=10, strategy="quantile"
    )

    clf.save(artifact_path)

    _print_report(accuracy, report_text, prob_true, prob_pred)
    return {"accuracy": accuracy, "n": _N, "seed": _SEED}


def _print_report(accuracy, report_text, prob_true, prob_pred) -> None:
    print(f"n={_N}  seed={_SEED}  test accuracy={accuracy:.3f}")
    print()
    print(report_text)
    print("Calibration (escalate, one-vs-rest, decile bins):")
    print(f"{'predicted P(escalate)':>24} {'empirical rate':>16}")
    for p_pred, p_true in zip(prob_pred, prob_true):
        print(f"{p_pred:>24.3f} {p_true:>16.3f}")
    print()
    print(
        "LOCAL TRAINING RUN -- deterministic given seed=42; re-running "
        "reproduces the committed evals/ml/price_classifier.joblib."
    )


if __name__ == "__main__":
    main()
