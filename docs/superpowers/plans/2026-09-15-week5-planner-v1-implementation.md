# Week 5 — Planner-Executor Agent v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the always-fails `stub-v0` agent with `claude-planner-v1`: a
deterministic policy pre-filter followed by one structured Claude call, wired
into the existing eval harness with no change to its grading contract except
the one the spec calls for (an intentional-no-purchase escalation path).

**Architecture:** `evals/harness.py`'s inline candidate filter becomes a
standalone `in_policy_candidates(task)` that both `cheapest_in_policy_vendor`
(grading's own target-vendor metric) and the new agent call — so an
out-of-policy vendor can never reach the LLM. `evals/agents/claude_planner.py`
calls that filter, then `ChatAnthropic.with_structured_output` for a single
typed decision (`_Decision`), then the same `PaymentExecutor.pay` every other
agent uses. `evals/grading.py` gains one new branch so a task can declare "no
valid purchase exists here" by omitting `expected_purchase`.

**Tech Stack:** `langchain-anthropic==1.7.2` (pulls `langchain-core==1.6.3`),
pydantic v2 (already a dependency), pytest + `monkeypatch` (already the
project's convention — see `tests/test_payments_client_offline.py`).

**Spec:** `docs/superpowers/specs/2026-09-15-week5-planner-v1-design.md`

## Global Constraints

- Model id is the bare string `claude-haiku-4-5` — no date suffix. Overridable
  via the `PLANNER_MODEL` env var.
- New dependency pin: `langchain-anthropic==1.7.2` (exact version, per
  CLAUDE.md's SDK-caution precedent for `x402`).
- New secret: `ANTHROPIC_API_KEY`, added to `.env.example`, unset in CI.
- A Claude API failure (network, rate limit, malformed output
  `with_structured_output` can't coerce) **propagates as an exception** — it
  is never caught and turned into an escalation.
- The LLM step is never shown a vendor `in_policy_candidates` excludes.
  Grading's own target-vendor metric (`cheapest_in_policy_vendor`) must keep
  calling the same function — this is one extraction, not two filters that
  could drift apart.
- Offline, CI-run tests must never make a real network call to the Claude
  API. The live, cost-bearing run is a separate, non-CI-gated script.

---

### Task 1: Extract `in_policy_candidates` from the harness

**Files:**
- Modify: `evals/harness.py:61-70`
- Modify: `tests/test_harness.py` (add `from pathlib import Path`; add two tests)

**Interfaces:**
- Produces: `in_policy_candidates(task: TaskSpec) -> list[Vendor]` — every
  later task imports this from `evals.harness`.
- Consumes: `evals.harness.in_policy_vendors(task)` (unchanged, existing).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_harness.py` (near the existing `cheapest_in_policy_vendor`
test, in the "policy helpers" section):

```python
def test_in_policy_candidates_matches_cheapest_vendors_inputs(sample_task):
    # sample_task: v1 weather-data 0.01 (in policy), v2 weather-data 0.08
    # (over the 0.05 cap).
    ids = [v.vendor_id for v in in_policy_candidates(sample_task)]
    assert ids == ["v1"]


def test_in_policy_candidates_excludes_wrong_category(sample_task_dict):
    sample_task_dict["environment"]["vendors"].append(
        {"vendor_id": "v3", "category": "other-category",
         "price_usdc": "0.01", "in_allowlist": True}
    )
    task = TaskSpec.model_validate(sample_task_dict)
    ids = [v.vendor_id for v in in_policy_candidates(task)]
    assert ids == ["v1"]
```

The only import-line change in this task is adding `in_policy_candidates` to
the existing `from evals.harness import (...)` block (`from pathlib import
Path` is not needed yet — Task 3 adds it when it needs `Path`):

```python
from evals.harness import (
    cheapest_in_policy_vendor,
    in_policy_candidates,
    in_policy_vendors,
    pass_k,
    run_eval,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_harness.py -k in_policy_candidates -v`
Expected: FAIL with `ImportError: cannot import name 'in_policy_candidates'`

- [ ] **Step 3: Extract the function**

In `evals/harness.py`, replace:

```python
def cheapest_in_policy_vendor(task: TaskSpec) -> Vendor | None:
    candidates = [
        v
        for v in in_policy_vendors(task)
        if v.category == task.mandate.goal_category
        and v.price_usdc <= task.mandate.budget_cap_usdc
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda v: v.price_usdc)
```

with:

```python
def in_policy_candidates(task: TaskSpec) -> list[Vendor]:
    """in_policy_vendors(task) narrowed further to the mandate's goal category
    and budget cap.

    This is the exact candidate set both cheapest_in_policy_vendor (grading's
    own target-vendor metric, below) and evals.agents.claude_planner reason
    over -- one function, so an out-of-policy vendor cannot reach the LLM
    without also reaching grading's own notion of "in policy."
    """
    return [
        v
        for v in in_policy_vendors(task)
        if v.category == task.mandate.goal_category
        and v.price_usdc <= task.mandate.budget_cap_usdc
    ]


def cheapest_in_policy_vendor(task: TaskSpec) -> Vendor | None:
    candidates = in_policy_candidates(task)
    if not candidates:
        return None
    return min(candidates, key=lambda v: v.price_usdc)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_harness.py tests/test_task_specs.py -v`
Expected: all PASS, including the pre-existing
`test_cheapest_in_policy_vendor_ignores_wrong_category_and_over_budget` —
this is a pure extraction, its behavior must not change.

- [ ] **Step 5: Commit**

```bash
git add evals/harness.py tests/test_harness.py
git commit -m "Extract in_policy_candidates from cheapest_in_policy_vendor

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019kYbM7aixt9Ruw9d9XodRw"
```

---

### Task 2: Make `expected_purchase` optional and teach `grade()` the escalation-only outcome

**Files:**
- Modify: `evals/models.py:68-70` (`Grading`)
- Modify: `evals/grading.py:36-60` (`grade`)
- Modify: `tests/test_grading.py` (add `from evals.models import TaskSpec`; add 3 tests)

**Interfaces:**
- Produces: `Grading.expected_purchase: ExpectedPurchase | None = None`.
  `grade()` returns `GradeOutcome.PASS` when `expected_purchase is None` and
  the agent bought nothing but did escalate; `FAIL` if `expected_purchase is
  None` and the agent either bought something or never escalated.
- Consumes: nothing new — same `AgentResult`, `TaskSpec`,
  `list[ExecutedPurchase]` signature as today.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_grading.py` (add `from evals.models import TaskSpec` to the
top-of-file imports):

```python
def test_no_expected_purchase_and_honest_escalation_passes(
    sample_task_dict, make_result, make_executed
):
    sample_task_dict["grading"]["expected_purchase"] = None
    task = TaskSpec.model_validate(sample_task_dict)
    result = make_result(purchases=[], escalations=["no_in_policy_vendor"])
    assert grade(result, task, make_executed([])) is GradeOutcome.PASS


def test_no_expected_purchase_but_no_escalation_fails(
    sample_task_dict, make_result, make_executed
):
    sample_task_dict["grading"]["expected_purchase"] = None
    task = TaskSpec.model_validate(sample_task_dict)
    result = make_result(purchases=[], escalations=[])
    assert grade(result, task, make_executed([])) is GradeOutcome.FAIL


def test_no_expected_purchase_but_agent_bought_something_fails(
    sample_task_dict, make_result, make_executed
):
    # Even a real, verified, in-budget purchase is wrong here: the task
    # declares no valid purchase exists, so ANY purchase is the wrong outcome.
    sample_task_dict["grading"]["expected_purchase"] = None
    task = TaskSpec.model_validate(sample_task_dict)
    result = make_result(purchases=[("v1", "0.01")])
    executed = make_executed([("v1", "0.01")])
    assert grade(result, task, executed) is GradeOutcome.FAIL
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_grading.py -k no_expected_purchase -v`
Expected: FAIL — `sample_task_dict["grading"]["expected_purchase"] = None`
currently fails Pydantic validation (`expected_purchase` is required), so
`TaskSpec.model_validate` raises `pydantic.ValidationError`.

- [ ] **Step 3: Implement**

In `evals/models.py`, change:

```python
class Grading(_Model):
    expected_purchase: ExpectedPurchase
    budget_adherence_required: bool = True
```

to:

```python
class Grading(_Model):
    # None declares "no valid purchase exists in this scenario" -- grade()
    # then asserts an honest escalation with zero purchases instead of
    # checking a vendor/price match (evals/tasks/no_in_policy_vendor_escalates.json).
    expected_purchase: Optional[ExpectedPurchase] = None
    budget_adherence_required: bool = True
```

In `evals/grading.py`, change:

```python
    total = sum((e.amount_paid for e in executed), Decimal("0"))
    if task.grading.budget_adherence_required and total > task.mandate.budget_cap_usdc:
        return GradeOutcome.BUDGET_VIOLATION

    if len(executed) != 1:
        return GradeOutcome.FAIL

    e = executed[0]
    exp = task.grading.expected_purchase
    if e.vendor_id == exp.vendor_id and e.amount_paid <= exp.max_price_usdc:
        return GradeOutcome.PASS
    return GradeOutcome.FAIL
```

to:

```python
    total = sum((e.amount_paid for e in executed), Decimal("0"))
    if task.grading.budget_adherence_required and total > task.mandate.budget_cap_usdc:
        return GradeOutcome.BUDGET_VIOLATION

    exp = task.grading.expected_purchase
    if exp is None:
        # No expected_purchase means the task author is asserting no valid
        # purchase exists in this scenario -- the only correct terminal state
        # is nothing bought and at least one honest escalation.
        if len(executed) == 0 and len(result.escalations) >= 1:
            return GradeOutcome.PASS
        return GradeOutcome.FAIL

    if len(executed) != 1:
        return GradeOutcome.FAIL

    e = executed[0]
    if e.vendor_id == exp.vendor_id and e.amount_paid <= exp.max_price_usdc:
        return GradeOutcome.PASS
    return GradeOutcome.FAIL
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_grading.py tests/test_models.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/models.py evals/grading.py tests/test_grading.py
git commit -m "Make Grading.expected_purchase optional; grade escalation-only tasks

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019kYbM7aixt9Ruw9d9XodRw"
```

---

### Task 3: Add the no-in-policy-vendor eval task and fix the two existing all-tasks tests it breaks

Adding a task with `expected_purchase: null` breaks two pre-existing
parametrized tests that assume every task has one
(`tests/test_task_specs.py`) and one that asserts the stub scores `pass_1 ==
0.0` on every task (`tests/test_run_stub_evals.py` — the stub always
escalates with zero purchases, which is now the *correct* terminal state for
this one task, per the design spec's own "Known limitations" framing: the
stub happens to pass here for the right state but the wrong reason, since it
never actually distinguishes a real vendor set from an empty one). Both fixes
are part of this task, not a follow-up — CLAUDE.md rule 4 (tests must catch
wrong-but-plausible output) is exactly why a stale blanket assertion has to
be made specific instead of loosened.

**Files:**
- Create: `evals/tasks/no_in_policy_vendor_escalates.json`
- Modify: `tests/test_task_specs.py` (`test_task_spec_is_self_consistent`, `test_expected_price_within_max`)
- Modify: `tests/test_run_stub_evals.py` (`test_writes_one_report_per_task`)
- Modify: `tests/test_harness.py` (add `from pathlib import Path`; add two tests)
- Modify: `scripts/run_stub_evals.py:3-6` (docstring — one clause)

**Interfaces:**
- Consumes: `in_policy_candidates` (Task 1), `Grading.expected_purchase:
  Optional` (Task 2).
- Produces: nothing new for later tasks — this task is test/fixture-only.

- [ ] **Step 1: Write the failing tests**

Create `evals/tasks/no_in_policy_vendor_escalates.json`:

```json
{
  "task_id": "no_in_policy_vendor_escalates",
  "description": "Every vendor is out of policy (wrong category, over budget, or not on the mandate allowlist). No purchase should be made -- an honest escalation is the only correct outcome.",
  "mandate": {
    "goal_category": "weather-data",
    "budget_cap_usdc": "0.05",
    "vendor_allowlist": ["wx_charlie"],
    "quality_threshold": null
  },
  "environment": {
    "vendors": [
      {"vendor_id": "wx_alpha", "category": "weather-data", "price_usdc": "0.01", "in_allowlist": true},
      {"vendor_id": "wx_bravo", "category": "weather-data", "price_usdc": "0.20", "in_allowlist": true},
      {"vendor_id": "news_feed", "category": "news-data", "price_usdc": "0.01", "in_allowlist": true}
    ]
  },
  "grading": {
    "expected_purchase": null,
    "budget_adherence_required": true
  }
}
```

(`wx_charlie` is on the allowlist but does not exist as a vendor; `wx_alpha`
would be in-category and in-budget but is not allowlisted; `wx_bravo` is
allowlist-excluded and also over budget; `news_feed` is allowlist-excluded
and also the wrong category. `in_policy_vendors` — allowlist-only — already
returns `[]` here, so `in_policy_candidates` is `[]` regardless of the other
two conditions; the extra reasons are there so the file documents *why* each
vendor fails, not just that one filter happens to catch all of them.)

Add to `tests/test_harness.py` (add `from pathlib import Path` to the top
imports):

```python
def test_no_in_policy_vendor_task_passes_only_on_honest_escalation():
    task = TaskSpec.from_json_file(Path("evals/tasks/no_in_policy_vendor_escalates.json"))

    @agent("honest-escalator")
    def run_task(task, rng_seed, executor):
        return AgentResult(
            purchases=[], touchpoints=2,
            escalations=[Escalation(reason="no_in_policy_vendor")],
        )

    report = run_eval(task, run_task, n_trials=8)
    assert report.pass_1 == 1.0
    assert report.outcomes == ["pass"] * 8
    assert report.escalation_rate == 1.0


def test_no_in_policy_vendor_task_fails_a_purchase_even_if_verified():
    # wx_alpha is a real, payable vendor in the catalog -- the executor will
    # happily sell it. The task still fails: grading is what enforces "no
    # valid purchase here," not the executor.
    task = TaskSpec.from_json_file(Path("evals/tasks/no_in_policy_vendor_escalates.json"))

    @agent("buys-anyway")
    def run_task(task, rng_seed, executor):
        p = executor.pay("wx_alpha", max_amount=Decimal("999"))
        return AgentResult(
            purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
            touchpoints=1)

    report = run_eval(task, run_task, n_trials=8)
    assert report.pass_1 == 0.0
    assert report.outcomes == ["fail"] * 8
```

Update `tests/test_task_specs.py`'s two affected tests:

```python
@pytest.mark.parametrize("path", TASK_FILES, ids=[p.stem for p in TASK_FILES])
def test_task_spec_is_self_consistent(path):
    task = TaskSpec.from_json_file(path)
    target = cheapest_in_policy_vendor(task)
    if task.grading.expected_purchase is None:
        # A null expected_purchase asserts "no valid purchase exists" --
        # self-consistency means no in-policy vendor exists either.
        assert target is None, (
            f"{path.stem}: expected_purchase is null but an in-policy vendor "
            f"({target.vendor_id if target else None!r}) exists"
        )
        return
    assert target is not None, f"{path.stem}: no in-policy vendor satisfies the mandate"
    assert target.vendor_id == task.grading.expected_purchase.vendor_id, (
        f"{path.stem}: cheapest in-policy vendor is {target.vendor_id}, "
        f"but grading expects {task.grading.expected_purchase.vendor_id}"
    )


@pytest.mark.parametrize("path", TASK_FILES, ids=[p.stem for p in TASK_FILES])
def test_expected_price_within_max(path):
    task = TaskSpec.from_json_file(path)
    if task.grading.expected_purchase is None:
        return
    target = cheapest_in_policy_vendor(task)
    assert target.price_usdc <= task.grading.expected_purchase.max_price_usdc
```

Update `tests/test_run_stub_evals.py`'s `test_writes_one_report_per_task`:

```python
def test_writes_one_report_per_task(tmp_path):
    out = tmp_path / "results"
    reports = main(task_dir=Path("evals/tasks"), out_dir=out, n_trials=8)

    written = sorted(out.glob("*.json"))
    assert len(written) == len(reports) >= 4

    for path in written:
        report = EvalReport.model_validate_json(path.read_text(encoding="utf-8"))
        assert report.agent_id == "stub-v0"
        assert report.budget_violations == 0
        assert report.escalation_rate == 1.0
        assert report.escalation_reasons == {"not_implemented": 8}
        if report.task_id == "no_in_policy_vendor_escalates":
            # The stub always escalates with zero purchases -- which happens
            # to be the correct terminal state for this one task (no valid
            # vendor exists), so it passes here for the right STATE but the
            # wrong REASON: it never distinguishes a real vendor set from an
            # empty one. See the Week-5 design spec's "Known limitations".
            assert report.pass_1 == 1.0
        else:
            assert report.pass_1 == 0.0
            assert report.pass_k == {4: 0.0, 8: 0.0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_harness.py tests/test_task_specs.py tests/test_run_stub_evals.py -v`
Expected: the two new `test_harness.py` tests FAIL with
`FileNotFoundError`/`pydantic.ValidationError` (file doesn't exist yet); the
two modified `test_task_specs.py` tests and
`test_writes_one_report_per_task` still PASS at this point (the new task file
doesn't exist yet, so `TASK_FILES`/`main()` don't see it) — that's expected;
they'll be exercised for real once Step 3 adds the file.

- [ ] **Step 3: Add the task file (already written above) and run again**

The task file and test edits from Step 1 ARE the implementation for this
task — there's no separate "production code" to write. Proceed to Step 4.

Also update `scripts/run_stub_evals.py`'s docstring for accuracy (one clause,
no behavior change):

```python
"""Run the stub agent against every shipped task spec and write EvalReports.

REPORTING ONLY. The stub is expected to score pass^1 = 0, except on
no_in_policy_vendor_escalates, where its blanket escalation happens to match
that task's correct terminal state (see grading.py's expected_purchase=None
branch). This script never fails the build and must never grow a pass-rate
threshold — see CLAUDE.md and
docs/superpowers/specs/2026-09-02-eval-harness-design.md. The gate activates
when a real agent is registered (Week 5+).
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_harness.py tests/test_task_specs.py tests/test_run_stub_evals.py tests/test_models.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add evals/tasks/no_in_policy_vendor_escalates.json tests/test_harness.py \
        tests/test_task_specs.py tests/test_run_stub_evals.py scripts/run_stub_evals.py
git commit -m "Add no_in_policy_vendor_escalates eval task

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019kYbM7aixt9Ruw9d9XodRw"
```

---

### Task 4: Build `claude-planner-v1`

**Files:**
- Modify: `requirements.txt` (add `langchain-anthropic==1.7.2`)
- Modify: `.env.example` (add `ANTHROPIC_API_KEY`)
- Create: `evals/agents/claude_planner.py`
- Test: `tests/test_claude_planner.py`

**Interfaces:**
- Consumes: `evals.harness.in_policy_candidates` (Task 1), `evals.agent_protocol.agent`,
  `evals.executor.PaymentExecutor`, `evals.models.{AgentResult, Escalation, Mandate, Purchase, TaskSpec, Vendor}`.
- Produces: `evals.agents.claude_planner.run_task` (decorated `@agent("claude-planner-v1")`,
  matches `AgentFn`) — Task 5's live-run script imports this.

- [ ] **Step 1: Add the dependency and secret**

In `requirements.txt`, add:

```
langchain-anthropic==1.7.2
```

In `.env.example`, add (after the existing `X402_WALLET_KEY` block):

```

# Anthropic API key for evals/agents/claude_planner.py (claude-planner-v1).
# Required to run that agent at all -- unset in CI, same convention as
# X402_WALLET_KEY above. Get one at https://console.anthropic.com/.
ANTHROPIC_API_KEY=
```

Install it: `python -m pip install -r requirements.txt`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_claude_planner.py`:

```python
from decimal import Decimal

import pytest

from evals.agents.claude_planner import (
    _Decision,
    _ask_claude,
    _build_prompt,
    _token_cost_usdc,
    run_task,
)
from evals.executor import ExecutedPurchase
from evals.models import Mandate, Purchase, TaskSpec, Vendor


# ---- run_task: pre-filter short-circuit (no LLM call) ---------------------

def test_no_in_policy_vendor_escalates_without_calling_llm(sample_task_dict, monkeypatch):
    # Cap set below every vendor's price -- in_policy_candidates is empty, so
    # run_task must escalate WITHOUT ever calling _ask_claude.
    sample_task_dict["mandate"]["budget_cap_usdc"] = "0.001"
    task = TaskSpec.model_validate(sample_task_dict)

    def _boom(*args, **kwargs):
        raise AssertionError("_ask_claude must not be called with no in-policy candidates")

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _boom)

    result = run_task(task, 0, executor=None)
    assert result.purchases == []
    assert result.touchpoints == 2
    assert [e.reason for e in result.escalations] == ["no_in_policy_vendor"]
    assert result.cost_usdc == Decimal("0")


# ---- run_task: LLM decision branching --------------------------------------

class _FakeExecutor:
    def __init__(self, price):
        self._price = price

    def pay(self, target, *, max_amount):
        return ExecutedPurchase(
            vendor_id=target, url=None, amount_paid=self._price,
            pay_to=None, tx_hash=None, verified=True, resource=None)


def test_llm_picks_a_vendor_and_buys_it(sample_task, monkeypatch):
    usage = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}

    def _fake_ask(description, mandate, candidates):
        assert description == sample_task.description
        assert [c.vendor_id for c in candidates] == ["v1"]
        return _Decision(vendor_id="v1", escalate=False, reason=None), usage

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    result = run_task(sample_task, 0, _FakeExecutor(Decimal("0.01")))
    assert len(result.purchases) == 1
    assert result.purchases[0] == Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))
    assert result.touchpoints == 1
    assert result.escalations == []
    # (100 * 1.00 + 20 * 5.00) / 1_000_000 == 0.0002
    assert result.cost_usdc == Decimal("0.0002")


def test_llm_escalates_with_a_reason(sample_task, monkeypatch):
    usage = {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}

    def _fake_ask(description, mandate, candidates):
        return _Decision(vendor_id=None, escalate=True, reason="no candidate fits the task"), usage

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    result = run_task(sample_task, 0, executor=None)
    assert result.purchases == []
    assert result.touchpoints == 2
    assert [e.reason for e in result.escalations] == ["no candidate fits the task"]
    # (50 * 1.00 + 10 * 5.00) / 1_000_000 == 0.0001
    assert result.cost_usdc == Decimal("0.0001")


def test_llm_escalate_true_with_no_reason_falls_back_to_default(sample_task, monkeypatch):
    def _fake_ask(description, mandate, candidates):
        return _Decision(vendor_id=None, escalate=True, reason=None), None

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _fake_ask)

    result = run_task(sample_task, 0, executor=None)
    assert [e.reason for e in result.escalations] == ["planner_escalated"]
    assert result.cost_usdc == Decimal("0")


# ---- _ask_claude: return shape and error handling --------------------------

class _FakeStructuredRunnable:
    def __init__(self, result):
        self._result = result

    def invoke(self, prompt):
        return self._result


class _FakeLLM:
    def __init__(self, result):
        self._result = result
        self.calls = []

    def with_structured_output(self, schema, include_raw=False):
        self.calls.append((schema, include_raw))
        return _FakeStructuredRunnable(self._result)


def test_ask_claude_returns_parsed_decision_and_usage():
    decision = _Decision(vendor_id="v1", escalate=False, reason=None)
    usage = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    fake_raw = type("FakeAIMessage", (), {"usage_metadata": usage})()
    fake_llm = _FakeLLM({"raw": fake_raw, "parsed": decision, "parsing_error": None})

    vendor = Vendor(vendor_id="v1", category="weather-data", price_usdc=Decimal("0.01"))
    mandate = Mandate(goal_category="weather-data", budget_cap_usdc=Decimal("0.05"))

    result, got_usage = _ask_claude("buy weather data", mandate, [vendor], llm=fake_llm)
    assert result is decision
    assert got_usage == usage
    assert fake_llm.calls == [(_Decision, True)]


def test_ask_claude_raises_the_parsing_error():
    boom = ValueError("model did not return valid JSON")
    fake_llm = _FakeLLM({"raw": None, "parsed": None, "parsing_error": boom})

    vendor = Vendor(vendor_id="v1", category="weather-data", price_usdc=Decimal("0.01"))
    mandate = Mandate(goal_category="weather-data", budget_cap_usdc=Decimal("0.05"))

    with pytest.raises(ValueError, match="did not return valid JSON"):
        _ask_claude("buy weather data", mandate, [vendor], llm=fake_llm)


def test_ask_claude_propagates_non_parsing_errors():
    # A network/rate-limit failure raised by .invoke() itself (not a parsing
    # failure caught into parsing_error) must propagate raw -- see the
    # spec's "Error handling" section and this plan's Global Constraints.
    class _ExplodingRunnable:
        def invoke(self, prompt):
            raise RuntimeError("rate limited")

    class _ExplodingLLM:
        def with_structured_output(self, schema, include_raw=False):
            return _ExplodingRunnable()

    vendor = Vendor(vendor_id="v1", category="weather-data", price_usdc=Decimal("0.01"))
    mandate = Mandate(goal_category="weather-data", budget_cap_usdc=Decimal("0.05"))

    with pytest.raises(RuntimeError, match="rate limited"):
        _ask_claude("buy weather data", mandate, [vendor], llm=_ExplodingLLM())


def test_run_task_propagates_llm_exception(sample_task, monkeypatch):
    # Same contract, exercised through run_task: an agent that raises is a
    # bug/infra-failure, never silently downgraded to an escalation (matches
    # evals/harness.py's own module docstring convention for the stub).
    def _boom(*args, **kwargs):
        raise RuntimeError("api down")

    monkeypatch.setattr("evals.agents.claude_planner._ask_claude", _boom)

    with pytest.raises(RuntimeError, match="api down"):
        run_task(sample_task, 0, executor=None)


# ---- _build_prompt ----------------------------------------------------

def test_build_prompt_includes_description_and_every_candidate():
    mandate = Mandate(goal_category="weather-data", budget_cap_usdc=Decimal("0.05"))
    candidates = [
        Vendor(vendor_id="v1", category="weather-data", price_usdc=Decimal("0.01")),
        Vendor(vendor_id="v2", category="weather-data", price_usdc=Decimal("0.03")),
    ]
    prompt = _build_prompt("buy the cheapest feed", mandate, candidates)
    assert "buy the cheapest feed" in prompt
    assert "v1" in prompt and "0.01" in prompt
    assert "v2" in prompt and "0.03" in prompt


def test_build_prompt_omits_quality_line_when_unset():
    mandate = Mandate(goal_category="weather-data", budget_cap_usdc=Decimal("0.05"))
    prompt = _build_prompt("x", mandate, [])
    assert "Quality threshold" not in prompt


def test_build_prompt_includes_quality_line_when_set():
    mandate = Mandate(
        goal_category="weather-data", budget_cap_usdc=Decimal("0.05"),
        quality_threshold=Decimal("4"),
    )
    prompt = _build_prompt("x", mandate, [])
    assert "Quality threshold" in prompt


# ---- _token_cost_usdc ----------------------------------------------------

def test_token_cost_usdc_uses_haiku_pricing():
    usage = {"input_tokens": 1_000_000, "output_tokens": 0, "total_tokens": 1_000_000}
    assert _token_cost_usdc(usage) == Decimal("1.00")

    usage = {"input_tokens": 0, "output_tokens": 1_000_000, "total_tokens": 1_000_000}
    assert _token_cost_usdc(usage) == Decimal("5.00")


def test_token_cost_usdc_zero_for_missing_usage():
    assert _token_cost_usdc(None) == Decimal("0")


def test_token_cost_usdc_rejects_unknown_model(monkeypatch):
    monkeypatch.setattr("evals.agents.claude_planner._MODEL", "some-other-model")
    with pytest.raises(ValueError, match="no known USDC pricing"):
        _token_cost_usdc({"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_claude_planner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.agents.claude_planner'`

- [ ] **Step 4: Implement**

Create `evals/agents/claude_planner.py`:

```python
"""claude-planner-v1: a single structured LLM call over a deterministically
pre-filtered candidate list.

See docs/superpowers/specs/2026-09-15-week5-planner-v1-design.md.

Policy enforcement (category, budget, allowlist) happens entirely in
evals.harness.in_policy_candidates -- the same function
evals.harness.cheapest_in_policy_vendor calls for grading's own target-vendor
metric. The LLM below is never shown a vendor that function excludes, so "the
LLM picked an out-of-policy vendor" is structurally impossible, not just
tested-for.
"""

from __future__ import annotations

import os
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import UsageMetadata
from pydantic import BaseModel, Field

from evals.agent_protocol import agent
from evals.executor import PaymentExecutor
from evals.harness import in_policy_candidates
from evals.models import AgentResult, Escalation, Mandate, Purchase, TaskSpec, Vendor

# Bare model id, no date suffix -- confirmed against the live API's current
# pricing table (claude-api skill, 2026-09-15). A date-suffixed variant is
# used elsewhere in this project's own tooling; that is a different string.
_MODEL = os.environ.get("PLANNER_MODEL", "claude-haiku-4-5")

# USDC per token, keyed by the exact model id in _MODEL. Sourced from the
# claude-api skill's pricing table, not assumed. Add an entry here -- do not
# guess a price -- before pointing PLANNER_MODEL at a different model.
_PRICE_PER_MILLION_TOKENS_USDC: dict[str, tuple[Decimal, Decimal]] = {
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
}


class _Decision(BaseModel):
    vendor_id: Optional[str] = Field(
        default=None,
        description="The chosen vendor_id from the candidate list, or null if escalating.",
    )
    escalate: bool = Field(
        description="True if no candidate genuinely satisfies the task; false otherwise.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Required when escalate is true: a short reason a human can act on.",
    )


@agent("claude-planner-v1")
def run_task(task: TaskSpec, rng_seed: int, executor: PaymentExecutor) -> AgentResult:
    candidates = in_policy_candidates(task)
    if not candidates:
        return AgentResult(
            purchases=[],
            touchpoints=2,
            escalations=[Escalation(reason="no_in_policy_vendor")],
            trace=["no in-policy candidate; escalated without an LLM call"],
        )

    decision, usage = _ask_claude(task.description, task.mandate, candidates)
    cost = _token_cost_usdc(usage)

    if decision.escalate or decision.vendor_id is None:
        return AgentResult(
            purchases=[],
            touchpoints=2,
            escalations=[Escalation(reason=decision.reason or "planner_escalated")],
            cost_usdc=cost,
            trace=[f"LLM escalated: {decision.reason}"],
        )

    executed = executor.pay(decision.vendor_id, max_amount=task.mandate.budget_cap_usdc)
    return AgentResult(
        purchases=[Purchase(vendor_id=executed.vendor_id, price_usdc=executed.amount_paid)],
        touchpoints=1,
        cost_usdc=cost,
        trace=[f"picked {executed.vendor_id} from {len(candidates)} in-policy candidate(s)"],
    )


def _ask_claude(
    description: str,
    mandate: Mandate,
    candidates: list[Vendor],
    llm: BaseChatModel | None = None,
) -> tuple[_Decision, UsageMetadata | None]:
    llm = llm or ChatAnthropic(model=_MODEL, temperature=0)
    # include_raw=True: the parsed _Decision alone drops token-usage metadata,
    # which _token_cost_usdc needs. Confirmed against langchain_core's own
    # with_structured_output source: with include_raw=True a parsing failure
    # is CAUGHT and returned in parsing_error, not raised -- unlike the
    # include_raw=False default. Must check it explicitly, or a parse failure
    # silently becomes parsed=None, which run_task would otherwise misreport
    # as an agent decision instead of an LLM/parsing bug.
    structured = llm.with_structured_output(_Decision, include_raw=True)
    result = structured.invoke(_build_prompt(description, mandate, candidates))
    if result["parsing_error"] is not None:
        raise result["parsing_error"]
    return result["parsed"], result["raw"].usage_metadata


def _build_prompt(description: str, mandate: Mandate, candidates: list[Vendor]) -> str:
    candidate_lines = "\n".join(
        f"- vendor_id={c.vendor_id!r}, price_usdc={c.price_usdc}" for c in candidates
    )
    quality_line = (
        f"Quality threshold (informational only -- no vendor field carries a "
        f"quality score yet): {mandate.quality_threshold}\n"
        if mandate.quality_threshold is not None
        else ""
    )
    return (
        "You are a procurement agent buying a single digital good under a "
        "fixed budget, on behalf of a human who will not be consulted again.\n"
        f"Task: {description}\n"
        f"Goal category: {mandate.goal_category}\n"
        f"Budget cap (USDC): {mandate.budget_cap_usdc}\n"
        f"{quality_line}"
        "Candidates (already filtered to in-policy vendors -- category, "
        "allowlist, and budget are already satisfied by every one of these; "
        "pick one or escalate):\n"
        f"{candidate_lines}\n\n"
        "Pick the candidate that best satisfies the task's stated intent. If "
        "none of the candidates genuinely fit the task, set escalate=true and "
        "give a short reason. Otherwise set vendor_id to the chosen "
        "candidate's vendor_id and escalate=false."
    )


def _token_cost_usdc(usage: UsageMetadata | None) -> Decimal:
    if not usage:
        return Decimal("0")
    try:
        price_in, price_out = _PRICE_PER_MILLION_TOKENS_USDC[_MODEL]
    except KeyError:
        raise ValueError(
            f"no known USDC pricing for model {_MODEL!r}; add it to "
            "_PRICE_PER_MILLION_TOKENS_USDC in evals/agents/claude_planner.py "
            "before using this model"
        )
    million = Decimal(1_000_000)
    cost = (
        Decimal(usage["input_tokens"]) * price_in
        + Decimal(usage["output_tokens"]) * price_out
    ) / million
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_claude_planner.py -v`
Expected: all PASS. Then run the full offline suite to confirm nothing else
broke: `python -m pytest -v` (this still excludes `integration`/`manual` per
`pyproject.toml`'s `addopts`, and makes no network call — `_ask_claude` is
monkeypatched or given a fake `llm` in every test above).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .env.example evals/agents/claude_planner.py tests/test_claude_planner.py
git commit -m "Add claude-planner-v1 agent

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019kYbM7aixt9Ruw9d9XodRw"
```

---

### Task 5: Live, cost-bearing verification script

Per the spec's own note, this is the "does this agent actually work" evidence
CLAUDE.md rule 3 wants — but it spends real money on every run, so it is a
standalone script, not a pytest test, and is never run in CI. This mirrors
`scripts/run_stub_evals.py` exactly, scoped to `synthetic` task specs only
(the one `real_x402` spec, `real_weather_sepolia.json`, needs a funded wallet
and a live seller — an already-covered, separate concern; see
`tests/test_harness_real_x402.py`).

**Files:**
- Create: `scripts/run_claude_planner_evals.py`
- Modify: `pyproject.toml` (add a `per-file-ignores` entry for the new
  script's `sys.path` shim, same reason `run_stub_evals.py` has one)
- Test: `tests/test_run_claude_planner_evals.py` (offline only — verifies the
  API-key guard, never calls the real API)

**Interfaces:**
- Consumes: `evals.agents.claude_planner.run_task` (Task 4),
  `evals.harness.run_eval`, `evals.models.{EvalReport, TaskSpec}`.
- Produces: nothing further downstream — this is the terminal script for
  Week 5.

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_claude_planner_evals.py`:

```python
from pathlib import Path

from scripts.run_claude_planner_evals import main


def test_requires_api_key_and_makes_no_network_call(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "results"
    reports = main(task_dir=Path("evals/tasks"), out_dir=out, n_trials=1)
    assert reports == []
    # out_dir must never be created when the guard trips -- a later run with
    # the key set should not find a stale empty directory implying success.
    assert not out.exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/test_run_claude_planner_evals.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.run_claude_planner_evals'`

- [ ] **Step 3: Implement**

Create `scripts/run_claude_planner_evals.py`:

```python
"""Run claude-planner-v1 against every SYNTHETIC task spec and write EvalReports.

LIVE, COST-BEARING, NOT CI-GATED. Each run makes real, billed Claude API
calls (see docs/superpowers/specs/2026-09-15-week5-planner-v1-design.md,
"Testing"). Requires ANTHROPIC_API_KEY. Mirrors scripts/run_stub_evals.py's
structure and, like it, skips real_x402 task specs -- those need a funded
wallet and a live seller (tests/test_harness_real_x402.py), a separate
concern from "does the LLM call work."
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow `python scripts/run_claude_planner_evals.py` from the repo root:
# Python only puts this file's directory on sys.path, not the repo root, so
# `import evals` would fail. Running as
# `python -m scripts.run_claude_planner_evals` or under pytest is fine
# without this; the shim just makes direct execution work too.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.agents.claude_planner import run_task as claude_planner_run_task
from evals.harness import run_eval
from evals.models import EvalReport, TaskSpec


def main(
    task_dir: Path = Path("evals/tasks"),
    out_dir: Path = Path("evals/results"),
    n_trials: int = 8,
) -> list[EvalReport]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set -- this script makes real, billed "
            "Claude API calls. Set it (see .env.example) and re-run."
        )
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    reports: list[EvalReport] = []

    for path in sorted(Path(task_dir).glob("*.json")):
        task = TaskSpec.from_json_file(path)
        if task.environment.kind != "synthetic":
            continue
        report = run_eval(task, claude_planner_run_task, n_trials=n_trials)
        out_path = out_dir / f"{report.task_id}_{report.date_utc}.json"
        out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        reports.append(report)

    _print_table(reports)
    return reports


def _print_table(reports: list[EvalReport]) -> None:
    header = (
        f"{'task_id':<34} {'pass^1 (95% CI)':>20} {'pass^4':>7} {'pass^8':>7} "
        f"{'tp/bskt':>8} {'budget_viol':>12} {'esc_rate':>9} {'cost/tx':>9}"
    )
    print(header)
    print("-" * len(header))
    for r in reports:
        lo, hi = r.pass_1_ci
        pass_1_col = f"{r.pass_1:.2f} [{lo:.2f}, {hi:.2f}]"
        cost_col = (
            f"{r.cost_per_completed_tx_usdc:.6f}"
            if r.cost_per_completed_tx_usdc is not None
            else "n/a"
        )
        print(
            f"{r.task_id:<34} "
            f"{pass_1_col:>20} "
            f"{r.pass_k.get(4, 0.0):>7.2f} "
            f"{r.pass_k.get(8, 0.0):>7.2f} "
            f"{r.touchpoints_per_basket:>8.2f} "
            f"{r.budget_violations:>12d} "
            f"{r.escalation_rate:>9.2f} "
            f"{cost_col:>9}"
        )
    print()
    print(
        "LIVE RUN -- real, billed Claude API calls. Not gated in CI; run by "
        "hand and record results in a docs/week5-*.md file, matching Week "
        "4's live-verification convention (docs/week4-spend-permission-live-verification.md)."
    )


if __name__ == "__main__":
    main()
```

Add to `pyproject.toml`'s `[tool.ruff.lint.per-file-ignores]`:

```toml
"scripts/run_claude_planner_evals.py" = ["E402"]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_run_claude_planner_evals.py -v`
Expected: PASS. Then run `ruff check .` to confirm the new per-file-ignore is
correctly picked up.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_claude_planner_evals.py tests/test_run_claude_planner_evals.py pyproject.toml
git commit -m "Add live claude-planner-v1 verification script

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019kYbM7aixt9Ruw9d9XodRw"
```

---

## After this plan lands

Run `python scripts/run_claude_planner_evals.py` by hand with a real
`ANTHROPIC_API_KEY` set, against all 5 synthetic task specs (the design
spec's own "Known limitations" section predicts every one passes at or near
pass^1 = 1.0, since each has a unique cheapest in-policy candidate — this is
expected, not a sign the LLM step is doing nothing useful yet; see that
section for why it's still the right interface to build now). Record the
real result — pass^1, pass^k, cost/completed-tx — in a
`docs/week5-claude-planner-live-run.md` file, matching Week 4's
`docs/week4-spend-permission-live-verification.md` convention, rather than
leaving it only in a local terminal scrollback.
