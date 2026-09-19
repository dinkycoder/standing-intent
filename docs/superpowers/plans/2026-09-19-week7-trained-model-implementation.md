# Week 7 — Trained Model v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship two real, tested, gradeable ML artifacts — a `LogisticRegression`
accept/reject/escalate price classifier trained on synthetic, probabilistically
labeled data, and a Beta-Binomial vendor-reliability tracker computed by
aggregating the harness's own local eval history — without changing any live
agent decision path.

**Architecture:** A new `evals/ml/` package (`synthetic_data.py`,
`price_classifier.py`, `reliability.py`) plus two new scripts
(`scripts/train_price_classifier.py`, `scripts/report_vendor_reliability.py`)
mirroring the existing `scripts/run_*_evals.py` convention. `evals/models.py`
gains a `VendorOutcome` model and `EvalReport.vendor_outcomes`, populated by
`evals/harness.py::run_eval` from `ExecutedPurchase.verified` — the one
signal every executor already produces.

**Tech Stack:** `scikit-learn==1.9.1` (new dependency, pulls `numpy`,
`scipy`, `joblib` transitively — all confirmed to install cleanly against
this project's pinned Python/pydantic stack during design verification),
pydantic v2 (already a dependency), pytest (already the project's
convention).

**Spec:** `docs/superpowers/specs/2026-09-19-week7-trained-model-design.md`

## Global Constraints

- Neither `evals/agents/claude_planner.py` nor `evals/guardrail.py::check_purchase`
  is touched anywhere in this plan. Both artifacts are built, trained, and
  reported — not wired into a live decision. See the spec's "Scope decisions
  made during brainstorming" #2 for why.
- `generate_offers(n, seed)` uses **exactly** `n=5000, seed=42` wherever the
  training/evaluation pipeline actually runs (Tasks 6 and 7) — both values
  were verified empirically during design (not guessed) to produce a
  reproducible, non-trivial classification problem. Do not change either
  value without re-verifying the downstream accuracy/calibration numbers
  this plan states as expected.
- The exact label-generation coefficients in `evals/ml/synthetic_data.py`
  (`_LOGIT_INTERCEPTS`, `_LOGIT_SLOPES`) were tuned and empirically verified
  during design — an earlier candidate set produced a classifier that only
  marginally beat a naive "always predict accept" baseline (83.2% model vs.
  82.4% majority-class baseline for the earlier constants — a test that
  would have silently passed a nearly-useless model). The constants in this
  plan's Task 5 are the corrected ones; do not substitute different values
  without re-running the full verification (generate at `n=5000, seed=42`,
  train, and confirm accuracy exceeds the majority-class baseline by a real
  margin) — this is exactly the class of "wrong-but-plausible" mistake
  CLAUDE.md rule 4 asks tests to catch, not just this plan's own numbers.
- `evals/results/` is git-ignored. `evals/ml/reliability.py`'s aggregation
  function takes an explicit list of file paths — it never scans a
  directory itself — so every test in this plan uses `tmp_path` fixture
  files, never the real, git-ignored, machine-local directory.
- `EvalReport.vendor_outcomes` is additive and defaults to `{}`. No existing
  `EvalReport` construction site (in any already-merged code, or in any
  already-written `evals/results/*.json` file) needs to change or breaks.

---

### Task 1: Add `VendorOutcome` and `EvalReport.vendor_outcomes`

**Files:**
- Modify: `evals/models.py` (add `VendorOutcome` class before `EvalReport`;
  add one field to `EvalReport`)
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `evals.models.VendorOutcome(successes: int = 0, failures: int = 0)`,
  `EvalReport.vendor_outcomes: dict[str, VendorOutcome]` — Task 2 populates
  this field; Task 3 (`evals/ml/reliability.py`) reads it back out of
  serialized `EvalReport` JSON.
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_models.py`. First, update the top-of-file import line:

```python
from evals.models import AgentResult, EvalReport, Escalation, Purchase, TaskSpec, VendorOutcome
```

Then add these tests (near the other `EvalReport`-focused tests):

```python
def test_vendor_outcome_defaults_to_zero():
    outcome = VendorOutcome()
    assert outcome.successes == 0
    assert outcome.failures == 0


def test_eval_report_vendor_outcomes_defaults_to_empty_for_pre_week7_reports():
    # A full, valid EvalReport payload with every pre-Week-7 field present
    # and no vendor_outcomes key at all -- proves backward compatibility
    # with every report this project has already produced. Deliberately an
    # inline literal, not a real file from the git-ignored evals/results/
    # directory, which does not exist on a fresh clone or in CI.
    payload = """{
      "task_id": "sample", "agent_id": "fake", "date_utc": "2026-09-07",
      "base_seed": 0, "n_trials": 8,
      "outcomes": ["pass", "pass", "pass", "pass", "pass", "pass", "pass", "pass"],
      "pass_1": 1.0, "pass_1_ci": [0.68, 1.0],
      "pass_k": {"4": 1.0, "8": 1.0},
      "pass_k_ci": {"4": [0.68, 1.0], "8": [0.68, 1.0]},
      "touchpoints_per_basket": 1.0, "budget_violations": 0,
      "best_price_capture_rate": 1.0, "best_price_capture_rate_ci": [0.68, 1.0],
      "cost_per_completed_tx_usdc": "0", "escalation_rate": 0.0,
      "escalation_reasons": {}, "unverified_claims": 0, "settled_tx_hashes": []
    }"""
    report = EvalReport.model_validate_json(payload)
    assert report.vendor_outcomes == {}


def test_eval_report_vendor_outcomes_roundtrips_through_json():
    payload = """{
      "task_id": "sample", "agent_id": "fake", "date_utc": "2026-09-07",
      "base_seed": 0, "n_trials": 1, "outcomes": ["pass"],
      "pass_1": 1.0, "pass_1_ci": [0.68, 1.0],
      "pass_k": {}, "pass_k_ci": {},
      "touchpoints_per_basket": 1.0, "budget_violations": 0,
      "best_price_capture_rate": 1.0, "best_price_capture_rate_ci": [0.68, 1.0],
      "cost_per_completed_tx_usdc": "0.01", "escalation_rate": 0.0,
      "escalation_reasons": {}, "unverified_claims": 0, "settled_tx_hashes": [],
      "vendor_outcomes": {"v1": {"successes": 3, "failures": 1}}
    }"""
    report = EvalReport.model_validate_json(payload)
    assert report.vendor_outcomes == {"v1": VendorOutcome(successes=3, failures=1)}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_models.py -k vendor_outcome -v`
Expected: `ImportError: cannot import name 'VendorOutcome'` for all three
(the import line itself fails, since `VendorOutcome` doesn't exist yet).

- [ ] **Step 3: Add the model and field**

In `evals/models.py`, insert this class immediately before `class EvalReport(_Model):`:

```python
class VendorOutcome(_Model):
    """A vendor's observed settlement outcomes within one eval run --
    ExecutedPurchase.verified is the one signal every executor already
    produces (evals/executor.py). Folded into a Beta-Binomial posterior by
    evals.ml.reliability, which reads this back out of serialized
    EvalReport JSON files."""
    successes: int = 0
    failures: int = 0
```

Then add one field to `EvalReport`, after the existing `settled_tx_hashes` field:

```python
    settled_tx_hashes: list[str] = Field(default_factory=list)
    vendor_outcomes: dict[str, VendorOutcome] = Field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/models.py tests/test_models.py
git commit -m "Add VendorOutcome and EvalReport.vendor_outcomes

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push
```

---

### Task 2: Populate `vendor_outcomes` in `evals/harness.py::run_eval`

**Files:**
- Modify: `evals/harness.py`
- Test: `tests/test_harness.py`

**Interfaces:**
- Consumes: `evals.models.VendorOutcome` (Task 1), `executed_per_trial`
  (already computed inside `run_eval`, unchanged).
- Produces: nothing new for later tasks — Task 3's reliability aggregation
  reads `EvalReport.vendor_outcomes` from serialized JSON files, not from
  this function directly.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_harness.py`, near the other `run_eval`-focused tests.
This needs one new fixture executor:

```python
class _AlternatingVerifiedExecutor:
    """Pays whatever target it's given; alternates verified True/False by
    call count, so a test can assert vendor_outcomes splits correctly."""
    def __init__(self):
        self._calls = 0

    def pay(self, target, *, max_amount):
        self._calls += 1
        verified = self._calls % 2 == 1  # 1st, 3rd, ... calls succeed
        return ExecutedPurchase(
            vendor_id=target, url=None, amount_paid=Decimal("0.01"),
            pay_to=None, tx_hash=None, verified=verified, resource=None)


def test_run_eval_populates_vendor_outcomes_from_verified_flag(sample_task):
    @agent("mixed-reliability-buyer")
    def run_task(task, rng_seed, executor):
        p = executor.pay("v1", max_amount=Decimal("999"))
        return AgentResult(
            purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
            touchpoints=1)

    report = run_eval(sample_task, run_task, n_trials=4, executor=_AlternatingVerifiedExecutor())
    assert report.vendor_outcomes["v1"].successes == 2
    assert report.vendor_outcomes["v1"].failures == 2


def test_run_eval_vendor_outcomes_is_empty_when_no_purchase_happens(sample_task):
    @agent("pure-escalator")
    def run_task(task, rng_seed, executor):
        return AgentResult(purchases=[], touchpoints=2)

    report = run_eval(sample_task, run_task, n_trials=2)
    assert report.vendor_outcomes == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_harness.py -k vendor_outcomes -v`
Expected: `AttributeError` — `report.vendor_outcomes` exists (Task 1 added
the field, defaulting to `{}`), so `test_run_eval_vendor_outcomes_is_empty_when_no_purchase_happens`
actually PASSES already (expected, harmless — the default `{}` already
satisfies it). `test_run_eval_populates_vendor_outcomes_from_verified_flag`
FAILS: `assert {}["v1"]...` raises `KeyError`, since nothing populates the
field yet.

- [ ] **Step 3: Populate the field in `run_eval`**

In `evals/harness.py`, update the model import line. Replace:

```python
from evals.models import AgentResult, EvalReport, TaskSpec, Vendor
```

with:

```python
from evals.models import AgentResult, EvalReport, TaskSpec, Vendor, VendorOutcome
```

Then, inside `run_eval`, insert this block right after the existing
`settled = [...]` line (before `target = cheapest_in_policy_vendor(task)`):

```python
    vendor_outcomes: dict[str, VendorOutcome] = {}
    for ex in executed_per_trial:
        for e in ex:
            outcome = vendor_outcomes.setdefault(e.vendor_id, VendorOutcome())
            if e.verified:
                outcome.successes += 1
            else:
                outcome.failures += 1
```

Finally, add the new field to the `EvalReport(...)` constructor call at the
end of the function, right after `settled_tx_hashes=settled,`:

```python
        settled_tx_hashes=settled,
        vendor_outcomes=vendor_outcomes,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_harness.py -v`
Expected: all PASS. Then run the full offline suite: `python -m pytest -v`
Expected: all PASS (confirms every existing `EvalReport`-consuming test,
including JSON round-trip tests, still works with the new field present).

- [ ] **Step 5: Commit**

```bash
git add evals/harness.py tests/test_harness.py
git commit -m "Populate EvalReport.vendor_outcomes from ExecutedPurchase.verified

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push
```

---

### Task 3: Build `evals/ml/reliability.py`

**Files:**
- Create: `evals/ml/__init__.py`
- Create: `evals/ml/reliability.py`
- Test: `tests/test_reliability.py`

**Interfaces:**
- Produces: `beta_update(alpha: float, beta: float, success: bool) -> tuple[float, float]`,
  `posterior_mean(alpha: float, beta: float) -> float`,
  `vendor_reliability_from_reports(report_paths: list[Path]) -> dict[str, dict]`
  (each value: `{"alpha", "beta", "mean", "successes", "failures", "n_observations"}`)
  — Task 4's reporting script imports all three.
- Consumes: `evals.models.EvalReport` (Task 1's `vendor_outcomes` field).

- [ ] **Step 1: Write the failing tests**

Create `evals/ml/__init__.py` (empty — just makes `evals.ml` a package):

```python
```

Create `tests/test_reliability.py`:

```python
from decimal import Decimal

import pytest

from evals.ml.reliability import (
    beta_update,
    posterior_mean,
    vendor_reliability_from_reports,
)
from evals.models import EvalReport, VendorOutcome


def test_beta_update_success_increments_alpha():
    assert beta_update(1, 1, success=True) == (2, 1)


def test_beta_update_failure_increments_beta():
    assert beta_update(1, 1, success=False) == (1, 2)


def test_posterior_mean():
    assert posterior_mean(2, 1) == pytest.approx(2 / 3)
    assert posterior_mean(1, 1) == pytest.approx(0.5)


def _write_report(path, vendor_outcomes):
    report = EvalReport(
        task_id="t", agent_id="a", date_utc="2026-09-19", base_seed=0,
        n_trials=1, outcomes=["pass"], pass_1=1.0, pass_1_ci=(0.0, 1.0),
        pass_k={}, pass_k_ci={}, touchpoints_per_basket=1.0, budget_violations=0,
        best_price_capture_rate=None, best_price_capture_rate_ci=None,
        cost_per_completed_tx_usdc=Decimal("0"), escalation_rate=0.0,
        escalation_reasons={}, unverified_claims=0, settled_tx_hashes=[],
        vendor_outcomes=vendor_outcomes,
    )
    path.write_text(report.model_dump_json(), encoding="utf-8")


def test_vendor_reliability_from_reports_folds_a_single_file(tmp_path):
    path = tmp_path / "r1.json"
    _write_report(path, {"v1": VendorOutcome(successes=3, failures=1)})

    result = vendor_reliability_from_reports([path])

    # prior (1,1) + 3 successes + 1 failure -> alpha=4, beta=2
    assert result["v1"]["alpha"] == 4
    assert result["v1"]["beta"] == 2
    assert result["v1"]["mean"] == pytest.approx(4 / 6)
    assert result["v1"]["successes"] == 3
    assert result["v1"]["failures"] == 1
    assert result["v1"]["n_observations"] == 4


def test_vendor_reliability_from_reports_folds_across_multiple_files(tmp_path):
    path1 = tmp_path / "r1.json"
    path2 = tmp_path / "r2.json"
    _write_report(path1, {"v1": VendorOutcome(successes=2, failures=0)})
    _write_report(path2, {"v1": VendorOutcome(successes=1, failures=1)})

    result = vendor_reliability_from_reports([path1, path2])

    assert result["v1"]["successes"] == 3
    assert result["v1"]["failures"] == 1
    assert result["v1"]["n_observations"] == 4


def test_vendor_reliability_from_reports_keeps_vendors_separate(tmp_path):
    path = tmp_path / "r1.json"
    _write_report(path, {
        "v1": VendorOutcome(successes=5, failures=0),
        "v2": VendorOutcome(successes=0, failures=5),
    })

    result = vendor_reliability_from_reports([path])

    assert result["v1"]["mean"] > 0.8
    assert result["v2"]["mean"] < 0.2


def test_vendor_reliability_from_reports_empty_list_returns_empty_dict():
    assert vendor_reliability_from_reports([]) == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_reliability.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.ml.reliability'`

- [ ] **Step 3: Create `evals/ml/reliability.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_reliability.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/ml/__init__.py evals/ml/reliability.py tests/test_reliability.py
git commit -m "Add evals/ml/reliability.py: Beta-Binomial vendor reliability

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push
```

---

### Task 4: Build `scripts/report_vendor_reliability.py`

**Files:**
- Create: `scripts/report_vendor_reliability.py`
- Modify: `pyproject.toml` (add a `per-file-ignores` entry for this
  script's `sys.path` shim, same reason `run_stub_evals.py`/
  `run_claude_planner_evals.py` have one)
- Test: `tests/test_report_vendor_reliability.py`

**Interfaces:**
- Consumes: `evals.ml.reliability.vendor_reliability_from_reports` (Task 3),
  `evals.stats.wilson_interval` (existing).
- Produces: nothing further downstream.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_vendor_reliability.py`:

```python
from decimal import Decimal

from evals.models import EvalReport, VendorOutcome
from scripts.report_vendor_reliability import main


def _write_report(path, vendor_outcomes):
    report = EvalReport(
        task_id="t", agent_id="a", date_utc="2026-09-19", base_seed=0,
        n_trials=1, outcomes=["pass"], pass_1=1.0, pass_1_ci=(0.0, 1.0),
        pass_k={}, pass_k_ci={}, touchpoints_per_basket=1.0, budget_violations=0,
        best_price_capture_rate=None, best_price_capture_rate_ci=None,
        cost_per_completed_tx_usdc=Decimal("0"), escalation_rate=0.0,
        escalation_reasons={}, unverified_claims=0, settled_tx_hashes=[],
        vendor_outcomes=vendor_outcomes,
    )
    path.write_text(report.model_dump_json(), encoding="utf-8")


def test_main_aggregates_reports_in_the_given_directory(tmp_path):
    _write_report(tmp_path / "r1.json", {"v1": VendorOutcome(successes=4, failures=0)})

    scores = main(results_dir=tmp_path)

    assert scores["v1"]["successes"] == 4
    assert scores["v1"]["failures"] == 0
    assert scores["v1"]["mean"] > 0.8


def test_main_returns_empty_dict_for_a_directory_with_no_reports(tmp_path):
    assert main(results_dir=tmp_path) == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_report_vendor_reliability.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.report_vendor_reliability'`

- [ ] **Step 3: Implement**

Create `scripts/report_vendor_reliability.py`:

```python
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
        print(f"{vendor_id:<24} {s['mean']:>8.3f} [{lo:.3f}, {hi:.3f}]         {s['n_observations']:>5d}")
        if s["mean"] < _SUSPICIOUS_MEAN_THRESHOLD:
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
```

Add to `pyproject.toml`'s `[tool.ruff.lint.per-file-ignores]`:

```toml
"scripts/report_vendor_reliability.py" = ["E402"]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_report_vendor_reliability.py -v`
Expected: PASS. Then run `ruff check .` to confirm the new per-file-ignore
is correctly picked up.

- [ ] **Step 5: Commit**

```bash
git add scripts/report_vendor_reliability.py tests/test_report_vendor_reliability.py pyproject.toml
git commit -m "Add scripts/report_vendor_reliability.py

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push
```

---

### Task 5: Build `evals/ml/synthetic_data.py`

**Files:**
- Create: `evals/ml/synthetic_data.py`
- Test: `tests/test_synthetic_data.py`

**Interfaces:**
- Produces: `generate_offers(n: int, seed: int) -> tuple[list[dict], list[str]]`
  — Task 6's classifier training/tests and Task 7's training script import
  this.
- Consumes: nothing from this project — pure `numpy` sampling.

**Important — read before implementing:** the exact constants below
(`_LOGIT_INTERCEPTS`, `_LOGIT_SLOPES`, category price parameters) were
empirically verified during design, not guessed. An earlier candidate set
(`escalate` intercept -2.0/slope 1.2, `reject` intercept -8.0/slope 4.0)
produced labels so imbalanced (82.7% accept) that a trained classifier
(83.2% test accuracy) barely beat the naive "always predict accept"
baseline (82.4%) — a test asserting only "accuracy > 0.7" would have
silently passed a nearly-useless model. The constants below were re-tuned
and re-verified to produce a genuinely learnable, non-trivial 3-class
problem (verified: 65.4% test accuracy vs. 57.1% majority-class baseline
at `n=5000, seed=42`). Use exactly these constants.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_synthetic_data.py`:

```python
from collections import Counter

from evals.ml.synthetic_data import _CATEGORY_PRICE_PARAMS, _LABELS, generate_offers


def test_generate_offers_returns_matching_lengths():
    features, labels = generate_offers(n=100, seed=1)
    assert len(features) == 100
    assert len(labels) == 100


def test_generate_offers_zscores_are_approximately_standard_normal_per_category():
    features, _ = generate_offers(n=20000, seed=1)
    for category in _CATEGORY_PRICE_PARAMS:
        zs = [f["price_zscore_in_category"] for f in features if f["category"] == category]
        assert len(zs) > 1000  # sanity: each category got a meaningful sample
        mean_z = sum(zs) / len(zs)
        std_z = (sum((z - mean_z) ** 2 for z in zs) / len(zs)) ** 0.5
        assert abs(mean_z) < 0.05
        assert abs(std_z - 1.0) < 0.05


def test_generate_offers_labels_are_one_of_the_three_classes():
    _, labels = generate_offers(n=500, seed=1)
    assert set(labels) <= set(_LABELS)
    assert "accept" in labels


def test_generate_offers_high_zscore_offers_skew_toward_reject():
    features, labels = generate_offers(n=20000, seed=1)
    high_z_labels = [
        label for f, label in zip(features, labels)
        if f["price_zscore_in_category"] > 2.5
    ]
    assert len(high_z_labels) > 50  # sanity: enough high-z samples exist
    reject_rate = high_z_labels.count("reject") / len(high_z_labels)
    assert reject_rate > 0.6


def test_generate_offers_reference_price_missing_flag_is_consistent():
    features, _ = generate_offers(n=2000, seed=1)
    for f in features:
        if f["reference_price_missing"]:
            assert f["reference_price_ratio"] == 1.0


def test_generate_offers_label_distribution_is_not_degenerate():
    # Guards against the exact "one class dominates so hard a trained
    # model can't beat guessing it" failure mode found during design --
    # every class must have a real, non-trivial share.
    _, labels = generate_offers(n=20000, seed=1)
    counts = Counter(labels)
    for label in _LABELS:
        assert counts[label] / len(labels) > 0.05


def test_generate_offers_is_reproducible_with_the_same_seed():
    f1, l1 = generate_offers(n=50, seed=7)
    f2, l2 = generate_offers(n=50, seed=7)
    assert f1 == f2
    assert l1 == l2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_synthetic_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.ml.synthetic_data'`

- [ ] **Step 3: Create `evals/ml/synthetic_data.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_synthetic_data.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/ml/synthetic_data.py tests/test_synthetic_data.py
git commit -m "Add evals/ml/synthetic_data.py: probabilistic training-data generator

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push
```

---

### Task 6: Build `evals/ml/price_classifier.py`

**Files:**
- Modify: `requirements.txt` (add `scikit-learn==1.9.1`)
- Create: `evals/ml/price_classifier.py`
- Test: `tests/test_price_classifier.py`

**Interfaces:**
- Consumes: `evals.ml.synthetic_data.generate_offers` (Task 5, for the
  full-pipeline test only).
- Produces: `FEATURE_NAMES`, `train(features, labels, seed) -> TrainedClassifier`,
  `load(path) -> TrainedClassifier`, `TrainedClassifier.predict_proba(features) -> dict[str, float]`,
  `TrainedClassifier.save(path)`, `DEFAULT_ARTIFACT_PATH` — Task 7's
  training script imports `train`, `DEFAULT_ARTIFACT_PATH`.

- [ ] **Step 1: Add the dependency**

In `requirements.txt`, add:

```
scikit-learn==1.9.1
```

Install it: `python -m pip install -r requirements.txt`

(Verified during design: this version installs cleanly in this project's
environment, pulling `numpy`, `scipy`, and `joblib` — no version conflicts
with any existing pinned dependency.)

- [ ] **Step 2: Write the failing tests**

Create `tests/test_price_classifier.py`:

```python
from collections import Counter

from sklearn.model_selection import train_test_split

from evals.ml.price_classifier import _vectorize, load, train
from evals.ml.synthetic_data import generate_offers


def test_train_produces_a_classifier_with_predict_proba():
    features = [
        {"price_zscore_in_category": -2.0, "reference_price_ratio": 1.0,
         "reference_price_missing": False, "budget_utilization": 0.1},
        {"price_zscore_in_category": -1.8, "reference_price_ratio": 0.9,
         "reference_price_missing": False, "budget_utilization": 0.2},
        {"price_zscore_in_category": 3.0, "reference_price_ratio": 3.0,
         "reference_price_missing": False, "budget_utilization": 0.9},
        {"price_zscore_in_category": 3.2, "reference_price_ratio": 3.5,
         "reference_price_missing": True, "budget_utilization": 0.95},
    ]
    labels = ["accept", "accept", "reject", "reject"]

    clf = train(features, labels, seed=0)
    low_z_proba = clf.predict_proba(features[0])
    high_z_proba = clf.predict_proba(features[2])

    assert set(low_z_proba) == {"accept", "reject"}
    assert abs(sum(low_z_proba.values()) - 1.0) < 1e-9
    assert low_z_proba["accept"] > high_z_proba["accept"]


def test_predict_proba_output_sums_to_one_for_three_classes():
    features = [
        {"price_zscore_in_category": z, "reference_price_ratio": 1.0,
         "reference_price_missing": False, "budget_utilization": 0.3}
        for z in (-2.0, -1.0, 0.0, 1.0, 2.0, 2.5, 3.0, 3.5)
    ]
    labels = ["accept", "accept", "accept", "escalate", "escalate", "escalate", "reject", "reject"]

    clf = train(features, labels, seed=0)
    proba = clf.predict_proba(features[0])
    assert set(proba) == {"accept", "escalate", "reject"}
    assert abs(sum(proba.values()) - 1.0) < 1e-9


def test_vectorize_encodes_reference_price_missing_as_the_third_position():
    with_ref = {"price_zscore_in_category": 0.0, "reference_price_ratio": 1.0,
                "reference_price_missing": False, "budget_utilization": 0.5}
    without_ref = {**with_ref, "reference_price_missing": True}
    assert _vectorize(with_ref)[2] == 0.0
    assert _vectorize(without_ref)[2] == 1.0


def test_save_and_load_round_trip(tmp_path):
    features = [
        {"price_zscore_in_category": -2.0, "reference_price_ratio": 1.0,
         "reference_price_missing": False, "budget_utilization": 0.1},
        {"price_zscore_in_category": 3.0, "reference_price_ratio": 3.0,
         "reference_price_missing": False, "budget_utilization": 0.9},
    ]
    labels = ["accept", "reject"]
    clf = train(features, labels, seed=0)
    path = tmp_path / "model.joblib"
    clf.save(path)

    loaded = load(path)
    assert loaded.predict_proba(features[0]) == clf.predict_proba(features[0])


def test_full_train_test_run_beats_the_majority_class_baseline():
    features, labels = generate_offers(n=5000, seed=42)
    x_train, x_test, y_train, y_test = train_test_split(
        features, labels, test_size=0.2, random_state=42, stratify=labels
    )
    clf = train(x_train, y_train, seed=42)

    correct = sum(
        1 for f, y in zip(x_test, y_test)
        if max((p := clf.predict_proba(f)), key=p.get) == y
    )
    accuracy = correct / len(y_test)
    majority_class = Counter(y_train).most_common(1)[0][0]
    baseline_accuracy = sum(1 for y in y_test if y == majority_class) / len(y_test)

    # Verified during design at these exact seeds: accuracy ~0.654,
    # baseline ~0.571. Both floors have margin below the observed values.
    assert accuracy > 0.60
    assert accuracy > baseline_accuracy + 0.05
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_price_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.ml.price_classifier'`

- [ ] **Step 4: Create `evals/ml/price_classifier.py`**

```python
"""Trained accept/reject/escalate price classifier.

See docs/superpowers/specs/2026-09-19-week7-trained-model-design.md.
"""

from __future__ import annotations

from pathlib import Path

import joblib
from sklearn.linear_model import LogisticRegression

FEATURE_NAMES = [
    "price_zscore_in_category", "reference_price_ratio",
    "reference_price_missing", "budget_utilization",
]
DEFAULT_ARTIFACT_PATH = Path(__file__).parent / "price_classifier.joblib"


def _vectorize(features: dict) -> list[float]:
    return [
        float(features["price_zscore_in_category"]),
        float(features["reference_price_ratio"]),
        1.0 if features["reference_price_missing"] else 0.0,
        float(features["budget_utilization"]),
    ]


class TrainedClassifier:
    def __init__(self, model: LogisticRegression):
        self._model = model

    def predict_proba(self, features: dict) -> dict[str, float]:
        x = [_vectorize(features)]
        proba = self._model.predict_proba(x)[0]
        # str(c): classes_ entries are numpy.str_, not plain str -- cast so
        # the returned dict's keys have a predictable, plain-Python type.
        return dict(zip((str(c) for c in self._model.classes_), (float(p) for p in proba)))

    def save(self, path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        joblib.dump(self._model, path)


def train(features: list[dict], labels: list[str], seed: int) -> TrainedClassifier:
    x = [_vectorize(f) for f in features]
    model = LogisticRegression(max_iter=1000, random_state=seed)
    model.fit(x, labels)
    return TrainedClassifier(model)


def load(path: Path = DEFAULT_ARTIFACT_PATH) -> TrainedClassifier:
    model = joblib.load(path)
    return TrainedClassifier(model)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_price_classifier.py -v`
Expected: all PASS (the full train/test run takes a few seconds — fitting
`LogisticRegression` on 4000 rows with 4 features is fast, but generating
5000 synthetic rows first adds some overhead; this is expected, not a
hang). Then run the full offline suite: `python -m pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt evals/ml/price_classifier.py tests/test_price_classifier.py
git commit -m "Add evals/ml/price_classifier.py: LogisticRegression accept/reject/escalate model

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push
```

---

### Task 7: Build `scripts/train_price_classifier.py`

**Files:**
- Create: `scripts/train_price_classifier.py`
- Modify: `pyproject.toml` (add a `per-file-ignores` entry for this
  script's `sys.path` shim)
- Test: `tests/test_train_price_classifier.py`

**Interfaces:**
- Consumes: `evals.ml.price_classifier.{train, DEFAULT_ARTIFACT_PATH}`
  (Task 6), `evals.ml.synthetic_data.generate_offers` (Task 5).
- Produces: the committed artifact `evals/ml/price_classifier.joblib` —
  nothing further downstream in this plan.

- [ ] **Step 1: Write the failing test**

Create `tests/test_train_price_classifier.py`:

```python
from scripts.train_price_classifier import main


def test_main_trains_and_saves_a_classifier(tmp_path):
    artifact_path = tmp_path / "model.joblib"
    result = main(artifact_path=artifact_path)

    assert artifact_path.exists()
    assert result["n"] == 5000
    assert result["seed"] == 42
    # Verified during design at these exact values: accuracy ~0.654.
    assert result["accuracy"] > 0.60
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_train_price_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.train_price_classifier'`

- [ ] **Step 3: Implement**

Create `scripts/train_price_classifier.py`:

```python
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
```

Add to `pyproject.toml`'s `[tool.ruff.lint.per-file-ignores]`:

```toml
"scripts/train_price_classifier.py" = ["E402"]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_train_price_classifier.py -v`
Expected: PASS. Then run `ruff check .` to confirm the new per-file-ignore
is picked up.

- [ ] **Step 5: Run the script for real and commit the trained artifact**

Run: `python scripts/train_price_classifier.py`
Expected: prints the accuracy/classification-report/calibration table
(accuracy ≈ 0.654) and writes `evals/ml/price_classifier.joblib`. Then run
the full offline suite once more: `python -m pytest -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/train_price_classifier.py tests/test_train_price_classifier.py \
        pyproject.toml evals/ml/price_classifier.joblib
git commit -m "Add scripts/train_price_classifier.py; commit the trained artifact

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
git push
```

---

## After this plan lands

Run `python scripts/train_price_classifier.py` and
`python scripts/report_vendor_reliability.py` by hand (both already run as
part of Tasks 7 and, optionally, 4's verification, but this is the
"official," recorded pass). Record the printed classifier metrics
(accuracy, per-class precision/recall, the calibration table) and the
reliability report's output — including its expected "all vendors show
near-100% reliability" caveat line, since `evals/results/` on the
implementer's machine will mostly reflect `SyntheticExecutor`'s
always-succeeds behavior — in a new `docs/week7-trained-model-live-run.md`,
matching the Week 4/5/6 live-verification convention. Also write
`docs/math/threshold-calibration.md` (referenced but not yet written per
`docs/MATH_COURSEWORK_PLAN.md`), summarizing the calibration curve results
from the training script's own output — this is the coursework artifact
the design spec's Bayes/calibration decision was building toward.
