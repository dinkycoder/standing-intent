"""Purchase-time policy checks.

Two independent entry points, not a class -- they have different callers
and different guarantees:

check_purchase is agent-side and OPT-IN. An agent calls it before paying;
an agent that skips the call can still attempt an out-of-policy or
anomalously-priced purchase -- by design. Several existing harness tests
(see tests/test_harness.py) deliberately let a bad purchase complete to
prove grading, not the executor, catches it; wiring this into the executor
layer would break that established backstop. See
docs/superpowers/specs/2026-09-18-week6-guardrail-layer-design.md's "Two
enforcement points, not one".

check_not_duplicate is wired into evals.harness's per-trial executor
wrapper, UNCONDITIONALLY, because it needs the trial's VERIFIED purchase
record -- an agent's own bookkeeping cannot be trusted for this the way
in_policy_candidates (a pure function of the task, not of what happened)
can be.
"""

from __future__ import annotations

from evals.executor import ExecutedPurchase
from evals.models import TaskSpec, Vendor


class PolicyViolation(Exception):
    """Base for every guardrail rejection."""


class VendorNotOffered(PolicyViolation):
    """target is not among in_policy_candidates(task). Structurally
    impossible for an agent that only ever acts on what check_purchase
    itself just offered it -- a hallucinated id, or a real-but-filtered-out
    id, is a bug in the caller."""


class PriceAnomaly(PolicyViolation):
    """The matched vendor's price exceeds its own reference_price_usdc by
    more than the mandate's price_sanity_multiplier. Not a bug -- the world
    presented something suspicious, not the agent misbehaving."""


class DuplicatePurchaseAttempt(PolicyViolation):
    """The same vendor (by vendor_id or url) already appears in this
    trial's verified purchase record. Always a bug -- nothing in this
    codebase issues retries yet (that's Week 8), so there is never a
    legitimate reason to pay the same vendor twice in one trial."""


def check_purchase(task: TaskSpec, target: str) -> Vendor:
    # Local import: evals.harness imports check_not_duplicate from this
    # module at module level, so a top-level import here would be a
    # circular import.
    from evals.harness import in_policy_candidates

    candidates = in_policy_candidates(task)
    chosen = next(
        (c for c in candidates if c.vendor_id == target or c.url == target), None
    )
    if chosen is None:
        raise VendorNotOffered(
            f"{target!r} is not among the {len(candidates)} offered "
            f"candidate(s): {[c.vendor_id for c in candidates]}"
        )
    multiplier = task.mandate.price_sanity_multiplier
    if (
        chosen.reference_price_usdc is not None
        and multiplier is not None
        and chosen.price_usdc > chosen.reference_price_usdc * multiplier
    ):
        raise PriceAnomaly(
            f"{chosen.vendor_id!r} priced at {chosen.price_usdc} exceeds "
            f"{multiplier}x its reference price {chosen.reference_price_usdc}"
        )
    return chosen


def check_not_duplicate(target: str, already_purchased: list[ExecutedPurchase]) -> None:
    if any(p.vendor_id == target or p.url == target for p in already_purchased):
        raise DuplicatePurchaseAttempt(
            f"{target!r} already has a verified purchase this trial"
        )
