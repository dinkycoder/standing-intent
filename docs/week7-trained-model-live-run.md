# Week 7 Trained Model — Live Run

The first real runs of both Week 7 artifacts, per the plan's own "After this
plan lands" note
(`docs/superpowers/plans/2026-09-19-week7-trained-model-implementation.md`).
Neither artifact changes any live agent decision — this confirms the
training pipeline and the reliability-reporting pipeline both actually work
end to end, with real numbers, not just against per-task unit tests.

## Price classifier

```
python scripts/train_price_classifier.py
```

```
n=5000  seed=42  test accuracy=0.654

              precision    recall  f1-score   support

      accept      0.706     0.848     0.770       571
    escalate      0.534     0.419     0.470       360
      reject      0.613     0.275     0.380        69

    accuracy                          0.654      1000
   macro avg      0.617     0.514     0.540      1000
weighted avg      0.637     0.654     0.635      1000

Calibration (escalate, one-vs-rest, decile bins):
   predicted P(escalate)   empirical rate
                   0.115            0.110
                   0.198            0.150
                   0.251            0.250
                   0.301            0.270
                   0.351            0.400
                   0.400            0.470
                   0.448            0.390
                   0.485            0.510
                   0.520            0.530
                   0.550            0.520
```

**Bit-for-bit reproducible.** This is the exact output the branch's final
whole-branch review independently confirmed by re-running the script and
SHA-256'ing the result against the committed `evals/ml/price_classifier.joblib`
(byte-identical). Running it again here, after merge, reproduced the same
accuracy and the same calibration table to three decimal places.

**Accuracy in context:** 65.4% clears the majority-class baseline (57.1%,
per `tests/test_price_classifier.py`'s own regression guard) by a real
8.3-point margin — this specific number matters because an earlier,
rejected set of label-generation constants produced a classifier that only
barely beat that baseline (83.2% vs. 82.4%), which would have looked like a
working model while actually having learned almost nothing. See the design
spec and implementation plan for the full story.

**Calibration is genuinely good**, not just plausible-looking — see
`docs/math/threshold-calibration.md` for the full derivation and why this
particular synthetic setup makes calibration a real, checkable property
rather than a vacuous one. The largest gap between predicted and empirical
escalate-rate across all ten deciles is 7 points, on bins holding roughly
100 test points each — within ordinary sampling noise.

## Vendor reliability

```
python scripts/report_vendor_reliability.py
```

The first attempt at this crashed outright — a real, load-bearing finding,
not a smooth first run:

```
pydantic_core._pydantic_core.ValidationError: 2 validation errors for EvalReport
pass_1_ci
  Field required [type=missing, ...]
pass_k_ci
  Field required [type=missing, ...]
```

`evals/results/` (git-ignored, local to this machine) has accumulated
report files from every week this project has shipped since Week 3, written
under whatever `EvalReport` schema existed at the time. Eight files predate
`pass_1_ci`/`pass_k_ci` (both required fields with no default) and crashed
the entire aggregation with no indication of which file was the problem —
exactly the "a single bad file kills the whole report" gap the branch's own
final review flagged as a deferred Minor finding, now confirmed to actually
block real use rather than being a theoretical robustness concern. Fixed in
`a08d5df`: incompatible files are now skipped with a per-file message, and
aggregation continues over whatever *is* compatible.

With that fixed, every schema-compatible file that already existed still
reported **no vendor outcomes at all** — correctly, since every one of them
was written before this same branch's `evals/harness.py` change that
populates `vendor_outcomes` in the first place. To get real data, a fresh
live `claude-planner-v1` run was needed:

```
python scripts/run_claude_planner_evals.py
```

(all 6 synthetic tasks passed at pass^1 = 1.0, same as prior weeks' live
runs — see `docs/week5-claude-planner-live-run.md` /
`docs/week6-guardrail-live-run.md` for that convention). Then:

```
python scripts/report_vendor_reliability.py
```

```
vendor_id                    mean    95% CI (raw rate)     n
------------------------------------------------------------
wx_alpha                    0.900       [0.676, 1.000]     8
wx_bravo                    0.962       [0.862, 1.000]    24

All observed vendors show near-100% reliability; this reflects
SyntheticExecutor's current failure model, not a claim about real-world
vendor trustworthiness. See docs/superpowers/specs/2026-09-19-week7-trained-model-design.md's Known limitations.
```

This is real, working data — `wx_alpha`'s posterior is exactly
Beta(1+8, 1+0) from 8 genuine successful settlements, `wx_bravo`'s is
Beta(1+24, 1+0) from 24 (its higher count reflects being the cheapest
in-policy vendor across more of the six task specs, so it gets picked more
often across the 8-trial-per-task run). The caveat fires correctly and for
the right reason: `SyntheticExecutor` (the executor behind every synthetic
task, which is all but one shipped task) has no realistic failure injection
yet, so both vendors show a perfect record. That's the design spec's own
predicted "Known limitation," now observed directly rather than assumed.

## What this does not close

- Reliability scores remain uninteresting (near-100% for everything) until
  a real failure model exists — Week 8 ("Failure/recovery + retries") or
  real `real_x402` volume, per the design spec.
- The classifier is still not wired into any live decision — `claude_planner.py`'s
  behavior is unchanged by this week's work, by design.
- The eight skipped, incompatible-schema report files in `evals/results/`
  were left in place (not deleted, not migrated) — they're git-ignored,
  machine-local history from earlier weeks, and deleting a user's local
  files wasn't this task's call to make. They'll continue to print a
  skip message on every future run of this script on this machine, which
  is the honest, harmless behavior now that the crash is fixed.
