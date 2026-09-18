# Week 6 — Policy/Guardrail Layer: Design

**Date:** 2026-09-18
**Status:** approved, pending implementation plan

## Why this exists

`docs/PMF_AND_BUILD_PLAN.md`'s Deliverable E names Week 6 as "Policy/guardrail
layer. Allowlists, idempotency, price-sanity, escalation logic. Off-chain +
on-chain enforcement wired." This spec narrows that to what actually needs
building, given what Weeks 1-5 already shipped, and explicitly parks the
"on-chain enforcement wired" half with reasons (see "Out of scope").

**The real gap this closes:** Week 5's `claude-planner-v1` added a
vendor-membership check (candidate must come from `in_policy_candidates`)
directly inside `evals/agents/claude_planner.py`, duplicating logic a future
agent would have to reimplement (and could get subtly wrong) rather than
reuse. `.claude/agents/planner.md`'s own charter says policy enforcement
should live in its own layer "so an agent bug cannot bypass it" — this spec
delivers the *shared, reusable logic* half of that goal in full (one tested
function, not N reimplementations), but not a universal hard gate every
agent is forced through: reading the existing test suite in detail during
plan-writing surfaced that grading, not the executor, is this codebase's
established backstop for a purchase that violates policy anyway (see "Two
enforcement points, not one" below) — a genuine, stated compromise from the
original framing, not a silent one. The one check that *is* a hard,
universal gate is the new one: idempotency, wired into the executor layer
every agent already passes through for recording purposes today.

## Scope decisions made during brainstorming

1. **Off-chain guardrails only.** "On-chain enforcement wired" — routing a
   real x402 purchase through the Base Spend Permission's on-chain cap
   (`payments/spend_router.py`'s `spend_and_route`, or the bare `spend()`
   custodial-hop pattern) — is explicitly deferred. Investigation during
   brainstorming found no way to satisfy a real x402 seller's payment
   verification from Spend-Permission-capped funds without either (a) an
   on-chain transaction that has no home in any of the four schemes x402
   currently defines (confirmed against `x402-foundation/x402`'s own scheme
   specs), or (b) the "custodial hop" pattern the Week 4 spec already flagged
   and gated off mainnet pending a legal opinion that does not yet exist.
   Building this now would mean shipping code that can never reach a real
   user without that opinion, and would not strengthen (arguably would
   complicate) the "strictly non-custodial" pitch `docs/PMF_AND_BUILD_PLAN.md`
   itself identifies as load-bearing for Base Ecosystem Fund credibility. See
   "Out of scope" for the specific findings, so this isn't re-litigated from
   scratch later.
2. **Centralize the logic, don't duplicate it.** The vendor-membership check
   moves out of `claude_planner.py` into a shared function every agent can
   call, so a future agent reuses the exact same check instead of
   reimplementing (and potentially drifting from) it. This is the same "one
   function, not two that could drift" principle Week 5's
   `in_policy_candidates` extraction already established — see decision #4
   below for exactly how far "centralize" goes once the existing test suite
   is accounted for.
3. **Price-sanity needs a reference, not a guess.** A price-anomaly check
   needs to compare an offer against *something*. Chosen: a `reference_price`
   the task spec declares per vendor (deterministic, testable, no new
   infrastructure) rather than deriving "normal" from the cheapest
   alternative in the same trial (which would false-flag a legitimately
   pricier vendor that's still the best available option). Week 7's trained
   classifier is the eventual place a *learned* price baseline belongs — this
   is the simple, honest placeholder Week 7 replaces or augments, the same
   way Week 5's LLM step is confirmatory rather than differentiating today.
4. **Two enforcement points, not one — corrected after reading the existing
   test suite, not assumed.** The original brainstorming assumed all three
   checks belong at the same enforcement point (wrapped around every
   payment, universally, no way to bypass). Reading `tests/test_harness.py`
   in detail during plan-writing surfaced a real conflict: several existing,
   currently-passing tests *deliberately* let an out-of-policy or over-cap
   purchase complete, specifically to prove **grading** — not the executor —
   is what catches it. `test_no_in_policy_vendor_task_fails_a_purchase_even_if_verified`
   says so in its own comment: "the executor will happily sell it... grading
   is what enforces 'no valid purchase here,' not the executor." Making
   vendor-membership a mandatory, universal executor-level gate (as
   originally drafted) would silently invert that already-established
   principle and break those tests. Resolution, corrected here rather than
   discovered mid-plan and worked around silently:
   - **Vendor-membership and price-sanity stay a *shared, reusable
     function*** (`guardrail.check_purchase`) that a well-built agent calls
     *before* attempting payment — real centralization of the check *logic*
     (one function, not N agents each reinventing it, so a future agent
     can't drift from `claude_planner.py`'s), but **not** a mandatory gate
     every executor call passes through. An agent that skips calling it can
     still attempt a bad purchase — exactly as today — and grading remains
     the backstop, exactly as the existing tests already assume. Both raise
     when tripped: `VendorNotOffered` propagates as a bug (a well-built
     agent should never hit it, since it only ever acts on what
     `in_policy_candidates` already offered it); `PriceAnomaly` is the one
     exception `claude_planner.py` is expected to catch and turn into an
     escalation.
   - **Idempotency is the one check that *does* stay wired into the
     executor-wrapping layer** (`evals/harness.py`'s `_recording_view`),
     because it's the one check that genuinely needs the trial's *verified*
     purchase record — an agent's own bookkeeping can't be trusted for this
     the way `in_policy_candidates` (a pure function of the task, not of
     what happened) can. This does not conflict with the existing tests:
     read closely, `.claude/agents/tests.md`'s actual wording is "the same
     mandate step executed twice must not double-buy" — the same vendor
     paid twice, not any second payment in a trial. Under that narrower,
     correct reading, `test_overcap_execution_and_misreport_counts_both`
     (which deliberately pays two *different* vendors, v1 then v2, in one
     trial, to test cumulative budget tracking) is unaffected — only a
     repeat of the *same* vendor within one trial trips this guard.

## Architecture

New module, peer of `evals/harness.py` and `evals/grading.py`:

```
evals/guardrail.py
```

Two independent entry points, reflecting the two enforcement points above —
neither is a method on a class; both are plain functions with no shared
state:

```python
# evals/guardrail.py
class PolicyViolation(Exception):
    """Base for every guardrail rejection."""

class VendorNotOffered(PolicyViolation):
    """target is not among in_policy_candidates(task). Structurally
    impossible for an agent that only ever acts on what check_purchase
    itself just offered it -- a hallucinated id, or a real-but-filtered-out
    id, is a bug in the caller. claude_planner.py does not catch this; it
    propagates and crashes the trial, the same way malformed LLM output
    already does."""

class PriceAnomaly(PolicyViolation):
    """The matched vendor's price exceeds its own reference_price_usdc by
    more than the mandate's price_sanity_multiplier. Not a bug -- the world
    presented something suspicious, not the agent misbehaving.
    claude_planner.py catches this specifically and converts it into
    Escalation(reason="price_anomaly")."""

class DuplicatePurchaseAttempt(PolicyViolation):
    """The same vendor (by vendor_id or url) already appears in this
    trial's verified purchase record. Always a bug -- nothing in this
    codebase issues retries yet (that's Week 8), so there is never a
    legitimate reason to pay the same vendor twice in one trial. Never
    caught by callers; always crashes the trial."""


def check_purchase(task: TaskSpec, target: str) -> Vendor:
    """Called by an agent BEFORE it attempts payment -- not wrapped around
    the executor, so an agent that skips this call can still attempt a bad
    purchase (grading remains the backstop, matching the existing test
    suite's own assumption). Matches target against in_policy_candidates(task)
    by EITHER vendor_id or url (callers use both conventions -- see
    executor.py's two implementations). Raises VendorNotOffered or
    PriceAnomaly, or returns the matched Vendor if the purchase may proceed.
    A pure function of task and target -- independently testable with no
    agent, executor, or LLM involved. Imports in_policy_candidates from
    evals.harness INSIDE this function body, not at module level -- harness.py
    imports check_not_duplicate (below) from this module at module level, and
    a matching top-level import here would be a circular import."""


def check_not_duplicate(target: str, already_purchased: "list[ExecutedPurchase]") -> None:
    """Called from evals.harness's _recording_view, wrapped around EVERY
    payment attempt, unconditionally -- this is the one guardrail check an
    agent cannot skip, because it protects against the agent's own
    bookkeeping being wrong, not against the agent forgetting to ask. Raises
    DuplicatePurchaseAttempt if any entry in already_purchased matches
    target by vendor_id or url. A pure function -- does not touch task,
    in_policy_candidates, or anything from evals.harness, so no import
    cycle with check_purchase's harness dependency above."""
```

## Data model changes

Both new fields are optional, defaulting to "no check" — every existing task
spec (five synthetic + `no_in_policy_vendor_escalates` + `real_weather_sepolia`)
needs zero changes.

```python
# evals/models.py
class Vendor(_Model):
    vendor_id: str
    category: str
    price_usdc: UsdcAmount
    in_allowlist: bool = True
    url: Optional[str] = None
    reference_price_usdc: Optional[UsdcAmount] = None   # new


class Mandate(_Model):
    goal_category: str
    budget_cap_usdc: UsdcAmount
    vendor_allowlist: Optional[list[str]] = None
    quality_threshold: Optional[Decimal] = Field(default=None, ge=0)
    price_sanity_multiplier: Optional[Decimal] = Field(default=None, gt=0)   # new
```

`price_sanity_multiplier` lives on `Mandate`, not `Vendor`: it's a policy
choice about how much price movement a *task* tolerates, the same way
`budget_cap_usdc` is a mandate-level policy, not a per-vendor field.
`reference_price_usdc` lives on `Vendor`: it's a fact about that specific
catalog entry (what this vendor normally charges), the same way `price_usdc`
is.

## `claude_planner.py` changes

One change, a simplification relative to today: **replace the inline
`by_id`/`chosen` membership check** (current lines 82-97) **with a call to
`guardrail.check_purchase`**, which now owns both the membership lookup and
the new price-sanity check:

```python
try:
    chosen = guardrail.check_purchase(task, decision.vendor_id)
except guardrail.PriceAnomaly:
    return AgentResult(
        purchases=[],
        touchpoints=2,
        escalations=[Escalation(reason="price_anomaly")],
        cost_usdc=cost,
        trace=["price anomaly detected; escalated"],
    )
executed = executor.pay(chosen.url or chosen.vendor_id, max_amount=task.mandate.budget_cap_usdc)
```

`guardrail.VendorNotOffered` is **not** caught here — it propagates,
matching `evals/harness.py`'s own documented convention ("An agent that
raises... is a bug... It is never recorded as a FAIL") and the same
treatment the inline check it replaces already gave a bad vendor id.
`_build_prompt` does **not** need to show the LLM `reference_price_usdc` —
policy enforcement here stays deterministic and LLM-independent, the same
principle Week 5's design already established for category/budget/allowlist
("a plain-Python pre-filter... before the LLM ever sees them"). The
guardrail catches a bad choice after the fact regardless of why the LLM made
it; the LLM is never asked to reason about price sanity itself.

## New eval task (CLAUDE.md rule 3)

`evals/tasks/price_anomaly_escalates.json`: mirrors
`no_in_policy_vendor_escalates.json`'s structure exactly, but for a
different reason — **the single in-policy candidate** (the only vendor
`in_policy_candidates` returns; no other candidate exists to fall back to)
carries a `reference_price_usdc` far below its `price_usdc`, with the
mandate's `price_sanity_multiplier` set tight enough that this candidate
trips the check. A second, non-anomalous in-policy candidate would let a
correct agent just buy that one instead — silently avoiding the anomaly
rather than escalating on it — so this task's only in-policy candidate must
be the anomalous one, forcing escalation as the sole correct outcome. Reuses
the escalation-only grading Week 5 already built (`Grading.expected_purchase:
null` — no valid purchase should be made; the only correct terminal state is
an honest escalation with zero purchases).

A second, offline-only test (not a shipped task spec, since it tests
*harness* behavior, not agent behavior) proves idempotency: an agent that
calls `executor.pay("v1", ...)` **twice** — the same vendor both times — in
one trial must have its second call raise `DuplicatePurchaseAttempt`, and
the trial must propagate that as a bug (no `EvalReport` produced). A
companion test confirms `test_overcap_execution_and_misreport_counts_both`'s
existing pattern (two *different* vendors paid in one trial) is unaffected
— that test itself needs no changes, but the guard's "same vendor" scoping
needs its own positive-and-negative test pair, not just an inference from
the existing test continuing to pass.

## Testing

- `evals/guardrail.py`'s `check_purchase` and `check_not_duplicate` are pure
  functions — tested directly, with hand-built `TaskSpec`/`Vendor`/
  `ExecutedPurchase` fixtures, no agent or executor involved. Covers
  `VendorNotOffered`, `PriceAnomaly`, `DuplicatePurchaseAttempt`, and the
  pass-through case for each, matching `.claude/agents/tests.md`'s own
  priority: "Policy enforcement is tested independently of the agent."
- `evals/harness.py`'s `_recording_view` wiring (`check_not_duplicate` only
  — `check_purchase` is not wired into the executor layer, see "Two
  enforcement points, not one" above) is tested via `run_eval` with small
  fake agents, the same pattern `tests/test_harness.py` already uses: one
  agent paying the same vendor twice (must raise), one paying two different
  vendors (must still succeed, guarding against a regression toward the
  original, rejected "any second payment" design).
- `claude_planner.py`'s price-anomaly handling is tested via
  `tests/test_claude_planner.py`'s existing monkeypatch-`_ask_claude`
  pattern: fake a decision that would trigger `PriceAnomaly`, assert the
  agent escalates with the right reason rather than crashing.
- `evals/tasks/price_anomaly_escalates.json` is exercised the same way
  `no_in_policy_vendor_escalates.json` already is in
  `tests/test_run_stub_evals.py` (the stub's blanket escalation happens to
  pass this task too, for the same "right state, not-yet-a-real-agent-
  decision" reason already documented for `no_in_policy_vendor_escalates`).
  `tests/test_task_specs.py`'s `test_task_spec_is_self_consistent` needs a
  real update, not just automatic coverage from its existing
  parametrization: its current invariant ("`expected_purchase is null`
  implies `cheapest_in_policy_vendor` is `None`") is true for
  `no_in_policy_vendor_escalates` but false for this task — a genuinely
  in-policy vendor exists here, it's just price-anomalous, which
  `cheapest_in_policy_vendor` has no way to know about. The test needs a
  second branch: when a target exists despite a null `expected_purchase`,
  prove it's anomalous by asserting `guardrail.check_purchase(task,
  target.vendor_id)` raises `PriceAnomaly` — reusing the same function
  `claude_planner.py` calls, rather than re-deriving the price-sanity math
  a second time in the test.
- Offline, CI-run, no network calls anywhere in this week's work — none of
  it touches `claude_planner.py`'s LLM call path except the one new
  monkeypatched test case above.

## Known limitations (stated plainly, not glossed over)

- **`reference_price_usdc` is a static, task-author-declared number**, not a
  learned or continuously-updated baseline. It cannot catch a genuinely novel
  price spike from a vendor with no declared reference — this is a
  deliberate placeholder for Week 7's trained vendor-selection/price-anomaly
  classifier, not a claim that price anomalies are "solved."
- **Idempotency is enforced as "the same vendor cannot be paid twice in one
  trial,"** not a general-purpose idempotency-key protocol. This is correct
  for today's model (nothing issues retries yet) and deliberately simple;
  Week 8 ("Failure/recovery + retries") is where a legitimate retry after an
  ambiguous outcome needs to exist *without* tripping this guard — likely by
  re-paying the *same* vendor on purpose, which is exactly what this guard
  currently forbids unconditionally. That will need a real idempotency-key
  design at that point (distinguishing "a deliberate retry of purchase X"
  from "a duplicate of purchase X"), not an extension of this one.
- **`check_purchase` (vendor-membership, price-sanity) is opt-in, not
  enforced.** Only `claude_planner.py` is required by this spec to call it.
  A different or future agent that skips the call can still attempt an
  out-of-policy or anomalously-priced purchase — by design, so grading
  remains the backstop the existing test suite already assumes (see "Two
  enforcement points, not one"). This is a real, accepted gap relative to
  the original "an agent bug cannot bypass it" framing from brainstorming:
  this spec centralizes the *logic* so agents don't reimplement or drift
  from it, not a hard guarantee no agent can circumvent. Only
  `check_not_duplicate` is a hard guarantee, because only it runs inside
  the executor wrapper every agent passes through unconditionally.
- **Neither check adds any guarantee for `RealX402Executor` beyond what
  runs identically for `SyntheticExecutor`.** It cannot, for instance, make
  a real payment atomic with a policy check the way the on-chain Spend
  Permission cap would. That gap is exactly the "on-chain enforcement" half
  this spec defers.

## Out of scope (deferred, not forgotten)

- **On-chain enforcement wired into a real purchase.** Investigated in depth
  during brainstorming, not a superficial pass:
  - x402's "exact" scheme (the only one any real seller in this project has
    been shown to support) requires a signed EIP-3009-style authorization
    submitted over HTTP; a facilitator, not the buyer, executes the actual
    on-chain transfer. `payments/spend_router.py`'s `spend_and_route()`
    produces a plain on-chain transfer with no home in that flow — verified
    against the installed `x402` SDK's own facilitator source
    (`x402/mechanisms/evm/exact/facilitator.py`) and this project's own
    x402-protocol-gated test seller (`payments/testing/fixtures.py`).
  - Whether a Spend-Permission-capped Coinbase Smart Wallet could sign that
    authorization *directly* (no custodial hop at all) was also
    investigated: USDC's own `transferWithAuthorization` does support
    contract-wallet (ERC-1271) signatures (confirmed against Circle's
    `stablecoin-evm` source), but Coinbase's Smart Wallet has no primitive
    that caps *what a signer can sign* — only `SpendPermissionManager`'s
    on-chain *pull* function is capped; the wallet's own owner key retains
    full, uncapped signing authority regardless (confirmed against
    `coinbase/smart-wallet`'s `CoinbaseSmartWallet.sol`). No primitive
    anywhere in the ERC-4337/account-abstraction ecosystem was found that
    caps signature *content* generically, and ERC-1271's own interface
    (an opaque 32-byte hash, not the underlying struct) explains why one
    would be unusual to build.
  - Coinbase's "Agentic Wallets" product was investigated as a possible
    third path (a hardware-enforced cap checked *before* a signature is
    produced). It is real, but not viable for this project right now: the
    specific x402 spend-cap feature could not be confirmed to be backed by
    the same hardware guarantee as the platform's general Policy Engine
    (docs describe it separately, as a client-side tracker); its x402
    tooling is TypeScript-first with no confirmed Python path, conflicting
    with this project's own all-Python boundary (Week 1 gate); and most
    decisively, this project already hit a live CDP business-verification
    wall trying to use the same underlying infrastructure
    (`payments/wallet.py`'s `CdpWallet`, "NOT implemented -- CDP API
    credentials are blocked by CDP business verification as of 2026-09").
  - **Conclusion carried forward, not re-derived next time it comes up:**
    paying a real x402 seller from Spend-Permission-capped funds requires
    either full-authority signing (the "custodial hop": `spend()` pulls
    funds into a wallet this project's own code controls, which then signs
    an ordinary x402 payment) or Coinbase's own hosted infrastructure
    (which raises its own, different, equally real legal question). Both
    remain gated on an actual attorney's opinion this project does not yet
    have — see `docs/superpowers/specs/2026-09-13-spend-permission-account-design.md`'s
    existing mainnet gate, which this spec does not weaken or reopen.
  - If and when a legal opinion is obtained, the concrete improvement worth
    building at that point (not before) is **scoping the custodial-hop
    wallet per user** rather than one shared service-wide operational
    wallet — this removes the "pool funds from multiple users in one
    wallet" trigger even though it does not remove the underlying "holds a
    private key that can move user funds unilaterally" one. Recorded here so
    the idea isn't lost, not because it's being built now.
- **Allowlist enforcement itself** is not new work — `in_policy_candidates`
  (Week 5) already enforces category, budget, and allowlist before anything
  reaches an agent. This spec's "allowlists" line item from the roadmap is
  already satisfied; nothing further is needed.
- **Per-vendor rate limits** (named in `docs/PMF_AND_BUILD_PLAN.md`'s
  guardrail description) — no current task or eval scenario exercises
  repeated purchases from the same vendor across trials in a way a rate
  limit would meaningfully constrain; deferred until a real scenario needs
  it, per this project's YAGNI convention.
