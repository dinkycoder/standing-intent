# Binomial confidence intervals for the eval harness

**Course:** Quantic "Mathematics for AI Engineering" -- Probability Distributions,
"Z-Scores and the Standard Normal Distribution."
**Code:** `evals/stats.py`, wired into `evals/harness.py::run_eval`.
**Tests:** `tests/test_stats.py`.

## The problem this closes

`evals/harness.py` reports `pass_1`, `pass_k`, and `best_price_capture_rate` as
bare rates over `n_trials` (default 8). A rate with no interval around it, at
n=8, is precise-looking and imprecise in fact -- exactly the "wrong-but-plausible"
shape CLAUDE.md's rule 4 exists to catch, and the same overclaim rule 2 polices
for on-chain constants. `pass^1 = 0.75` at n=8 is consistent with a true
success rate anywhere from about 0.41 to 0.93 at 95% confidence. Publishing
0.75 alone hides that.

## Why Wilson, not the textbook Wald interval

The formula usually taught first is the **Wald interval**:

```
p_hat +/- z * sqrt(p_hat * (1 - p_hat) / n)
```

It is a normal approximation to the binomial, and it degrades badly in exactly
the two regimes this harness lives in:

- **Small n.** `n_trials` defaults to 8. The normal approximation the Wald
  interval leans on is a large-n asymptotic result.
- **p_hat near 0 or 1.** A stub agent scoring `pass^1 = 0`, or a tuned agent
  scoring `pass^1 = 1.0`, makes the Wald half-width `z * sqrt(p_hat*(1-p_hat)/n)`
  collapse to *exactly zero* -- reporting "0.00 successes, no uncertainty,"
  which is never true at n=8.

The **Wilson score interval** inverts the normal approximation to the
*score test* for p rather than approximating p_hat's sampling distribution
directly. Closed form:

```
p_hat = successes / n
z2    = z**2
center     = (p_hat + z2/(2n)) / (1 + z2/n)
half_width = z * sqrt(p_hat*(1-p_hat)/n + z2/(4n^2)) / (1 + z2/n)
interval   = [max(0, center - half_width), min(1, center + half_width)]
```

At `successes=0` or `successes=n` this still returns a proper, non-zero-width
interval bounded inside `[0, 1]` -- the property that matters here.

## Extending it to pass^k

`pass_k()` doesn't estimate a rate observed directly; it estimates **p^k**,
the probability that k independent fresh attempts would *all* succeed, via
the unbiased hypergeometric estimator `C(successes, k) / C(n_trials, k)` (see
its docstring). There is no independent binomial count of "k-successes" to
run Wilson on directly.

The fix used here: since `x -> x**k` is monotone increasing on `[0, 1]`,
bounding the per-trial success probability `p` bounds `p**k` the same way.
So `pass_k_interval()` computes the Wilson interval on `p` (i.e. on
`pass_1`), then raises both endpoints to the `k`-th power:

```
lo, hi = wilson_interval(successes, n_trials)
return lo**k, hi**k
```

This is an **approximation**, not an exact interval for the hypergeometric
estimator `pass_k()` returns -- the estimator and `p**k` coincide exactly
only as `n_trials` grows. Being explicit about that gap matters more here
than elsewhere in the repo: this is math applied past its textbook form, and
"an approximate interval, documented as such" is the honest version of the
same rule that says a plausible-but-wrong on-chain constant must be flagged,
not implemented quietly.

## What's still open

- `pass_k_interval`'s approximation quality at `n_trials=8` (the harness
  default) hasn't been checked against a simulation; it's a reasonable
  first cut, not a validated one.
- The Week-12 10x experiment (`docs/PMF_AND_BUILD_PLAN.md`) will need an
  interval on a *ratio* of two touchpoint counts, not a single proportion --
  Wilson doesn't directly apply there. That's a separate derivation for that
  week, not solved by this module.
