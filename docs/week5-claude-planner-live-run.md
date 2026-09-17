# claude-planner-v1 Live Run

The first real, billed Claude API pass through `claude-planner-v1`
(`evals/agents/claude_planner.py`), per the design spec's own "After this
plan lands" note (`docs/superpowers/specs/2026-09-15-week5-planner-v1-design.md`).
Every offline test in the branch that merged this agent (PR-equivalent:
commits `9eac1b4..2e04bc3`) fakes or monkeypatches the LLM call — this is
the first execution of the primary code path against a live model.

## What ran

```
python scripts/run_claude_planner_evals.py
```

Model: `claude-haiku-4-5` (the `PLANNER_MODEL` default). All 5 shipped
synthetic task specs, `n_trials=8` each (the script's default). The one
`real_x402` spec (`real_weather_sepolia.json`) is out of scope for this
script by design — it needs a funded wallet and a live seller, a separate
concern already covered by `tests/test_harness_real_x402.py`.

## Result

```
task_id                                 pass^1 (95% CI)  pass^4  pass^8  tp/bskt  budget_viol  esc_rate   cost/tx
-----------------------------------------------------------------------------------------------------------------
allowlist_excludes_cheapest           1.00 [0.68, 1.00]    1.00    1.00     1.00            0      0.00  0.001246
cheapest_of_three                     1.00 [0.68, 1.00]    1.00    1.00     1.00            0      0.00  0.001256
cheapest_over_budget_pick_next        1.00 [0.68, 1.00]    1.00    1.00     1.00            0      0.00  0.001255
no_in_policy_vendor_escalates         1.00 [0.68, 1.00]    1.00    1.00     2.00            0      1.00  0.000000
single_vendor_under_budget            1.00 [0.68, 1.00]    1.00    1.00     1.00            0      0.00  0.001218

Model: claude-haiku-4-5
```

pass^1 = pass^4 = pass^8 = 1.0 on all five specs, zero budget violations.
`no_in_policy_vendor_escalates` shows `touchpoints_per_basket=2.00` and
`escalation_rate=1.00` with `cost/tx=0` — every trial hit the deterministic
pre-filter (`in_policy_candidates` returns `[]`) and escalated without ever
calling the LLM, exactly as designed. The other four specs show
`cost/tx≈$0.0012`, consistent with `_token_cost_usdc`'s Haiku pricing
($1.00/$5.00 per 1M input/output tokens) against a small
mandate-plus-candidate-list prompt. Total spend across the whole run was a
few cents.

This matches the design spec's own "Known limitations" prediction exactly:
every task's pre-filtered candidate set has a unique cheapest option, so the
LLM step is confirmatory here, not yet differentiating — the interface is
being built ahead of the harder task specs (a stated preference not
reducible to price, a real quality signal) that will actually need it.

## What this does not close

- **No task in the current suite exercises genuine LLM judgment.** A
  deterministic `min(candidates, key=price)` would already pass all five —
  this run proves the plumbing (prompt → structured decision → payment →
  grading) works end to end against the real API, not that the LLM step is
  earning its place yet. That's the explicit, stated scope of v1.
- Seven Minor findings from the implementation's final review remain
  deferred, unaffected by this run: free-text LLM escalation reasons
  degrade `escalation_reasons` from a histogram into near-unique strings;
  `_MODEL` is read at import time so `PLANNER_MODEL` set afterward has no
  effect; the unpriced-model pricing guard fires only after a billed call;
  the USD-as-USDC 1:1 assumption in the pricing table is undocumented;
  `langchain-core` isn't pinned even though the code depends on one of its
  version-sensitive internal behaviors; the README doesn't mention
  `ANTHROPIC_API_KEY` or this script; and the `escalate=True`-with-a-
  non-null-`vendor_id` decision branch has no dedicated test.
