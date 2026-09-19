# Week 7 — Trained Model v1: Design

**Date:** 2026-09-19
**Status:** approved, pending implementation plan

## Why this exists

`docs/PMF_AND_BUILD_PLAN.md`'s Deliverable E names Week 7 as "Trained model
v1. Collect/generate vendor+price data; train scikit-learn accept/reject/
escalate classifier; integrate; report train/test metrics" — the coursework
requirement for a measurable ML artifact distinct from the LLM planner.
`docs/MATH_COURSEWORK_PLAN.md` couples a **second** component to the same
PR: "vendor-reliability memory as a Beta-Binomial update," explicitly
because it "needs the same vendor+price history anyway" as the classifier
(Week 5's own design doc already flagged this as the reason vector-store
memory was deferred, not abandoned). Both are in scope for this spec.

`docs/MATH_COURSEWORK_PLAN.md` also locks the model choice: `LogisticRegression`
(scikit-learn), specifically because "nothing in the 13-week plan needs
hand-derived gradients or PyTorch" — this is not a placeholder open to
revisiting mid-design, it's an already-committed decision this spec builds
from.

## Scope decisions made during brainstorming

1. **Both components together, not classifier-only.** They share the same
   underlying vendor+price+outcome data; building the history-tracking
   mechanism twice (once now, once later) would be wasted work.
2. **Neither component gets wired into a live decision this week.**
   `claude_planner.py` and `evals/guardrail.py::check_purchase` are
   unchanged by this spec. Both artifacts are built, trained/computed, and
   reported with real metrics — the same pattern Week 5 used for
   `claude-planner-v1` itself ("the LLM step is confirmatory, not
   differentiating... yet") and Week 6 used for `reference_price_usdc`
   ("a deliberate placeholder... not a claim that price anomalies are
   solved"). Wiring either into a live path is a later week's decision,
   made once there's an eval number that justifies it — not a
   mid-brainstorm architectural leap taken under time pressure. Approach 1
   (classifier replaces the static price-sanity check now) and Approach 3
   (full integration into `claude_planner.py`) were both considered and
   rejected for this reason during brainstorming.
3. **The classifier's real value-add over Week 6's static check is
   cross-vendor context, not a fancier threshold.** `reference_price_usdc *
   price_sanity_multiplier` (Week 6) can only compare a vendor to *itself*.
   A trained model earns its place by comparing a vendor's price to the
   **distribution of prices across its category** — visible only once many
   vendors are seen, which a single static per-vendor number structurally
   cannot express. This directly extends Week 4's existing
   Z-score/standard-normal work (`evals/stats.py`) rather than introducing
   a second, unrelated statistical foundation.
4. **Training data is synthetic and probabilistically labeled, not
   deterministically labeled.** A hard-cutoff label rule (e.g. "escalate iff
   z > 2") would make calibration vacuous — the model would just learn to be
   100% confident everywhere, and there would be nothing to check calibration
   *against*. Labels are instead sampled from a logistic function of the
   price z-score — literally `LogisticRegression`'s own generative
   assumption — so (a) the model class is the *correct* one for the
   data-generating process, not an arbitrary baseline choice, and (b)
   calibration has real, checkable content: does the trained model's
   predicted P(escalate) actually track the true generating probability at
   a given z-score, not just look plausible.
5. **Reliability's success/failure signal is `ExecutedPurchase.verified`,
   not a rejected offer.** A purchase rejected for being out-of-policy or
   over-cap is a *policy* mismatch, not evidence the vendor itself is
   unreliable — using it would conflate two different questions. Reliability
   asks "when this vendor's offer *was* accepted and paid, did settlement
   actually verify?" — the one signal every executor already produces
   (`ExecutedPurchase.verified: bool`, `evals/executor.py:22`).
6. **No new persistence infrastructure.** `evals/results/*.json` — written
   by the existing `scripts/run_stub_evals.py` / `run_claude_planner_evals.py`
   — already accumulates real per-run history across repeated invocations.
   Reliability scores are computed by **aggregating those existing files**,
   not by inventing a new state store, a database table, or a JSON
   read-modify-write cache. This is exactly the "real purchase history"
   Week 5 said memory should wait for — it now exists, in a place the
   harness already writes to. **Caveat, stated plainly:** `evals/results/`
   is git-ignored (confirmed: `.gitignore` line `evals/results/`). This
   memory is real and useful for local iterative development, but it is
   per-machine and ephemeral relative to source control — not a durable,
   shared, or CI-visible history. A future week that needs durable
   cross-environment memory will need real persistence; this spec does not
   claim to provide that.

## Architecture

New package, peer of `evals/agents/`:

```
evals/ml/
  __init__.py
  synthetic_data.py     # training-data generator (Vendor/Mandate features -> label)
  price_classifier.py   # feature engineering, train(), load(), predict()
  reliability.py         # Beta-Binomial math + aggregation over EvalReport files
  price_classifier.joblib   # committed, trained artifact (see "Training" below)

scripts/
  train_price_classifier.py   # generates data, trains, evaluates, reports, saves artifact
  report_vendor_reliability.py # aggregates evals/results/*.json, reports reliability scores
```

### `evals/ml/synthetic_data.py`

```python
def generate_offers(n: int, seed: int) -> tuple[list[dict], list[str]]:
    """Returns (features, labels), each of length n.

    Sampling process (fixed seed -> fully reproducible, per CLAUDE.md's
    "record the seed and model version"):
    1. Draw a category from a small fixed set (reusing this repo's existing
       task categories, e.g. "weather-data", "news-data").
    2. Draw that category's "true" price distribution: mean mu_c, std sigma_c
       (fixed per category, not per-sample -- this is what makes a category's
       distribution a stable thing a classifier can learn).
    3. Draw a price ~ Normal(mu_c, sigma_c); compute
       z = (price - mu_c) / sigma_c.
    4. Sample the label from a 3-class distribution whose log-odds are a
       LINEAR function of z (i.e. literally softmax(w0 + w1*z) over
       {accept, escalate, reject}, with w1 > 0 so higher z means more
       escalate/reject mass) -- this is what makes LogisticRegression the
       correct model for this data, not an arbitrary baseline pick.

    Each feature dict carries exactly these keys:
    - price_usdc, category: raw context, not fed to the model directly.
    - price_zscore_in_category: (price - mu_c) / sigma_c, computed above.
    - reference_price_ratio: price / an assigned reference price, for the
      fraction of rows (fixed at 70%) that get one assigned at all --
      mirrors evals.models.Vendor.reference_price_usdc being Optional.
    - reference_price_missing: bool, True for the other 30% of rows. When
      True, reference_price_ratio is set to a fixed placeholder (1.0) that
      carries NO information -- reference_price_missing is what tells the
      classifier to ignore it, not a magic sentinel value smuggled into
      reference_price_ratio itself.
    - budget_utilization: price / a synthetically-assigned budget_cap_usdc.
    """
```

### `evals/ml/price_classifier.py`

```python
FEATURE_NAMES = [
    "price_zscore_in_category", "reference_price_ratio",
    "reference_price_missing", "budget_utilization",
]  # reference_price_missing is the explicit missingness indicator,
   # not a magic sentinel value baked into reference_price_ratio itself.

def train(features: list[dict], labels: list[str], seed: int) -> "TrainedClassifier": ...
def load(path: Path = DEFAULT_ARTIFACT_PATH) -> "TrainedClassifier": ...

class TrainedClassifier:
    def predict_proba(self, features: dict) -> dict[str, float]: ...  # {"accept": .., "escalate": .., "reject": ..}
```

`predict_proba`'s three-key dict, not a bare `predict()` label, is the point
of this whole exercise — CLAUDE.md rule 3 wants a *measurable* artifact, and
a calibration report needs probabilities, not just a hard label.

### `evals/ml/reliability.py`

```python
def beta_update(alpha: float, beta: float, success: bool) -> tuple[float, float]:
    """One Beta-Binomial posterior update. alpha=beta=1 (uniform) is every
    vendor's starting prior -- no vendor is assumed reliable or unreliable
    before any evidence exists."""

def posterior_mean(alpha: float, beta: float) -> float:
    return alpha / (alpha + beta)

def vendor_reliability_from_reports(report_paths: list[Path]) -> dict[str, dict]:
    """Reads a list of evals/results/*.json files (EvalReport.model_validate_json),
    folds every EvalReport.vendor_outcomes entry through beta_update per
    vendor_id, and returns {vendor_id: {"alpha":.., "beta":.., "mean":.., "n_observations":..}}.
    Pure function of its file-path input -- no implicit directory scanning,
    so it's testable against a handful of fixture files without touching the
    real (git-ignored, machine-local) evals/results/ directory."""
```

## Data model change

```python
# evals/models.py
class VendorOutcome(_Model):
    successes: int = 0
    failures: int = 0


class EvalReport(_Model):
    ...  # existing fields unchanged
    vendor_outcomes: dict[str, VendorOutcome] = Field(default_factory=dict)
```

`evals/harness.py::run_eval` populates this from `executed_per_trial`
(already computed, already in scope at the point `EvalReport` is
constructed) — one `ExecutedPurchase` with `verified=True` increments that
`vendor_id`'s `successes`; `verified=False` increments `failures`. This is
purely additive: every existing `EvalReport` construction site keeps
working with the new field defaulting to `{}`, and every already-written
`evals/results/*.json` file (missing the field entirely) still round-trips
through `model_validate_json` under pydantic's default-value semantics.

## Training

`scripts/train_price_classifier.py`:

1. `evals.ml.synthetic_data.generate_offers(n=5000, seed=42)` — both values
   fixed and recorded here, not left to whatever the implementer picks (per
   CLAUDE.md's "record the seed and model version" — this applies to a
   trained artifact exactly the way it applies to an LLM eval run). 5000
   rows across 3 classes and 4 features is comfortably enough for stable
   `LogisticRegression` metrics without a meaningful runtime cost; 42 is an
   arbitrary but fixed, recorded, unremarkable choice.
2. Train/test split (`sklearn.model_selection.train_test_split`, same fixed
   seed).
3. Fit `sklearn.linear_model.LogisticRegression` on the training split.
4. Report on the held-out test split: accuracy, per-class precision/recall
   (`sklearn.metrics.classification_report`), and a calibration check —
   bin predicted P(escalate) into deciles, compare each bin's mean
   predicted probability to its empirical escalate-rate (a basic
   reliability/calibration diagram in table form; `sklearn.calibration.calibration_curve`
   does this directly) — this is the concrete, checkable output the
   "Bayes, calibration" coursework line in `docs/MATH_COURSEWORK_PLAN.md`
   is pointing at.
5. Serialize the fitted model (`joblib.dump`) to `evals/ml/price_classifier.joblib`,
   committed to the repo (a trained artifact under ~KB for a 4-feature
   logistic model — no Git LFS concern).
6. Print the metrics table, matching the existing `scripts/run_*_evals.py`
   reporting convention.

**New dependency:** `scikit-learn` (exact version pinned in
`requirements.txt`, per this repo's existing `langchain-anthropic`
precedent) — pulls `numpy`/`scipy` transitively. `joblib` ships with
scikit-learn; no separate pin needed.

## Reporting

`scripts/report_vendor_reliability.py`:

1. Glob `evals/results/*.json` (or accept a directory argument for
   testability).
2. `evals.ml.reliability.vendor_reliability_from_reports(paths)`.
3. Print a table: vendor_id, alpha, beta, posterior mean, n_observations,
   a Wilson-style credible interval width note (reuse `evals.stats.wilson_interval`
   directly — a Beta(alpha, beta) posterior mean with a binomial observation
   count is the same shape of problem `evals/stats.py` already solves for
   pass^1; no new interval math needs inventing).
4. Explicitly print a caveat line when every vendor's `successes` count vastly
   dominates `failures` (today's expected case, since `SyntheticExecutor`
   rarely fails) — e.g. "All observed vendors show near-100% reliability;
   this reflects SyntheticExecutor's current failure model, not a claim
   about real-world vendor trustworthiness. See Known limitations." Stated
   plainly in the tool's own output, not just in a doc nobody reads before
   running it.

## Testing

- `evals/ml/synthetic_data.py`: `generate_offers` is tested for
  distributional sanity at a large sample size — z-scores computed from the
  generated data are approximately standard normal *within each category*
  (mean ~0, std ~1, checked with a tolerance appropriate to sample size, not
  exact equality); the label distribution's empirical escalate-rate at a
  known z-score band approximately matches the true logistic function used
  to generate it. This is the offline analogue of `evals/stats.py`'s own
  rigor — a statistical claim gets a statistical test, not just "didn't
  crash."
- `evals/ml/price_classifier.py`: `train`/`predict_proba` tested against a
  small, fixed, hand-computable dataset first (verifying the wrapper's
  input/output shape and the missingness-indicator logic independently of
  whether scikit-learn's fit converges to good weights), then a full
  train/test run asserting the reported test-set accuracy clears a stated
  floor (e.g. `> 0.7` for a 3-class problem — a real, specific number
  CLAUDE.md rule 4 requires, not "the script ran without crashing").
- `evals/ml/reliability.py`: `beta_update`/`posterior_mean` tested with
  hand-computed values (e.g. `beta_update(1, 1, success=True) == (2, 1)`,
  `posterior_mean(2, 1) == pytest.approx(2/3)`). `vendor_reliability_from_reports`
  tested against small, committed **fixture** `EvalReport` JSON files
  (written to a `tmp_path` in the test, not read from the real,
  git-ignored `evals/results/`) with known vendor_outcomes, asserting exact
  alpha/beta/mean arithmetic.
- `evals/models.py`: `EvalReport.vendor_outcomes` defaults to `{}`. Backward
  compatibility is tested against an inline JSON string literal in the test
  file itself (a full, valid `EvalReport` payload with every pre-Week-7
  field present and no `vendor_outcomes` key at all) — not a real file from
  the git-ignored `evals/results/` directory, which does not exist on a
  fresh clone or in CI and would make this test non-reproducible outside
  this one machine. `model_validate_json` against that literal must
  round-trip without error and produce `vendor_outcomes == {}`.
- `evals/harness.py::run_eval`: a new test with a fake multi-vendor,
  mixed-verified-flag executor confirms `vendor_outcomes` is populated
  correctly (right vendor_id, right successes/failures split) across
  several trials.

## Known limitations (stated plainly, not glossed over)

- **Neither the classifier nor the reliability tracker changes any agent's
  live behavior.** They are real, tested, gradeable artifacts — not yet
  load-bearing. `claude_planner.py`'s decision path is byte-identical to
  Week 6's after this spec lands.
- **Reliability scores will show near-100% for essentially every vendor
  today**, because `SyntheticExecutor` (the executor behind every synthetic
  task, which is all but one shipped task) has no realistic failure
  injection yet — `verified=True` on every successful call, by construction.
  The Beta-Binomial *mechanism* is real and correctly tested; the *numbers*
  it currently produces are not yet interesting. This is expected to change
  once Week 8 ("Failure/recovery + retries") gives `SyntheticExecutor` (or
  a successor) a real failure model, or once `real_x402` runs accumulate
  enough history to matter.
- **Reliability memory lives in a git-ignored directory.** It is real
  memory across runs *on one machine*, not durable, shared, or CI-visible
  history. A future need for durable cross-environment memory is a
  different, larger problem this spec does not solve.
- **The classifier's training data is entirely synthetic**, generated from
  a known logistic process, not mined from this project's own real task
  specs or eval history. This is the honest baseline the coursework
  requirement calls for — a real, working scikit-learn pipeline with
  genuine train/test metrics and a genuine calibration check — not a claim
  that it has learned anything about this project's actual six shipped
  vendors, which are too few to train on meaningfully.

## Out of scope (deferred, not forgotten)

- **Wiring the classifier into `check_purchase` or `claude_planner.py`.**
  A later week's decision, once real eval numbers justify it — see scope
  decision #2 above for the specific approaches considered and rejected.
- **Feeding reliability scores into the classifier as a feature.** Natural
  next step once reliability scores are actually informative (post
  failure-injection); premature while they're uniformly ~100%.
- **Durable, shared, cross-environment reliability persistence** (a real
  database, a committed data file, etc.) — not needed until something
  outside a single developer's local iteration loop needs to read it.
- **Any model class beyond `LogisticRegression`.** Already decided,
  project-wide, in `docs/MATH_COURSEWORK_PLAN.md` — not revisited here.
