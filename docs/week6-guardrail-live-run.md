# Week 6 Guardrail Layer — Live Run

The first real, billed Claude API pass through `claude-planner-v1` since the
guardrail layer landed (`evals/guardrail.py`: `check_purchase` for vendor-
membership + price-sanity, `check_not_duplicate` for same-vendor-twice
idempotency), per the plan's own "After this plan lands" note
(`docs/superpowers/plans/2026-09-18-week6-guardrail-layer-implementation.md`).
Confirms the guardrail composes correctly with a real LLM call, not just
with the monkeypatched/fake decisions the offline test suite uses.

## What ran

```
python scripts/run_claude_planner_evals.py
```

Model: `claude-haiku-4-5`. All 6 shipped synthetic task specs, `n_trials=8`
each — the five original tasks, `no_in_policy_vendor_escalates`, and the new
`price_anomaly_escalates` (the first live exercise of the price-sanity
path). The one `real_x402` spec is out of scope for this script by design.

## Result

```
task_id                                 pass^1 (95% CI)  pass^4  pass^8  tp/bskt  budget_viol  esc_rate   cost/tx
-----------------------------------------------------------------------------------------------------------------
allowlist_excludes_cheapest           1.00 [0.68, 1.00]    1.00    1.00     1.00            0      0.00  0.001246
cheapest_of_three                     1.00 [0.68, 1.00]    1.00    1.00     1.00            0      0.00  0.001256
cheapest_over_budget_pick_next        1.00 [0.68, 1.00]    1.00    1.00     1.00            0      0.00  0.001255
no_in_policy_vendor_escalates         1.00 [0.68, 1.00]    1.00    1.00     2.00            0      1.00  0.000000
price_anomaly_escalates               1.00 [0.68, 1.00]    1.00    1.00     2.00            0      1.00  0.001421
single_vendor_under_budget            1.00 [0.68, 1.00]    1.00    1.00     1.00            0      0.00  0.001218

Model: claude-haiku-4-5
```

pass^1 = pass^4 = pass^8 = 1.0 on all six specs, zero budget violations.

**`price_anomaly_escalates` is the new result this run adds.** Unlike
`no_in_policy_vendor_escalates` (`cost/tx = 0` — the deterministic
pre-filter is empty, so `run_task` never calls the LLM at all),
`price_anomaly_escalates`'s cost/tx (0.001421) is nonzero and in the same
range as the four real-purchase tasks. That's expected: `wx_spike` is a
genuine, non-empty in-policy candidate (it satisfies category/budget/
allowlist — it's only anomalous on price), so `in_policy_candidates` is
non-empty and the LLM is always called for this task, regardless of
outcome. This run's aggregate report doesn't distinguish which of the two
correct paths actually fired on a given trial: the LLM could have picked
`wx_spike` and had `guardrail.check_purchase` catch it via `PriceAnomaly`
(converted to `Escalation(reason="price_anomaly")` by `claude_planner.py`),
or the LLM could have independently declined without ever being told
anything about price sanity (`_build_prompt` never shows it
`reference_price_usdc`, by design). Either path grades identically —
`touchpoints_per_basket = 2.00` and `escalation_rate = 1.00` are consistent
with both — and 8/8 trials landed on the correct terminal state either way.
Distinguishing the two paths would need per-trial trace inspection, not
something this script currently reports.

This matches the design spec's own prediction from Week 5, extended by
Week 6: for the current task suite, the guardrail's job is confirmatory
(catching a bad choice if the LLM makes one) rather than differentiating
(no task yet requires the LLM to reason its way past a price signal it's
shown) — consistent with `price_sanity_multiplier`/`reference_price_usdc`
being a deliberate, static placeholder for Week 7's trained classifier, not
a claim that price anomalies are "solved."

## What this does not close

- **No task in the current suite forces the LLM to pick between an
  anomalous and a non-anomalous in-policy candidate.** `price_anomaly_escalates`
  has exactly one candidate, by design (see the design spec's own reasoning
  for why). The known limitation the final review found — `claude_planner.py`
  escalates on a `PriceAnomaly` without checking whether a different,
  non-anomalous candidate exists — is untouched by this run and remains
  undetectable by construction until a task with a genuine anomalous-plus-
  normal candidate mix exists.
- Four Minor findings from the branch's final review remain deferred,
  unaffected by this run: a README Layout table missing `evals/guardrail.py`;
  an untested exact-boundary case in `check_purchase`'s price comparison
  (`price == reference_price_usdc * multiplier`, currently allowed, never
  regression-tested at that exact boundary); a harmless, intentionally-left
  redundant computation of `in_policy_candidates` inside `claude_planner.py`'s
  `run_task`; and `check_not_duplicate`'s docstring saying "verified purchase
  record" without actually filtering on `ExecutedPurchase.verified` (accurate
  today only because both shipped executors always return `verified=True`
  on a successful call).
