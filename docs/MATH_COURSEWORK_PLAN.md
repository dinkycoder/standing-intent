# Math coursework -> Standing Intent

Sequencing note for the Quantic "Mathematics for AI Engineering" specialization
(Advanced Differentiation, Optimization Models, Probability Fundamentals,
Probability Distributions) against this repo's build plan
(`docs/PMF_AND_BUILD_PLAN.md`). Each item lands as a normal PR, paired with the
code and eval it serves -- not a standalone writeup. This file just tracks
where each course earns a place and when.

| Course material | Lands in | Artifact |
|---|---|---|
| Probability Distributions -- Z-scores, standard normal | Now (Week 4 side-branch) | `evals/stats.py`, `docs/math/binomial-intervals.md` |
| Probability Fundamentals + Distributions -- conditional probability, Bayes, calibration | Week 7 (trained accept/reject/escalate classifier) | `docs/math/threshold-calibration.md` (not yet written) |
| Probability Fundamentals -- Bayes' rule | Week 7 (vendor-reliability memory as a Beta-Binomial update) | folded into the Week-7 PR |
| Optimization Models -- linear/integer programming, sensitivity analysis | Week 5+ (once the planner decomposes a mandate into a multi-item basket; `quality_threshold` on `Mandate` becomes a real constraint) | `docs/math/basket-optimization.md` (not yet written) |
| Probability Distributions -- interval on a ratio | Week 12 (the 10x touchpoints experiment) | `docs/math/10x-experiment-stats.md` (not yet written) |
| Advanced Differentiation | No repo artifact | Nothing in the 13-week plan needs hand-derived gradients or PyTorch; scikit-learn's `LogisticRegression` doesn't require it. |

Full reasoning for this mapping is in conversation, not restated here. This
table is the pointer, not the argument.
