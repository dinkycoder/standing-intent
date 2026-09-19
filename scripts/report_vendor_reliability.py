"""Aggregate evals/results/*.json into per-vendor Beta-Binomial reliability
scores and print a report.

See docs/superpowers/specs/2026-09-19-week7-trained-model-design.md.

evals/results/ is git-ignored -- this reads whatever reports exist locally
on THIS machine. It is real memory across runs, not durable or CI-visible
history.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python scripts/report_vendor_reliability.py` from the repo root --
# same shim as scripts/run_claude_planner_evals.py, same reason.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.ml.reliability import vendor_reliability_from_reports  # noqa: E402
from evals.stats import wilson_interval  # noqa: E402

# Reporting threshold only -- nothing reads this script's output
# automatically (see the design spec's "Out of scope").
_SUSPICIOUS_MEAN_THRESHOLD = 0.9


def main(results_dir: Path = Path("evals/results")) -> dict[str, dict]:
    paths = sorted(Path(results_dir).glob("*.json"))
    scores = vendor_reliability_from_reports(paths)
    _print_table(scores)
    return scores


def _print_table(scores: dict[str, dict]) -> None:
    if not scores:
        print("No vendor_outcomes found in any report under the given directory.")
        return

    header = f"{'vendor_id':<24} {'mean':>8} {'95% CI (raw rate)':>20} {'n':>5}"
    print(header)
    print("-" * len(header))
    all_high = True
    for vendor_id, s in sorted(scores.items()):
        if s["n_observations"] > 0:
            lo, hi = wilson_interval(s["successes"], s["n_observations"])
        else:
            lo, hi = (s["mean"], s["mean"])
        ci_text = f"[{lo:.3f}, {hi:.3f}]"
        print(f"{vendor_id:<24} {s['mean']:>8.3f} {ci_text:>20} {s['n_observations']:>5d}")
        # A vendor counts as "suspiciously reliable" from its raw evidence
        # (zero failures, or successes swamping failures 9:1), not from the
        # Beta(1,1) posterior mean -- the uniform prior pulls small samples
        # toward 0.5, so e.g. 7 successes/0 failures gives mean 8/9 ~= 0.889,
        # which would wrongly fall BELOW a flat 0.9 mean threshold even
        # though it's a perfect small record that should trigger the caveat.
        if not (s["failures"] == 0 or s["successes"] >= 9 * s["failures"]):
            all_high = False
    print()
    if all_high:
        print(
            "All observed vendors show near-100% reliability; this reflects "
            "SyntheticExecutor's current failure model, not a claim about "
            "real-world vendor trustworthiness. See "
            "docs/superpowers/specs/2026-09-19-week7-trained-model-design.md's "
            "Known limitations."
        )


if __name__ == "__main__":
    main()
