# Week 2 Eval Harness — Design

**Date:** 2026-09-02
**Status:** approved, pending implementation plan

## Why this exists

`CLAUDE.md` rule 3: no agent capability is implemented before a failing eval task
exists for it. `PMF_AND_BUILD_PLAN.md` names Week 2 as "Env + eval harness." Neither
the payments spine (Week 3) nor the planner/executor (Week 5) exist yet, so this
harness has to be buildable and meaningfully testable **today**, decoupled from both.

## Scope decisions made during brainstorming

1. **Agent under test for Week 2 is a stub, not a real baseline.** The stub always
   fails (returns zero purchases, one escalation reason `"not_implemented"`). This
   gives rule 3 its literal "failing eval exists" and proves the harness end-to-end
   without waiting on the wallet or the planner. The real baseline (Deliverable E's
   "ReAct/GPT-4o-style single-agent tool-caller" to beat) is deferred to whenever the
   payments spine exists to make it runnable — likely Week 3+, not Week 2.
2. **Task environment is an in-memory synthetic catalog, not real HTTP.** Task specs
   embed a vendor catalog as plain JSON — no network calls, no self-hosted Flask
   sellers, no x402 handshake. This decouples the harness from chain entirely; wiring
   real vendors (self-hosted or Bazaar) happens later without touching the harness or
   task-spec format.
3. **Langfuse tracing is deferred to Week 5**, deviating from `PMF_AND_BUILD_PLAN.md`'s
   literal Week-2 listing. Rationale: a stub agent that does nothing produces no
   meaningful trace; standing up self-hosted Langfuse now is infra cost with no
   payoff until there's a planner/executor loop worth tracing. Recorded here per
   `CLAUDE.md`'s instruction that changing a documented plan gets said explicitly,
   not done silently.

## Architecture

A new top-level `evals/` package, distinct from a future `tests/` (pytest unit
tests, on-chain constant-pinning tests — owned by the `tests` subagent). `evals/`
owns:

- **Task specs** (`evals/tasks/*.json`) — a procurement mandate + synthetic vendor
  catalog + grading criteria. No network, no chain.
- **Agent interface contract** (`evals/agent_protocol.py`) — the one function
  signature every agent (stub today, baseline later, real planner eventually) must
  implement. The harness depends only on this contract, never on a concrete agent.
- **Harness** (`evals/harness.py`) — loads a task, runs an agent for *n* trials,
  grades terminal state (never process — never "was a function called"), aggregates
  pass^1 / pass^k (k=4, k=8), computes the five day-one counters, records seed +
  agent identifier + date.
- **Stub agent** (`evals/agents/stub.py`) — implements the interface, fails every
  task on purpose.
- **CI skeleton** (`.github/workflows/evals.yml`) — runs harness unit tests
  (gating) plus a stub-agent eval run (reporting only, not gating — see Testing).

## Data model

Task spec, e.g. `evals/tasks/single_vendor_under_budget.json`:

```json
{
  "task_id": "single_vendor_under_budget",
  "description": "Buy the cheapest in-policy weather data feed under a $0.05 cap",
  "mandate": {
    "goal_category": "weather-data",
    "budget_cap_usdc": "0.05",
    "vendor_allowlist": null,
    "quality_threshold": null
  },
  "environment": {
    "vendors": [
      {"vendor_id": "v1", "category": "weather-data", "price_usdc": "0.01", "in_allowlist": true},
      {"vendor_id": "v2", "category": "weather-data", "price_usdc": "0.08", "in_allowlist": true}
    ]
  },
  "grading": {
    "expected_purchase": {"vendor_id": "v1", "max_price_usdc": "0.05"},
    "budget_adherence_required": true
  }
}
```

All USDC amounts are **decimal strings**, never floats — matches the atomic-unit
gotcha recorded in `probe/findings.md` §3/§6 (USDC has 6 decimals; a float invites
silent precision bugs).

Agent interface:

```python
def run_task(task: TaskSpec, rng_seed: int) -> AgentResult:
    """AgentResult carries: purchases made (vendor_id, price paid), touchpoint
    count, escalations (with reason), cost, and a decision trace."""
```

Harness entry point:

```python
def run_eval(task: TaskSpec, agent_fn: AgentFn, n_trials: int) -> EvalReport:
    """Runs n_trials, grades each AgentResult against task.grading, aggregates
    pass^1 and pass^k (k in {4, 8}), computes counters, records seed/agent/date."""
```

## Data flow (CI)

CI (`.github/workflows/evals.yml`) → `pytest` runs `tests/test_harness.py` (gating)
→ separately, a script loads every `evals/tasks/*.json` and calls
`harness.run_eval(task, stub_agent.run_task, n_trials=8)` for each → each
`EvalReport` is written to `evals/results/<task_id>_<date>.json` (git-ignored,
report artifact not source) → a summary table (pass^1/pass^8, counters) is printed
to stdout, non-gating.

## Metrics computed per `EvalReport` (from `evals` agent's charter, `.claude/agents/evals.md`)

- human touchpoints per basket
- budget adherence violations (must be zero — a dedicated hard-fail path, not folded
  into the generic pass/fail bit)
- best-price capture rate
- cost per completed transaction
- escalation rate and reason breakdown
- pass^1 and pass^k (k=4, k=8), with seed, agent identifier, and date recorded

## Error handling

A malformed task spec or an agent that throws is a **harness or agent bug**, not a
graded failure. It propagates as an exception, not a silent "fail" grade — per
`CLAUDE.md` rule 4, conflating a crash with an honest policy failure corrupts the
pass-rate numbers the whole harness exists to protect.

Budget-adherence violations get their own hard-fail signal separate from
task-completion pass/fail, since `CLAUDE.md` requires that counter to read zero,
always, and a violation must be loud.

## Testing (two layers, not conflated)

1. **`tests/test_harness.py`** (pytest, unit, gates CI) — exercises the grading
   logic with hand-built fake `AgentResult`s: an agent that buys the right vendor
   under budget grades pass; one that overspends grades a budget violation
   regardless of task completion; one that buys the wrong vendor grades fail. This
   is what proves the harness isn't lying to itself, and it's the one thing in this
   design that should actually fail the build if broken.
2. **Stub-agent eval run** — CI prints the pass^1/pass^8 table (expected: 0% —
   correct, not broken) but does **not** gate the build on it. Gating on a number
   that is supposed to be zero is vacuous. The gate activates once a real agent is
   registered (Week 5+). This is stated explicitly in the CI workflow's comments and
   in the PR description, per `evals.md`'s warning against silently lowering a bar —
   this isn't lowering a bar, the bar doesn't exist yet.

Eval run outputs (`evals/results/*.json`) are report artifacts, not source — git-ignored.

## Out of scope for this design (explicitly deferred, not forgotten)

- Real HTTP / x402 vendor environments (self-hosted or Bazaar) — deferred until the
  payments spine (Week 3) exists to make settlement gradeable.
- The real baseline agent (ReAct/tool-caller) — deferred alongside the above.
- Langfuse tracing — deferred to Week 5 (see Scope decisions, #3).
- The trained vendor-selection/price-anomaly classifier (Deliverable E, Week 7) —
  unrelated to this harness's scope.
