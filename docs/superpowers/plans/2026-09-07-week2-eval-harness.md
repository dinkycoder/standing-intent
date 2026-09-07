# Week 2 Eval Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a statistical evaluation harness for the procurement agent that grades terminal state against synthetic task specs, computes the day-one metrics, runs an always-failing stub agent to satisfy `CLAUDE.md` rule 3, and gates CI on the harness's own unit tests.

**Architecture:** A new top-level `evals/` Python package holding typed data models, an agent-interface contract, pure terminal-state grading, and an aggregating harness. Task specs are plain JSON with an embedded synthetic vendor catalog — no network, no chain, no wallet. A stub agent that always fails proves the pipeline end to end. CI runs the deterministic harness/grading tests as a gate and runs the stub eval as a non-gating report.

**Tech Stack:** Python 3.12, pydantic v2 (typed models + JSON parsing), `decimal.Decimal` for all money, pytest (deterministic tests), PyYAML (CI-workflow test), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-02-eval-harness-design.md` — read it alongside this plan. This plan argues from that spec; where it extends or deviates, it says so inline.

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from `CLAUDE.md`, `docs/superpowers/specs/2026-09-02-eval-harness-design.md`, and `.claude/agents/evals.md` / `.claude/agents/tests.md`.

- **Language:** Python 3.11+ (repo runs 3.12.10). The graded artifact must be Python.
- **Money is never a float.** All USDC amounts are decimal strings in JSON and `decimal.Decimal` in code. A `float` reaching a money field is a bug and must raise, not coerce. (USDC has 6 decimals; a float invites silent precision bugs — `probe/findings.md` §3/§6.)
- **Grade terminal state, not process.** "Did the right vendor get bought, under budget?" Never assert "a function was called."
- **Tests must catch wrong-but-plausible output.** A test that only asserts "returned a number" / "returned a `GradeOutcome`" is inadequate. Assert against values that would be wrong if the logic were subtly broken.
- **Budget-adherence violations get a dedicated hard-fail signal**, separate from the generic pass/fail bit. The counter must be able to read exactly zero, and a violation must be loud.
- **A crash or malformed input is a bug, not a grade.** A malformed task spec or an agent that raises propagates as an exception. It is never silently recorded as a `FAIL` — conflating a crash with an honest policy failure corrupts the pass-rate numbers.
- **Statistics:** every eval runs `n` trials, records `seed`, `agent identifier`, and `date`. Report `pass^1` and `pass^k` for `k ∈ {4, 8}` side by side. `pass^k` here means "all `k` independent attempts succeed" (the τ-bench reliability metric), estimated unbiased from `n` trials as `C(successes, k) / C(n, k)`.
- **CI:** the deterministic harness/grading unit tests gate the build. The stub eval run is reporting-only and must **not** gate — never add a pass-rate threshold to it. The gate activates when a non-stub agent is registered (Week 5+); that threshold will be added deliberately and recorded in the PR. Silently lowering or faking a bar is the one thing that makes the harness worthless.
- **No network, no chain, no real keys, no real funds** anywhere in this package or its tests. Everything is in-memory synthetic.
- **Pinned dependencies.** Exact `==` pins in `requirements.txt` and `requirements-dev.txt`. If `pip` resolves a different version than this plan names, use what `pip` resolved and record it.
- **Environment:** Windows / PowerShell. Use PowerShell command forms. Always `python -m pytest`, never bare `pytest`. Run all commands from the repo root.
- **Commits:** one per task, imperative subject matching repo history (e.g. "Add evals data models and task-spec loader"). End every commit message with the repo's standard trailer:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: <this session's URL>
  ```
- **Deviations from the spec, made deliberately in this plan:**
  1. The spec's single `tests/test_harness.py` is realized as `tests/test_grading.py` (pure grading rules) + `tests/test_harness.py` (aggregation, `pass^k` math, counters). Both gate CI. Better factoring, same coverage.
  2. The spec names `evals/harness.py` as the thing that "grades terminal state ... aggregates". This plan splits pure grading into `evals/grading.py`, which `harness.py` imports, so grading is testable in isolation.
  3. Every Week-2 sample task expects a **purchase** (never "escalate instead of buying"). Grading an escalation as the correct outcome needs the policy layer (Week 6) and is out of scope. `AgentResult.escalations` is still collected and drives the escalation-rate / reason-breakdown counters.

---

## File Structure

```
requirements.txt                     # runtime deps (pydantic)
requirements-dev.txt                  # test deps (pytest, PyYAML)
pyproject.toml                        # pytest config only
.gitignore                            # + evals/results/

evals/
  __init__.py                         # empty marker
  models.py                           # UsdcAmount, Vendor, Mandate, ExpectedPurchase, Grading,
                                      #   Environment, TaskSpec(+from_json_file), Purchase,
                                      #   Escalation, AgentResult, EvalReport
  agent_protocol.py                   # AgentFn type, @agent(id) decorator, require_agent_id()
  grading.py                          # GradeOutcome enum, grade(result, task) -> GradeOutcome
  harness.py                          # pass_k(), in_policy_vendors(), cheapest_in_policy_vendor(),
                                      #   run_eval(task, agent_fn, n_trials, base_seed) -> EvalReport
  agents/
    __init__.py                       # empty marker
    stub.py                           # @agent("stub-v0") run_task(task, rng_seed) -> AgentResult
  tasks/
    single_vendor_under_budget.json
    cheapest_of_three.json
    cheapest_over_budget_pick_next.json
    allowlist_excludes_cheapest.json
  results/                            # runtime output, git-ignored, created on demand
  README.md                          # what the package is, how to add a task, how to run

scripts/
  run_stub_evals.py                   # load evals/tasks/*.json, run stub n=8, write results, print table

tests/
  __init__.py                         # empty marker
  conftest.py                         # shared fixtures: sample task dict/file/object, make_result
  test_models.py                      # spec parsing, Decimal-not-float, malformed -> ValidationError
  test_agent_protocol.py              # @agent decorator, require_agent_id
  test_grading.py                     # every GradeOutcome path, budget-violation override
  test_harness.py                     # run_eval aggregation, pass_k math, counters, exception propagation
  test_stub_agent.py                  # stub shape + stub grades FAIL on every sample task
  test_task_specs.py                  # every shipped task loads and is self-consistent
  test_ci_workflow.py                 # evals.yml parses, two jobs, gating runs pytest, report is non-gating

.github/
  workflows/
    evals.yml                         # job harness-tests (GATING) + job stub-eval-report (NON-GATING)
```

---

## Task 1: Data models, task-spec loader, and project scaffold

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`
- Create: `evals/__init__.py`, `evals/agents/__init__.py`, `tests/__init__.py`
- Create: `evals/models.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`
- Modify: `.gitignore` (add `evals/results/`)

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - `evals.models.UsdcAmount` — `Annotated[Decimal, BeforeValidator(...)]`; rejects `float` and `bool`, accepts `str`/`int`/`Decimal`.
  - `evals.models.Vendor(vendor_id: str, category: str, price_usdc: Decimal, in_allowlist: bool = True)`
  - `evals.models.Mandate(goal_category: str, budget_cap_usdc: Decimal, vendor_allowlist: list[str] | None = None, quality_threshold: Decimal | None = None)`
  - `evals.models.ExpectedPurchase(vendor_id: str, max_price_usdc: Decimal)`
  - `evals.models.Grading(expected_purchase: ExpectedPurchase, budget_adherence_required: bool = True)`
  - `evals.models.Environment(vendors: list[Vendor])`
  - `evals.models.TaskSpec(task_id: str, description: str, mandate: Mandate, environment: Environment, grading: Grading)` with classmethod `from_json_file(path: str | pathlib.Path) -> TaskSpec`
  - `evals.models.Purchase(vendor_id: str, price_usdc: Decimal)`
  - `evals.models.Escalation(reason: str)`
  - `evals.models.AgentResult(purchases: list[Purchase] = [], touchpoints: int, escalations: list[Escalation] = [], cost_usdc: Decimal = Decimal("0"), trace: list[str] = [])` — `touchpoints` counts human interactions *including* the mandatory initial mandate signature (so a perfect run = 1; each escalation or confirmation adds 1).
  - `evals.models.EvalReport(task_id: str, agent_id: str, date_utc: str, base_seed: int, n_trials: int, outcomes: list[str], pass_1: float, pass_k: dict[int, float], touchpoints_per_basket: float, budget_violations: int, best_price_capture_rate: float, cost_per_completed_tx_usdc: Decimal | None, escalation_rate: float, escalation_reasons: dict[str, int])`

- [ ] **Step 1: Create the dependency and config files**

`requirements.txt`:
```
pydantic==2.13.5
```

`requirements-dev.txt`:
```
pytest==8.3.4
PyYAML==6.0.2
```

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-ra"
```

Then create the empty package markers:
```powershell
New-Item -ItemType File evals\__init__.py
New-Item -ItemType File evals\agents\__init__.py
New-Item -ItemType File tests\__init__.py
```

- [ ] **Step 2: Install dependencies**

Run:
```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
```
Expected: pydantic already present (2.13.5), pytest and PyYAML install. If pip resolves different versions, update the two requirements files to the resolved versions (`python -m pip show pytest pydantic pyyaml`).

- [ ] **Step 3: Add `evals/results/` to `.gitignore`**

Append under the `# python` section of `.gitignore`:
```
# eval run artifacts (reports, not source)
evals/results/
```

- [ ] **Step 4: Write the failing model tests**

Create `tests/conftest.py`:
```python
import copy
import json

import pytest

SAMPLE_TASK = {
    "task_id": "sample",
    "description": "sample task for tests",
    "mandate": {
        "goal_category": "weather-data",
        "budget_cap_usdc": "0.05",
        "vendor_allowlist": None,
        "quality_threshold": None,
    },
    "environment": {
        "vendors": [
            {"vendor_id": "v1", "category": "weather-data", "price_usdc": "0.01", "in_allowlist": True},
            {"vendor_id": "v2", "category": "weather-data", "price_usdc": "0.08", "in_allowlist": True},
        ]
    },
    "grading": {
        "expected_purchase": {"vendor_id": "v1", "max_price_usdc": "0.05"},
        "budget_adherence_required": True,
    },
}


@pytest.fixture
def sample_task_dict():
    return copy.deepcopy(SAMPLE_TASK)


@pytest.fixture
def sample_task_file(tmp_path, sample_task_dict):
    path = tmp_path / "sample_task.json"
    path.write_text(json.dumps(sample_task_dict), encoding="utf-8")
    return path


@pytest.fixture
def sample_task(sample_task_file):
    from evals.models import TaskSpec

    return TaskSpec.from_json_file(sample_task_file)
```

Create `tests/test_models.py`:
```python
from decimal import Decimal

import pytest
from pydantic import ValidationError

from evals.models import AgentResult, Escalation, Purchase, TaskSpec


def test_loads_sample_task_with_decimal_money(sample_task_file):
    task = TaskSpec.from_json_file(sample_task_file)
    assert task.task_id == "sample"
    assert task.mandate.budget_cap_usdc == Decimal("0.05")
    assert isinstance(task.mandate.budget_cap_usdc, Decimal)
    assert task.environment.vendors[0].price_usdc == Decimal("0.01")
    assert task.grading.expected_purchase.max_price_usdc == Decimal("0.05")


def test_float_money_is_rejected(sample_task_dict):
    sample_task_dict["mandate"]["budget_cap_usdc"] = 0.05  # float, not "0.05"
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_bool_money_is_rejected(sample_task_dict):
    sample_task_dict["mandate"]["budget_cap_usdc"] = True
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_missing_required_field_raises(sample_task_dict):
    del sample_task_dict["grading"]
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_string_and_int_money_are_accepted(sample_task_dict):
    sample_task_dict["environment"]["vendors"][0]["price_usdc"] = 1  # int -> Decimal("1")
    task = TaskSpec.model_validate(sample_task_dict)
    assert task.environment.vendors[0].price_usdc == Decimal("1")


def test_agent_result_defaults():
    result = AgentResult(touchpoints=1)
    assert result.purchases == []
    assert result.escalations == []
    assert result.cost_usdc == Decimal("0")
    assert result.trace == []


def test_agent_result_roundtrips_through_json():
    result = AgentResult(
        purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))],
        touchpoints=1,
        escalations=[Escalation(reason="not_implemented")],
        cost_usdc=Decimal("0"),
        trace=["did a thing"],
    )
    reloaded = AgentResult.model_validate_json(result.model_dump_json())
    assert reloaded == result
```

- [ ] **Step 5: Run the model tests to verify they fail**

Run:
```powershell
python -m pytest tests/test_models.py -v
```
Expected: FAIL / collection error — `ModuleNotFoundError: No module named 'evals.models'`.

- [ ] **Step 6: Implement `evals/models.py`**

```python
"""Typed data structures for the eval harness.

All money is decimal.Decimal. A float reaching a money field is a bug and raises
(see UsdcAmount) rather than being silently coerced — USDC has 6 decimals and a
float invites precision bugs (probe/findings.md sections 3 and 6).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _strict_decimal(value: object) -> Decimal:
    # bool is an int subclass; reject it explicitly before the int branch.
    if isinstance(value, bool):
        raise TypeError("bool is not a valid USDC amount")
    if isinstance(value, float):
        raise TypeError("USDC amounts must be decimal strings, not float")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (str, int)):
        return Decimal(str(value))
    raise TypeError(f"unsupported type for USDC amount: {type(value)!r}")


UsdcAmount = Annotated[Decimal, BeforeValidator(_strict_decimal)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Vendor(_Model):
    vendor_id: str
    category: str
    price_usdc: UsdcAmount
    in_allowlist: bool = True


class Mandate(_Model):
    goal_category: str
    budget_cap_usdc: UsdcAmount
    vendor_allowlist: Optional[list[str]] = None
    quality_threshold: Optional[UsdcAmount] = None


class ExpectedPurchase(_Model):
    vendor_id: str
    max_price_usdc: UsdcAmount


class Grading(_Model):
    expected_purchase: ExpectedPurchase
    budget_adherence_required: bool = True


class Environment(_Model):
    vendors: list[Vendor]


class TaskSpec(_Model):
    task_id: str
    description: str
    mandate: Mandate
    environment: Environment
    grading: Grading

    @classmethod
    def from_json_file(cls, path: str | Path) -> "TaskSpec":
        raw = Path(path).read_text(encoding="utf-8")
        return cls.model_validate(json.loads(raw))


class Purchase(_Model):
    vendor_id: str
    price_usdc: UsdcAmount


class Escalation(_Model):
    reason: str


class AgentResult(_Model):
    """What an agent returns for a single trial.

    touchpoints counts human interactions INCLUDING the mandatory initial mandate
    signature. A flawless unattended run therefore reports touchpoints == 1. Each
    escalation or confirmation prompt the agent raised adds 1.
    """

    purchases: list[Purchase] = Field(default_factory=list)
    touchpoints: int
    escalations: list[Escalation] = Field(default_factory=list)
    cost_usdc: UsdcAmount = Decimal("0")
    trace: list[str] = Field(default_factory=list)


class EvalReport(_Model):
    task_id: str
    agent_id: str
    date_utc: str
    base_seed: int
    n_trials: int
    outcomes: list[str]
    pass_1: float
    pass_k: dict[int, float]
    touchpoints_per_basket: float
    budget_violations: int
    best_price_capture_rate: float
    cost_per_completed_tx_usdc: Optional[UsdcAmount]
    escalation_rate: float
    escalation_reasons: dict[str, int]
```

- [ ] **Step 7: Run the model tests to verify they pass**

Run:
```powershell
python -m pytest tests/test_models.py -v
```
Expected: PASS — all 8 tests green.

- [ ] **Step 8: Run the whole suite**

Run:
```powershell
python -m pytest -v
```
Expected: PASS (only `test_models.py` exists so far).

- [ ] **Step 9: Commit**

```powershell
git add requirements.txt requirements-dev.txt pyproject.toml .gitignore evals tests
git commit
```
Message: `Add evals data models and task-spec loader` + standard trailer.

---

## Task 2: Agent-interface contract

**Files:**
- Create: `evals/agent_protocol.py`
- Create: `tests/test_agent_protocol.py`

**Interfaces:**
- Consumes: `evals.models.TaskSpec`, `evals.models.AgentResult`.
- Produces:
  - `evals.agent_protocol.AgentFn` — `Callable[[TaskSpec, int], AgentResult]` (type alias, for annotations).
  - `evals.agent_protocol.agent(agent_id: str)` — decorator that attaches `.agent_id = agent_id` to a `run_task` function and returns it unchanged otherwise.
  - `evals.agent_protocol.require_agent_id(fn: object) -> str` — returns `fn.agent_id` or raises `TypeError` with a message telling the caller to wrap the function with `@agent("...")`.

Rationale: the spec keeps `run_eval(task, agent_fn, n_trials)` at three args, but `EvalReport` needs an agent identifier. Rather than add a parameter, the identifier rides on the function as an attribute set by the `@agent` decorator. The harness reads it via `require_agent_id`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_agent_protocol.py`:
```python
import pytest

from evals.agent_protocol import agent, require_agent_id
from evals.models import AgentResult


def test_agent_decorator_attaches_id_and_preserves_call():
    @agent("demo-v1")
    def run_task(task, rng_seed):
        return AgentResult(touchpoints=1)

    assert run_task.agent_id == "demo-v1"
    result = run_task(None, 0)
    assert isinstance(result, AgentResult)


def test_require_agent_id_returns_the_id():
    @agent("demo-v1")
    def run_task(task, rng_seed):
        return AgentResult(touchpoints=1)

    assert require_agent_id(run_task) == "demo-v1"


def test_require_agent_id_raises_for_undecorated_function():
    def run_task(task, rng_seed):
        return AgentResult(touchpoints=1)

    with pytest.raises(TypeError, match="@agent"):
        require_agent_id(run_task)


def test_require_agent_id_rejects_empty_id():
    with pytest.raises(ValueError):

        @agent("")
        def run_task(task, rng_seed):
            return AgentResult(touchpoints=1)
```

- [ ] **Step 2: Run to verify failure**

Run:
```powershell
python -m pytest tests/test_agent_protocol.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.agent_protocol'`.

- [ ] **Step 3: Implement `evals/agent_protocol.py`**

```python
"""The one interface every agent under test implements.

An agent is a callable ``run_task(task: TaskSpec, rng_seed: int) -> AgentResult``.
It carries a stable string id, attached by the ``@agent("...")`` decorator, which
the harness records in every EvalReport.
"""

from __future__ import annotations

from typing import Callable

from evals.models import AgentResult, TaskSpec

AgentFn = Callable[[TaskSpec, int], AgentResult]


def agent(agent_id: str) -> Callable[[AgentFn], AgentFn]:
    if not agent_id:
        raise ValueError("agent_id must be a non-empty string")

    def decorate(fn: AgentFn) -> AgentFn:
        fn.agent_id = agent_id  # type: ignore[attr-defined]
        return fn

    return decorate


def require_agent_id(fn: object) -> str:
    agent_id = getattr(fn, "agent_id", None)
    if not isinstance(agent_id, str) or not agent_id:
        raise TypeError(
            "agent function has no agent_id; wrap it with @agent(\"your-id\") "
            "from evals.agent_protocol"
        )
    return agent_id
```

- [ ] **Step 4: Run to verify pass**

Run:
```powershell
python -m pytest tests/test_agent_protocol.py -v
```
Expected: PASS — 4 tests green.

- [ ] **Step 5: Commit**

```powershell
git add evals/agent_protocol.py tests/test_agent_protocol.py
git commit
```
Message: `Add agent-interface contract for the eval harness` + standard trailer.

---

## Task 3: Terminal-state grading

**Files:**
- Create: `evals/grading.py`
- Modify: `tests/conftest.py` (append a `make_result` fixture)
- Create: `tests/test_grading.py`

**Interfaces:**
- Consumes: `evals.models.TaskSpec`, `evals.models.AgentResult`.
- Produces:
  - `evals.grading.GradeOutcome` — `str`-valued `Enum`: `PASS = "pass"`, `FAIL = "fail"`, `BUDGET_VIOLATION = "budget_violation"`.
  - `evals.grading.grade(result: AgentResult, task: TaskSpec) -> GradeOutcome` — pure. Rules, in order:
    1. If `task.grading.budget_adherence_required` and `sum(p.price_usdc for p in result.purchases) > task.mandate.budget_cap_usdc` → `BUDGET_VIOLATION` (checked first; overrides everything, including a wrong purchase count).
    2. If `len(result.purchases) != 1` → `FAIL`.
    3. If the single purchase's `vendor_id == task.grading.expected_purchase.vendor_id` **and** its `price_usdc <= task.grading.expected_purchase.max_price_usdc` → `PASS`.
    4. Otherwise → `FAIL`.

- [ ] **Step 1: Append the `make_result` fixture to `tests/conftest.py`**

```python
@pytest.fixture
def make_result():
    from decimal import Decimal

    from evals.models import AgentResult, Escalation, Purchase

    def _make(purchases=None, touchpoints=1, escalations=None, cost_usdc="0", trace=None):
        return AgentResult(
            purchases=[
                Purchase(vendor_id=vid, price_usdc=Decimal(str(price)))
                for vid, price in (purchases or [])
            ],
            touchpoints=touchpoints,
            escalations=[Escalation(reason=r) for r in (escalations or [])],
            cost_usdc=Decimal(str(cost_usdc)),
            trace=trace or [],
        )

    return _make
```

- [ ] **Step 2: Write the failing grading tests**

Create `tests/test_grading.py`:
```python
from decimal import Decimal

from evals.grading import GradeOutcome, grade


def test_correct_vendor_under_budget_passes(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.01")])
    assert grade(result, sample_task) is GradeOutcome.PASS


def test_wrong_vendor_fails(sample_task, make_result):
    result = make_result(purchases=[("v2", "0.02")])
    assert grade(result, sample_task) is GradeOutcome.FAIL


def test_no_purchase_fails(sample_task, make_result):
    result = make_result(purchases=[], escalations=["gave_up"])
    assert grade(result, sample_task) is GradeOutcome.FAIL


def test_two_purchases_fail_even_if_one_is_right(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.01"), ("v2", "0.01")])
    # total 0.02 <= cap 0.05, so not a violation; but count != 1 -> FAIL
    assert grade(result, sample_task) is GradeOutcome.FAIL


def test_overspend_is_budget_violation_not_fail(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.09")])  # over the 0.05 cap
    assert grade(result, sample_task) is GradeOutcome.BUDGET_VIOLATION


def test_budget_violation_overrides_wrong_count(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.04"), ("v2", "0.04")])  # total 0.08 > 0.05
    assert grade(result, sample_task) is GradeOutcome.BUDGET_VIOLATION


def test_right_vendor_above_max_price_but_under_cap_fails(sample_task, make_result):
    # Lower the expected max_price below the cap so there is room between them.
    sample_task.grading.expected_purchase.max_price_usdc = Decimal("0.03")
    result = make_result(purchases=[("v1", "0.04")])  # 0.04 <= cap 0.05 (no violation), > max 0.03
    assert grade(result, sample_task) is GradeOutcome.FAIL


def test_price_just_over_cap_is_violation(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.051")])  # 0.051 > cap 0.05
    assert grade(result, sample_task) is GradeOutcome.BUDGET_VIOLATION


def test_price_equal_to_cap_is_allowed(sample_task, make_result):
    result = make_result(purchases=[("v1", "0.05")])
    # 0.05 == cap (inclusive, not a violation) and 0.05 <= max_price 0.05 -> PASS
    assert grade(result, sample_task) is GradeOutcome.PASS


def test_budget_adherence_not_required_lets_overspend_through_to_fail(sample_task, make_result):
    sample_task.grading.budget_adherence_required = False
    result = make_result(purchases=[("v1", "0.09")])
    # no violation path; count == 1, vendor right, but 0.09 > max_price 0.05 -> FAIL
    assert grade(result, sample_task) is GradeOutcome.FAIL
```

- [ ] **Step 3: Run to verify failure**

Run:
```powershell
python -m pytest tests/test_grading.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.grading'`.

- [ ] **Step 4: Implement `evals/grading.py`**

```python
"""Pure terminal-state grading. No I/O, no agent introspection.

Grades the OUTCOME an agent produced against a task's grading criteria. It never
asks how the agent got there.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from evals.models import AgentResult, TaskSpec


class GradeOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    BUDGET_VIOLATION = "budget_violation"


def grade(result: AgentResult, task: TaskSpec) -> GradeOutcome:
    total_spend = sum((p.price_usdc for p in result.purchases), Decimal("0"))

    if (
        task.grading.budget_adherence_required
        and total_spend > task.mandate.budget_cap_usdc
    ):
        return GradeOutcome.BUDGET_VIOLATION

    if len(result.purchases) != 1:
        return GradeOutcome.FAIL

    purchase = result.purchases[0]
    expected = task.grading.expected_purchase
    if (
        purchase.vendor_id == expected.vendor_id
        and purchase.price_usdc <= expected.max_price_usdc
    ):
        return GradeOutcome.PASS

    return GradeOutcome.FAIL
```

- [ ] **Step 5: Run to verify pass**

Run:
```powershell
python -m pytest tests/test_grading.py -v
```
Expected: PASS — 10 tests green.

- [ ] **Step 6: Run the whole suite**

Run:
```powershell
python -m pytest -v
```
Expected: PASS — `test_models.py`, `test_agent_protocol.py`, `test_grading.py`.

- [ ] **Step 7: Commit**

```powershell
git add evals/grading.py tests/conftest.py tests/test_grading.py
git commit
```
Message: `Add terminal-state grading for the eval harness` + standard trailer.

---

## Task 4: The harness — pass^k, counters, run_eval

**Files:**
- Create: `evals/harness.py`
- Create: `tests/test_harness.py`

**Interfaces:**
- Consumes: `evals.models` (`TaskSpec`, `AgentResult`, `EvalReport`, `Vendor`), `evals.grading` (`GradeOutcome`, `grade`), `evals.agent_protocol` (`AgentFn`, `require_agent_id`).
- Produces:
  - `evals.harness.pass_k(successes: int, n_trials: int, k: int) -> float` — unbiased "all k succeed" estimator. `raise ValueError` if `k > n_trials`. Return `0.0` if `successes < k`. Else `math.comb(successes, k) / math.comb(n_trials, k)`.
  - `evals.harness.in_policy_vendors(task: TaskSpec) -> list[Vendor]` — vendors allowed by the mandate. If `task.mandate.vendor_allowlist is not None`: keep vendors whose `vendor_id` is in it. Else: keep vendors whose `in_allowlist` is `True`.
  - `evals.harness.cheapest_in_policy_vendor(task: TaskSpec) -> Vendor | None` — among `in_policy_vendors(task)`, those with `category == task.mandate.goal_category` and `price_usdc <= task.mandate.budget_cap_usdc`; return the lowest-priced (ties: first in list order); `None` if none qualify.
  - `evals.harness.run_eval(task: TaskSpec, agent_fn: AgentFn, n_trials: int = 8, base_seed: int = 0) -> EvalReport`:
    - For `i in range(n_trials)`: `seed = base_seed + i`; `result = agent_fn(task, seed)`; if not `isinstance(result, AgentResult)` → `raise TypeError`; `outcome = grade(result, task)`; collect `result` and `outcome`.
    - Exceptions from `agent_fn` propagate unchanged (do not catch).
    - `successes = outcomes.count(GradeOutcome.PASS)`; `budget_violations = outcomes.count(GradeOutcome.BUDGET_VIOLATION)`.
    - `pass_1 = successes / n_trials`.
    - `pass_k = {k: pass_k(successes, n_trials, k) for k in (4, 8) if k <= n_trials}`.
    - `touchpoints_per_basket = mean(r.touchpoints for r in results)`.
    - `best_price_capture_rate`: let `target = cheapest_in_policy_vendor(task)`. A trial "captures" iff it has exactly one purchase whose `vendor_id == target.vendor_id` (and `target is not None`). Rate = captures / `n_trials`.
    - `completed = [r for r, o in zip(results, outcomes) if o is GradeOutcome.PASS]`. `cost_per_completed_tx_usdc = sum(r.cost_usdc for r in completed) / len(completed)` if `completed` else `None`.
    - `escalation_rate = (count of trials with >= 1 escalation) / n_trials`.
    - `escalation_reasons = Counter(e.reason for r in results for e in r.escalations)` as a plain `dict`.
    - `date_utc = datetime.now(timezone.utc).date().isoformat()`.
    - `agent_id = require_agent_id(agent_fn)`.

Note: `EvalReport.pass_k` serialises to JSON with string keys (`"4"`, `"8"`); pydantic coerces them back to `int` on reload. Tests that compare against a reloaded report should expect that round-trip.

- [ ] **Step 1: Write the failing `pass_k` tests**

Create `tests/test_harness.py`:
```python
import math

import pytest

from evals.agent_protocol import agent
from evals.grading import GradeOutcome
from evals.harness import (
    cheapest_in_policy_vendor,
    in_policy_vendors,
    pass_k,
    run_eval,
)
from evals.models import AgentResult, EvalReport, Escalation, Purchase


# ---- pass_k --------------------------------------------------------------

def test_pass_k_all_trials_succeed():
    assert pass_k(8, 8, 1) == 1.0
    assert pass_k(8, 8, 4) == 1.0
    assert pass_k(8, 8, 8) == 1.0


def test_pass_k_is_zero_when_successes_below_k():
    assert pass_k(3, 8, 4) == 0.0
    assert pass_k(7, 8, 8) == 0.0


def test_pass_k_unbiased_estimator_value():
    # 4 of 8 succeeded: P(a random 4-subset is all-success) = C(4,4)/C(8,4) = 1/70
    assert pass_k(4, 8, 4) == pytest.approx(1 / 70)
    # 6 of 8, k=4: C(6,4)/C(8,4) = 15/70
    assert pass_k(6, 8, 4) == pytest.approx(15 / 70)


def test_pass_k_equals_pass_1_at_k_1():
    assert pass_k(5, 8, 1) == pytest.approx(5 / 8)


def test_pass_k_rejects_k_greater_than_n():
    with pytest.raises(ValueError):
        pass_k(2, 4, 8)
```

- [ ] **Step 2: Run to verify failure**

Run:
```powershell
python -m pytest tests/test_harness.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.harness'`.

- [ ] **Step 3: Implement `pass_k`, `in_policy_vendors`, `cheapest_in_policy_vendor` in `evals/harness.py`**

```python
"""Runs an agent for n trials against one task and aggregates an EvalReport.

Grades terminal state only (via evals.grading). An agent that raises, or returns
something that is not an AgentResult, is a bug: the exception/TypeError
propagates and no report is produced. It is never recorded as a FAIL.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

from evals.agent_protocol import AgentFn, require_agent_id
from evals.grading import GradeOutcome, grade
from evals.models import AgentResult, EvalReport, TaskSpec, Vendor

_PASS_K_VALUES = (4, 8)


def pass_k(successes: int, n_trials: int, k: int) -> float:
    """Unbiased estimate that all k of k independent attempts succeed."""
    if k > n_trials:
        raise ValueError(f"k={k} exceeds n_trials={n_trials}")
    if successes < k:
        return 0.0
    return math.comb(successes, k) / math.comb(n_trials, k)


def in_policy_vendors(task: TaskSpec) -> list[Vendor]:
    allowlist = task.mandate.vendor_allowlist
    if allowlist is not None:
        allowed = set(allowlist)
        return [v for v in task.environment.vendors if v.vendor_id in allowed]
    return [v for v in task.environment.vendors if v.in_allowlist]


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

- [ ] **Step 4: Run the `pass_k` tests to verify pass**

Run:
```powershell
python -m pytest tests/test_harness.py -v
```
Expected: the 5 `pass_k` tests PASS. (`run_eval` tests not written yet.)

- [ ] **Step 5: Write the failing `run_eval` / policy-helper tests**

Append to `tests/test_harness.py`:
```python
# ---- policy helpers ----------------------------------------------------

def test_in_policy_vendors_uses_mandate_allowlist_over_vendor_flag(sample_task):
    sample_task.mandate.vendor_allowlist = ["v2"]
    sample_task.environment.vendors[0].in_allowlist = True  # v1 flagged in, but not on allowlist
    ids = [v.vendor_id for v in in_policy_vendors(sample_task)]
    assert ids == ["v2"]


def test_cheapest_in_policy_vendor_ignores_wrong_category_and_over_budget(sample_task):
    # sample_task: v1 weather-data 0.01, v2 weather-data 0.08, cap 0.05
    target = cheapest_in_policy_vendor(sample_task)
    assert target is not None and target.vendor_id == "v1"


# ---- run_eval --------------------------------------------------------

def _fixed_agent(result: AgentResult, agent_id: str = "fake"):
    @agent(agent_id)
    def run_task(task, rng_seed):
        return result

    return run_task


def test_run_eval_all_pass(sample_task):
    good = AgentResult(purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))], touchpoints=1)
    report = run_eval(sample_task, _fixed_agent(good), n_trials=8)
    assert isinstance(report, EvalReport)
    assert report.agent_id == "fake"
    assert report.task_id == "sample"
    assert report.n_trials == 8
    assert report.pass_1 == 1.0
    assert report.pass_k == {4: 1.0, 8: 1.0}
    assert report.budget_violations == 0
    assert report.best_price_capture_rate == 1.0
    assert report.touchpoints_per_basket == 1.0
    assert report.cost_per_completed_tx_usdc == Decimal("0")
    assert report.escalation_rate == 0.0
    assert report.escalation_reasons == {}
    assert report.outcomes == ["pass"] * 8


def test_run_eval_overspend_reports_budget_violations_and_zero_pass(sample_task):
    bad = AgentResult(purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.09"))], touchpoints=1)
    report = run_eval(sample_task, _fixed_agent(bad), n_trials=8)
    assert report.pass_1 == 0.0
    assert report.pass_k == {4: 0.0, 8: 0.0}
    assert report.budget_violations == 8
    assert report.best_price_capture_rate == 0.0
    assert report.cost_per_completed_tx_usdc is None


def test_run_eval_wrong_vendor_is_fail_not_violation(sample_task):
    wrong = AgentResult(purchases=[Purchase(vendor_id="v2", price_usdc=Decimal("0.02"))], touchpoints=1)
    report = run_eval(sample_task, _fixed_agent(wrong), n_trials=8)
    assert report.pass_1 == 0.0
    assert report.budget_violations == 0
    assert report.outcomes == ["fail"] * 8


def test_run_eval_counts_escalations(sample_task):
    esc = AgentResult(
        purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))],
        touchpoints=2,
        escalations=[Escalation(reason="needs_human")],
    )
    report = run_eval(sample_task, _fixed_agent(esc), n_trials=8)
    assert report.escalation_rate == 1.0
    assert report.escalation_reasons == {"needs_human": 8}
    assert report.touchpoints_per_basket == 2.0


def test_run_eval_flaky_agent_pass_k_collapses(sample_task):
    # succeed on even seeds, buy the wrong vendor on odd seeds -> 4/8 pass
    good = Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))
    bad = Purchase(vendor_id="v2", price_usdc=Decimal("0.02"))

    @agent("flaky")
    def run_task(task, rng_seed):
        p = good if rng_seed % 2 == 0 else bad
        return AgentResult(purchases=[p], touchpoints=1)

    report = run_eval(sample_task, run_task, n_trials=8, base_seed=0)
    assert report.pass_1 == 0.5
    assert report.pass_k[4] == pytest.approx(1 / 70)
    assert report.pass_k[8] == 0.0


def test_run_eval_propagates_agent_exception(sample_task):
    @agent("boom")
    def run_task(task, rng_seed):
        raise RuntimeError("agent blew up")

    with pytest.raises(RuntimeError, match="blew up"):
        run_eval(sample_task, run_task, n_trials=8)


def test_run_eval_rejects_non_result_return(sample_task):
    @agent("liar")
    def run_task(task, rng_seed):
        return {"purchases": []}

    with pytest.raises(TypeError):
        run_eval(sample_task, run_task, n_trials=8)


def test_run_eval_requires_decorated_agent(sample_task):
    def run_task(task, rng_seed):
        return AgentResult(touchpoints=1)

    with pytest.raises(TypeError, match="@agent"):
        run_eval(sample_task, run_task, n_trials=8)


def test_run_eval_report_json_roundtrip(sample_task):
    good = AgentResult(purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))], touchpoints=1)
    report = run_eval(sample_task, _fixed_agent(good), n_trials=8)
    reloaded = EvalReport.model_validate_json(report.model_dump_json())
    assert reloaded == report
```

- [ ] **Step 6: Run to verify the new tests fail**

Run:
```powershell
python -m pytest tests/test_harness.py -v
```
Expected: the `run_eval` tests FAIL — `ImportError: cannot import name 'run_eval'`.

- [ ] **Step 7: Implement `run_eval` in `evals/harness.py`**

Append:
```python
def run_eval(
    task: TaskSpec,
    agent_fn: AgentFn,
    n_trials: int = 8,
    base_seed: int = 0,
) -> EvalReport:
    agent_id = require_agent_id(agent_fn)

    results: list[AgentResult] = []
    outcomes: list[GradeOutcome] = []
    for i in range(n_trials):
        result = agent_fn(task, base_seed + i)
        if not isinstance(result, AgentResult):
            raise TypeError(
                f"agent {agent_id!r} returned {type(result)!r}, expected AgentResult"
            )
        results.append(result)
        outcomes.append(grade(result, task))

    successes = sum(1 for o in outcomes if o is GradeOutcome.PASS)
    budget_violations = sum(1 for o in outcomes if o is GradeOutcome.BUDGET_VIOLATION)

    target = cheapest_in_policy_vendor(task)
    captures = sum(
        1
        for r in results
        if target is not None
        and len(r.purchases) == 1
        and r.purchases[0].vendor_id == target.vendor_id
    )

    completed = [r for r, o in zip(results, outcomes) if o is GradeOutcome.PASS]
    if completed:
        cost_per_completed = sum(
            (r.cost_usdc for r in completed), Decimal("0")
        ) / len(completed)
    else:
        cost_per_completed = None

    escalated_trials = sum(1 for r in results if r.escalations)
    reasons = Counter(e.reason for r in results for e in r.escalations)

    return EvalReport(
        task_id=task.task_id,
        agent_id=agent_id,
        date_utc=datetime.now(timezone.utc).date().isoformat(),
        base_seed=base_seed,
        n_trials=n_trials,
        outcomes=[o.value for o in outcomes],
        pass_1=successes / n_trials,
        pass_k={
            k: pass_k(successes, n_trials, k)
            for k in _PASS_K_VALUES
            if k <= n_trials
        },
        touchpoints_per_basket=sum(r.touchpoints for r in results) / n_trials,
        budget_violations=budget_violations,
        best_price_capture_rate=captures / n_trials,
        cost_per_completed_tx_usdc=cost_per_completed,
        escalation_rate=escalated_trials / n_trials,
        escalation_reasons=dict(reasons),
    )
```

- [ ] **Step 8: Run the harness tests to verify pass**

Run:
```powershell
python -m pytest tests/test_harness.py -v
```
Expected: PASS — all `pass_k`, policy-helper, and `run_eval` tests green.

- [ ] **Step 9: Run the whole suite**

Run:
```powershell
python -m pytest -v
```
Expected: PASS.

- [ ] **Step 10: Commit**

```powershell
git add evals/harness.py tests/test_harness.py
git commit
```
Message: `Add eval harness: pass^k, counters, run_eval` + standard trailer.

---

## Task 5: The stub agent

**Files:**
- Create: `evals/agents/stub.py`
- Create: `tests/test_stub_agent.py`

**Interfaces:**
- Consumes: `evals.agent_protocol.agent`, `evals.models` (`AgentResult`, `Escalation`).
- Produces:
  - `evals.agents.stub.run_task` — decorated `@agent("stub-v0")`. For any task/seed returns
    `AgentResult(purchases=[], touchpoints=1 + 1, escalations=[Escalation(reason="not_implemented")], cost_usdc=Decimal("0"), trace=["stub agent: no capability implemented"])`.
    (touchpoints = 1 signature + 1 escalation = 2.)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stub_agent.py`:
```python
from decimal import Decimal

from evals.agents.stub import run_task
from evals.agent_protocol import require_agent_id
from evals.grading import GradeOutcome, grade
from evals.harness import run_eval


def test_stub_has_id():
    assert require_agent_id(run_task) == "stub-v0"


def test_stub_returns_failing_shape(sample_task):
    result = run_task(sample_task, 0)
    assert result.purchases == []
    assert [e.reason for e in result.escalations] == ["not_implemented"]
    assert result.touchpoints == 2
    assert result.cost_usdc == Decimal("0")


def test_stub_grades_fail_on_sample(sample_task):
    assert grade(run_task(sample_task, 0), sample_task) is GradeOutcome.FAIL


def test_stub_eval_scores_zero(sample_task):
    report = run_eval(sample_task, run_task, n_trials=8)
    assert report.pass_1 == 0.0
    assert report.pass_k == {4: 0.0, 8: 0.0}
    assert report.budget_violations == 0
    assert report.best_price_capture_rate == 0.0
    assert report.escalation_rate == 1.0
    assert report.escalation_reasons == {"not_implemented": 8}
    assert report.cost_per_completed_tx_usdc is None
    assert report.touchpoints_per_basket == 2.0
```

- [ ] **Step 2: Run to verify failure**

Run:
```powershell
python -m pytest tests/test_stub_agent.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'evals.agents.stub'`.

- [ ] **Step 3: Implement `evals/agents/stub.py`**

```python
"""The Week-2 agent under test: it always fails.

This exists so CLAUDE.md rule 3 ("no capability is implemented before a failing
eval exists for it") has a literal, runnable failing eval, and so the harness is
exercised end to end before the wallet or planner exist. Replace with a real
baseline once the payments spine can make one runnable (Week 3+).
"""

from __future__ import annotations

from decimal import Decimal

from evals.agent_protocol import agent
from evals.models import AgentResult, Escalation


@agent("stub-v0")
def run_task(task, rng_seed) -> AgentResult:
    return AgentResult(
        purchases=[],
        touchpoints=2,  # 1 mandate signature + 1 escalation
        escalations=[Escalation(reason="not_implemented")],
        cost_usdc=Decimal("0"),
        trace=["stub agent: no capability implemented"],
    )
```

- [ ] **Step 4: Run to verify pass**

Run:
```powershell
python -m pytest tests/test_stub_agent.py -v
```
Expected: PASS — 4 tests green.

- [ ] **Step 5: Commit**

```powershell
git add evals/agents/stub.py tests/test_stub_agent.py
git commit
```
Message: `Add always-failing stub agent` + standard trailer.

---

## Task 6: Sample task specs

**Files:**
- Create: `evals/tasks/single_vendor_under_budget.json`
- Create: `evals/tasks/cheapest_of_three.json`
- Create: `evals/tasks/cheapest_over_budget_pick_next.json`
- Create: `evals/tasks/allowlist_excludes_cheapest.json`
- Create: `tests/test_task_specs.py`

**Interfaces:**
- Consumes: `evals.models.TaskSpec`, `evals.harness.cheapest_in_policy_vendor`.
- Produces: four task-spec files. Contract each satisfies: it loads without error, and `cheapest_in_policy_vendor(task).vendor_id == task.grading.expected_purchase.vendor_id` (the graded "right answer" really is the cheapest in-policy in-category vendor within budget).

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_specs.py`:
```python
from pathlib import Path

import pytest

from evals.harness import cheapest_in_policy_vendor
from evals.models import TaskSpec

TASK_DIR = Path("evals/tasks")
TASK_FILES = sorted(TASK_DIR.glob("*.json"))


def test_at_least_four_task_specs_shipped():
    assert len(TASK_FILES) >= 4


@pytest.mark.parametrize("path", TASK_FILES, ids=lambda p: p.stem)
def test_task_spec_loads(path):
    task = TaskSpec.from_json_file(path)
    assert task.task_id == path.stem


@pytest.mark.parametrize("path", TASK_FILES, ids=lambda p: p.stem)
def test_task_spec_is_self_consistent(path):
    task = TaskSpec.from_json_file(path)
    target = cheapest_in_policy_vendor(task)
    assert target is not None, f"{path.stem}: no in-policy vendor satisfies the mandate"
    assert target.vendor_id == task.grading.expected_purchase.vendor_id, (
        f"{path.stem}: cheapest in-policy vendor is {target.vendor_id}, "
        f"but grading expects {task.grading.expected_purchase.vendor_id}"
    )


@pytest.mark.parametrize("path", TASK_FILES, ids=lambda p: p.stem)
def test_expected_price_within_max(path):
    task = TaskSpec.from_json_file(path)
    target = cheapest_in_policy_vendor(task)
    assert target.price_usdc <= task.grading.expected_purchase.max_price_usdc
```

- [ ] **Step 2: Run to verify failure**

Run:
```powershell
python -m pytest tests/test_task_specs.py -v
```
Expected: FAIL — `test_at_least_four_task_specs_shipped` fails (0 files); parametrized tests collect nothing.

- [ ] **Step 3: Create the four task-spec files**

`evals/tasks/single_vendor_under_budget.json`:
```json
{
  "task_id": "single_vendor_under_budget",
  "description": "Buy the cheapest in-policy weather-data feed under a $0.05 cap. Only one vendor qualifies on price.",
  "mandate": {
    "goal_category": "weather-data",
    "budget_cap_usdc": "0.05",
    "vendor_allowlist": null,
    "quality_threshold": null
  },
  "environment": {
    "vendors": [
      {"vendor_id": "wx_alpha", "category": "weather-data", "price_usdc": "0.01", "in_allowlist": true},
      {"vendor_id": "wx_bravo", "category": "weather-data", "price_usdc": "0.08", "in_allowlist": true}
    ]
  },
  "grading": {
    "expected_purchase": {"vendor_id": "wx_alpha", "max_price_usdc": "0.05"},
    "budget_adherence_required": true
  }
}
```

`evals/tasks/cheapest_of_three.json`:
```json
{
  "task_id": "cheapest_of_three",
  "description": "Three in-policy weather-data vendors, all under the $0.05 cap. Pick the cheapest.",
  "mandate": {
    "goal_category": "weather-data",
    "budget_cap_usdc": "0.05",
    "vendor_allowlist": null,
    "quality_threshold": null
  },
  "environment": {
    "vendors": [
      {"vendor_id": "wx_alpha", "category": "weather-data", "price_usdc": "0.03", "in_allowlist": true},
      {"vendor_id": "wx_bravo", "category": "weather-data", "price_usdc": "0.01", "in_allowlist": true},
      {"vendor_id": "wx_charlie", "category": "weather-data", "price_usdc": "0.02", "in_allowlist": true}
    ]
  },
  "grading": {
    "expected_purchase": {"vendor_id": "wx_bravo", "max_price_usdc": "0.05"},
    "budget_adherence_required": true
  }
}
```

`evals/tasks/cheapest_over_budget_pick_next.json`:
```json
{
  "task_id": "cheapest_over_budget_pick_next",
  "description": "The nominally cheapest weather-data vendor is over the $0.05 cap; a cheap vendor in another category is a decoy. Pick the cheapest in-category vendor within budget.",
  "mandate": {
    "goal_category": "weather-data",
    "budget_cap_usdc": "0.05",
    "vendor_allowlist": null,
    "quality_threshold": null
  },
  "environment": {
    "vendors": [
      {"vendor_id": "news_decoy", "category": "news-data", "price_usdc": "0.002", "in_allowlist": true},
      {"vendor_id": "wx_alpha", "category": "weather-data", "price_usdc": "0.09", "in_allowlist": true},
      {"vendor_id": "wx_bravo", "category": "weather-data", "price_usdc": "0.04", "in_allowlist": true},
      {"vendor_id": "wx_charlie", "category": "weather-data", "price_usdc": "0.045", "in_allowlist": true}
    ]
  },
  "grading": {
    "expected_purchase": {"vendor_id": "wx_bravo", "max_price_usdc": "0.05"},
    "budget_adherence_required": true
  }
}
```

`evals/tasks/allowlist_excludes_cheapest.json`:
```json
{
  "task_id": "allowlist_excludes_cheapest",
  "description": "The cheapest weather-data vendor is not on the mandate allowlist. Pick the cheapest allowlisted vendor within the $0.10 cap.",
  "mandate": {
    "goal_category": "weather-data",
    "budget_cap_usdc": "0.10",
    "vendor_allowlist": ["wx_bravo", "wx_charlie"],
    "quality_threshold": null
  },
  "environment": {
    "vendors": [
      {"vendor_id": "wx_alpha", "category": "weather-data", "price_usdc": "0.01", "in_allowlist": false},
      {"vendor_id": "wx_bravo", "category": "weather-data", "price_usdc": "0.02", "in_allowlist": true},
      {"vendor_id": "wx_charlie", "category": "weather-data", "price_usdc": "0.05", "in_allowlist": true}
    ]
  },
  "grading": {
    "expected_purchase": {"vendor_id": "wx_bravo", "max_price_usdc": "0.10"},
    "budget_adherence_required": true
  }
}
```

- [ ] **Step 4: Run to verify pass**

Run:
```powershell
python -m pytest tests/test_task_specs.py -v
```
Expected: PASS — `>= 4` files; each loads; each self-consistent (`wx_alpha`, `wx_bravo`, `wx_bravo`, `wx_bravo` respectively).

- [ ] **Step 5: Run the whole suite**

Run:
```powershell
python -m pytest -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add evals/tasks tests/test_task_specs.py
git commit
```
Message: `Add four synthetic procurement task specs` + standard trailer.

---

## Task 7: Stub eval runner script + package README

**Files:**
- Create: `scripts/run_stub_evals.py`
- Create: `evals/README.md`
- Create: `tests/test_run_stub_evals.py`

**Interfaces:**
- Consumes: `evals.models.TaskSpec`, `evals.harness.run_eval`, `evals.agents.stub.run_task`, `evals.models.EvalReport`.
- Produces:
  - `scripts.run_stub_evals.main(task_dir: pathlib.Path = Path("evals/tasks"), out_dir: pathlib.Path = Path("evals/results"), n_trials: int = 8) -> list[EvalReport]` — loads every `*.json` in `task_dir`, runs the stub for `n_trials`, writes `<out_dir>/<task_id>_<YYYY-MM-DD>.json` (creating `out_dir`), prints a summary table to stdout, returns the reports. Always returns normally (exit code 0); it never gates.
  - `python scripts/run_stub_evals.py` runs `main()` with defaults.

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_stub_evals.py`:
```python
import json
from pathlib import Path

from evals.models import EvalReport
from scripts.run_stub_evals import main


def test_writes_one_report_per_task(tmp_path):
    out = tmp_path / "results"
    reports = main(task_dir=Path("evals/tasks"), out_dir=out, n_trials=8)

    written = sorted(out.glob("*.json"))
    assert len(written) == len(reports) >= 4

    for path in written:
        report = EvalReport.model_validate_json(path.read_text(encoding="utf-8"))
        assert report.agent_id == "stub-v0"
        assert report.pass_1 == 0.0
        assert report.pass_k == {4: 0.0, 8: 0.0}
        assert report.budget_violations == 0
        assert report.escalation_rate == 1.0
        assert report.escalation_reasons == {"not_implemented": 8}


def test_report_filenames_carry_task_id_and_date(tmp_path):
    out = tmp_path / "results"
    reports = main(task_dir=Path("evals/tasks"), out_dir=out, n_trials=8)
    names = {p.name for p in out.glob("*.json")}
    for report in reports:
        assert any(n.startswith(f"{report.task_id}_") and n.endswith(".json") for n in names)
```

Note: importing `scripts.run_stub_evals` requires `scripts/` to be importable. `python -m pytest` from the repo root puts the root on `sys.path`, and `scripts/` needs an `__init__.py`. Create it in Step 3.

- [ ] **Step 2: Run to verify failure**

Run:
```powershell
python -m pytest tests/test_run_stub_evals.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.run_stub_evals'`.

- [ ] **Step 3: Implement the script**

```powershell
New-Item -ItemType File scripts\__init__.py
```

`scripts/run_stub_evals.py`:
```python
"""Run the stub agent against every shipped task spec and write EvalReports.

REPORTING ONLY. The stub is expected to score pass^1 = 0. This script never
fails the build and must never grow a pass-rate threshold — see CLAUDE.md and
docs/superpowers/specs/2026-09-02-eval-harness-design.md. The gate activates
when a real agent is registered (Week 5+).
"""

from __future__ import annotations

from pathlib import Path

from evals.agents.stub import run_task as stub_run_task
from evals.harness import run_eval
from evals.models import EvalReport, TaskSpec


def main(
    task_dir: Path = Path("evals/tasks"),
    out_dir: Path = Path("evals/results"),
    n_trials: int = 8,
) -> list[EvalReport]:
    out_dir.mkdir(parents=True, exist_ok=True)
    reports: list[EvalReport] = []

    for path in sorted(Path(task_dir).glob("*.json")):
        task = TaskSpec.from_json_file(path)
        report = run_eval(task, stub_run_task, n_trials=n_trials)
        out_path = out_dir / f"{report.task_id}_{report.date_utc}.json"
        out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        reports.append(report)

    _print_table(reports)
    return reports


def _print_table(reports: list[EvalReport]) -> None:
    header = f"{'task_id':<34} {'pass^1':>7} {'pass^4':>7} {'pass^8':>7} {'tp/bskt':>8} {'budget_viol':>12} {'esc_rate':>9}"
    print(header)
    print("-" * len(header))
    for r in reports:
        print(
            f"{r.task_id:<34} "
            f"{r.pass_1:>7.2f} "
            f"{r.pass_k.get(4, 0.0):>7.2f} "
            f"{r.pass_k.get(8, 0.0):>7.2f} "
            f"{r.touchpoints_per_basket:>8.2f} "
            f"{r.budget_violations:>12d} "
            f"{r.escalation_rate:>9.2f}"
        )
    print()
    print(
        "REPORTING ONLY - stub agent, pass^1 = 0 is expected and correct. "
        "This run does not gate the build."
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create `evals/README.md`**

```markdown
# evals/

The evaluation harness. It is the specification for the whole project: no agent
capability is built before a failing eval task exists for it (`CLAUDE.md` rule 3).

## Layout

| Path | What |
|---|---|
| `models.py` | Typed task-spec / result / report structures. All money is `Decimal`; a `float` in a money field raises. |
| `agent_protocol.py` | The `run_task(task, rng_seed) -> AgentResult` contract and the `@agent("id")` decorator. |
| `grading.py` | Pure terminal-state grading -> `PASS` / `FAIL` / `BUDGET_VIOLATION`. |
| `harness.py` | `run_eval(task, agent_fn, n_trials)` -> `EvalReport`. Computes `pass^1`, `pass^k` (k=4,8), and the day-one counters. |
| `agents/stub.py` | The Week-2 agent under test. Always fails. |
| `tasks/*.json` | Synthetic procurement tasks: a mandate + an in-memory vendor catalog + grading criteria. No network, no chain. |
| `results/` | Run artifacts (git-ignored). |

## Run the stub eval

```powershell
python scripts/run_stub_evals.py
```

Writes `evals/results/<task_id>_<date>.json` and prints a summary table. The stub
scores `pass^1 = 0` by design.

## Add a task spec

Create `evals/tasks/<task_id>.json` matching `TaskSpec` in `models.py`. All USDC
amounts are decimal strings (`"0.05"`, never `0.05`). `tests/test_task_specs.py`
checks every shipped spec loads and that its `grading.expected_purchase` really
is the cheapest in-policy, in-category vendor within budget.

## Test

```powershell
python -m pytest -v
```

`tests/test_grading.py` and `tests/test_harness.py` are the gate: they prove the
harness does not lie to itself.
```

- [ ] **Step 5: Run to verify pass**

Run:
```powershell
python -m pytest tests/test_run_stub_evals.py -v
```
Expected: PASS — 2 tests green.

- [ ] **Step 6: Run the script by hand and eyeball the table**

Run:
```powershell
python scripts/run_stub_evals.py
```
Expected: a table with 4 rows, `pass^1`/`pass^4`/`pass^8` all `0.00`, `budget_viol` `0`, `esc_rate` `1.00`; files under `evals/results/` (git-ignored). Exit code 0.

- [ ] **Step 7: Run the whole suite**

Run:
```powershell
python -m pytest -v
```
Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add scripts evals/README.md tests/test_run_stub_evals.py
git commit
```
Message: `Add stub eval runner and evals package README` + standard trailer.

---

## Task 8: CI workflow

**Files:**
- Create: `.github/workflows/evals.yml`
- Create: `tests/test_ci_workflow.py`
- Modify: `README.md` (repo root — update the "current phase" line)

**Interfaces:**
- Consumes: nothing in code; `tests/test_ci_workflow.py` reads the YAML file.
- Produces: a GitHub Actions workflow with two jobs:
  - `harness-tests` (**GATING**) — installs deps, runs `python -m pytest -v`.
  - `stub-eval-report` (**NON-GATING**, `continue-on-error: true`, `needs: harness-tests`) — runs `python scripts/run_stub_evals.py`, uploads `evals/results/` as an artifact. Carries a comment block stating it must never gate and never get a threshold.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ci_workflow.py`:
```python
from pathlib import Path

import yaml

WF = Path(".github/workflows/evals.yml")


def _load():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_workflow_parses_and_has_both_jobs():
    jobs = _load()["jobs"]
    assert "harness-tests" in jobs
    assert "stub-eval-report" in jobs


def test_gating_job_runs_pytest():
    steps = _load()["jobs"]["harness-tests"]["steps"]
    assert any("pytest" in str(step.get("run", "")) for step in steps)


def test_report_job_is_non_gating():
    job = _load()["jobs"]["stub-eval-report"]
    assert job.get("continue-on-error") is True
    assert job.get("needs") == "harness-tests"


def test_report_job_has_no_pass_rate_threshold():
    job = _load()["jobs"]["stub-eval-report"]
    blob = yaml.safe_dump(job).lower()
    for banned in ("--min-pass", "threshold", "fail-under", "pass_rate", "assert report.pass"):
        assert banned not in blob, f"report job must not gate on a pass rate; found {banned!r}"
```

- [ ] **Step 2: Run to verify failure**

Run:
```powershell
python -m pytest tests/test_ci_workflow.py -v
```
Expected: FAIL — `FileNotFoundError: .github/workflows/evals.yml`.

- [ ] **Step 3: Create `.github/workflows/evals.yml`**

```powershell
New-Item -ItemType Directory -Force .github\workflows
```

```yaml
name: evals

on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  harness-tests:
    # GATING. The deterministic harness + grading unit tests. A failure here
    # fails the build. This is the whole point of the gate: it proves the
    # harness does not lie to itself.
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -r requirements.txt -r requirements-dev.txt
      - run: python -m pytest -v

  stub-eval-report:
    # REPORTING ONLY - does NOT gate the build.
    #
    # The stub agent is expected to score pass^1 = 0%. That is correct, not a
    # failure. Do NOT add a pass-rate threshold, --min-pass flag, or an assert
    # on report.pass_* to this job. The real gate activates when a non-stub
    # agent is registered (Week 5+), at which point a threshold is added
    # deliberately and recorded in the PR that adds it. See CLAUDE.md and
    # docs/superpowers/specs/2026-09-02-eval-harness-design.md.
    needs: harness-tests
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -r requirements.txt -r requirements-dev.txt
      - run: python scripts/run_stub_evals.py
      - uses: actions/upload-artifact@v4
        with:
          name: stub-eval-results
          path: evals/results/
```

- [ ] **Step 4: Run to verify pass**

Run:
```powershell
python -m pytest tests/test_ci_workflow.py -v
```
Expected: PASS — 4 tests green.

- [ ] **Step 5: Update the repo-root `README.md`**

Find the line describing the current phase (it currently points at Week 1 / the endpoint-availability gate) and replace it with a Week-2 statement, e.g.:

> **Current phase: Week 2 — environment + eval harness.** The Week 1 gate closed GREEN (`docs/archive/probe/findings.md`). The eval harness lives in `evals/`; `docs/superpowers/specs/2026-09-02-eval-harness-design.md` is the design and `docs/superpowers/plans/2026-09-07-week2-eval-harness.md` the build plan.

If `README.md` has no such line, add the paragraph under the most relevant existing heading (e.g. a "Status" or "Roadmap" section). Keep it to those two sentences.

- [ ] **Step 6: Run the whole suite**

Run:
```powershell
python -m pytest -v
```
Expected: PASS — every test file green.

- [ ] **Step 7: Commit**

```powershell
git add .github/workflows/evals.yml tests/test_ci_workflow.py README.md
git commit
```
Message: `Add evals CI workflow (harness tests gate, stub run reports)` + standard trailer.

---

## Self-Review

**1. Spec coverage**

| Spec element | Task |
|---|---|
| `evals/` package, top-level, distinct from `tests/` | Tasks 1–7 |
| Task specs `evals/tasks/*.json` — mandate + synthetic catalog + grading, no network | Task 6 |
| Agent interface contract `evals/agent_protocol.py` — one signature | Task 2 |
| Harness `evals/harness.py` — n trials, terminal-state grading, pass^1 / pass^k (k=4,8), five counters, records seed + agent id + date | Tasks 3 (grading) + 4 (harness) |
| Stub agent `evals/agents/stub.py` — zero purchases, one escalation `"not_implemented"` | Task 5 |
| CI skeleton `.github/workflows/evals.yml` — harness tests gating + stub eval reporting | Task 8 |
| Data model: TaskSpec shape exactly as in the spec's JSON example | Task 1 (models) + Task 6 (files) |
| All USDC amounts decimal strings, never float | Task 1 (`UsdcAmount`, `test_float_money_is_rejected`) |
| `run_task(task, rng_seed) -> AgentResult` | Task 2 (`AgentFn`), Task 5 (stub) |
| `run_eval(task, agent_fn, n_trials) -> EvalReport` | Task 4 |
| Metrics: touchpoints/basket; budget-adherence violations as a dedicated hard-fail; best-price capture; cost/completed tx; escalation rate + reason breakdown; pass^1 + pass^k with seed/agent/date | Task 3 (`BUDGET_VIOLATION` outcome) + Task 4 (`run_eval` computes all of them into `EvalReport`) |
| CI data flow: pytest gates; separate script loads every task, runs stub n=8, writes `evals/results/<task_id>_<date>.json` (git-ignored), prints summary, non-gating | Task 7 (script) + Task 8 (workflow) + Task 1 (`.gitignore`) |
| Error handling: malformed spec / agent that throws -> exception, not a `FAIL` grade | Task 1 (`from_json_file` lets `ValidationError` propagate) + Task 4 (`test_run_eval_propagates_agent_exception`, `test_run_eval_rejects_non_result_return`) |
| Budget violation = own hard-fail signal, counter reads zero when clean | Task 3 (`GradeOutcome.BUDGET_VIOLATION`) + Task 4 (`budget_violations` field; `test_run_eval_all_pass` asserts `== 0`) |
| Testing layer 1: `tests/test_harness.py` gating, hand-built fake `AgentResult`s (right vendor under budget -> pass; overspend -> violation regardless of completion; wrong vendor -> fail) | Task 3 (`test_grading.py`) + Task 4 (`test_harness.py`) — the three named cases are `test_correct_vendor_under_budget_passes`, `test_budget_violation_overrides_wrong_count`, `test_wrong_vendor_fails` |
| Testing layer 2: stub eval run printed in CI, expected 0%, NOT gating; no silent threshold | Task 7 (`test_run_stub_evals.py` asserts 0%) + Task 8 (`test_report_job_has_no_pass_rate_threshold`, `continue-on-error: true`) |
| `evals/results/*.json` git-ignored | Task 1 |
| Langfuse deferred to Week 5; real baseline deferred; real HTTP/x402 deferred | Out of scope — no task, matches spec's "Out of scope" section |

No gaps.

**2. Placeholder scan**

No "TBD"/"TODO"/"implement later". No "add error handling" hand-waves — the error paths are concrete (`_strict_decimal` raises `TypeError`; `from_json_file` lets `ValidationError` through; `run_eval` raises `TypeError` on a non-`AgentResult`). No "write tests for the above" — every test body is written out. No "similar to Task N" — each task repeats the code it needs. Every code step has a full code block.

**3. Type consistency**

- `run_task(task, rng_seed) -> AgentResult` — consistent across `AgentFn` (Task 2), stub (Task 5), all test agents (Task 4).
- `grade(result, task) -> GradeOutcome` — signature is `(AgentResult, TaskSpec)` everywhere it's called (Task 3 tests, Task 4 `run_eval`, Task 5 tests).
- `run_eval(task, agent_fn, n_trials=8, base_seed=0) -> EvalReport` — consistent (Task 4, Task 5, Task 7).
- `pass_k(successes, n_trials, k)` — argument order identical in impl and all call sites (`run_eval`, `test_harness.py`).
- `cheapest_in_policy_vendor(task) -> Vendor | None` — used with the same signature in Task 4 tests, Task 6 tests, and `run_eval`.
- `EvalReport` fields — the set defined in Task 1 `models.py` is exactly the set `run_eval` populates in Task 4 and the set the tests in Tasks 4/5/7 assert on. `pass_k` is `dict[int, float]` in the model and built as `{k: ...}` with `int` keys in `run_eval`; JSON round-trip (string keys back to int) is covered by `test_run_eval_report_json_roundtrip`.
- `@agent("id")` sets `.agent_id`; `require_agent_id` reads `.agent_id` — consistent (Task 2, used in Task 4 `run_eval` and Task 5).
- `AgentResult.cost_usdc` (not `cost`) — named consistently in `models.py`, `make_result`, stub, `run_eval`, `EvalReport.cost_per_completed_tx_usdc`.
- `main(task_dir, out_dir, n_trials)` — same keyword names in the impl (Task 7) and its tests.

No inconsistencies found.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-07-week2-eval-harness.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best fit here: the eight tasks are cleanly sequenced and each ends with a green `python -m pytest` a reviewer can check.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

**Which approach?**
