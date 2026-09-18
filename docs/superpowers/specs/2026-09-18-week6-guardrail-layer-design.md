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
directly inside `evals/agents/claude_planner.py`. `.claude/agents/planner.md`'s
own charter says policy enforcement should live in its own layer "so an agent
bug cannot bypass it" — but today, a different or buggy agent could call
`executor.pay(anything)` directly, with zero guardrail in the way, because the
only enforcement lives inside the one agent that happens to have it. This
week moves that check (and two new ones) into a layer every agent is forced
through, whether it knows the layer exists or not.

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
2. **Centralize enforcement, don't duplicate it.** The vendor-membership check
   moves out of `claude_planner.py` into a shared layer every agent's
   `pay()` call passes through, whether or not the agent's own author
   remembered to add a check. This is the same "one function, not two that
   could drift" principle Week 5's `in_policy_candidates` extraction already
   established.
3. **Price-sanity needs a reference, not a guess.** A price-anomaly check
   needs to compare an offer against *something*. Chosen: a `reference_price`
   the task spec declares per vendor (deterministic, testable, no new
   infrastructure) rather than deriving "normal" from the cheapest
   alternative in the same trial (which would false-flag a legitimately
   pricier vendor that's still the best available option). Week 7's trained
   classifier is the eventual place a *learned* price baseline belongs — this
   is the simple, honest placeholder Week 7 replaces or augments, the same
   way Week 5's LLM step is confirmatory rather than differentiating today.
4. **Two failure modes, not one.** A vendor outside the offered candidates
   and a second payment attempt in one trial are both **bugs** — a
   correctly-built agent should never produce either, so both raise and
   crash the trial loudly, the same way malformed LLM output already does.
   A price anomaly is different in kind: it's not the agent misbehaving, it's
   the world presenting something suspicious, so it raises a *different*,
   named exception the agent is expected to catch and convert into an honest
   escalation — matching `.claude/agents/planner.md`'s existing escalation
   list ("budget exhausted, no in-policy vendor found, or repeated settlement
   failure"), which this spec extends by one entry.

## Architecture

New module, peer of `evals/harness.py` and `evals/grading.py`:

```
evals/guardrail.py
```

`evals/harness.py`'s `_recording_view` — the per-trial wrapper every agent's
`pay()` call already passes through today, currently used only to record
verified purchases — gains one line: before delegating to the real executor,
it calls `guardrail.check_purchase(task, target, calls)`. `calls` is the same
list `_recording_view` already accumulates verified purchases into, which is
exactly the state the idempotency check needs (has a payment already
succeeded this trial?) — no new state threading required.

```python
# evals/guardrail.py
class PolicyViolation(Exception):
    """Base for every guardrail rejection. Never caught by the harness --
    callers (agents) decide per-subclass whether to escalate or let it
    crash, per the two-failure-mode split above."""

class VendorNotOffered(PolicyViolation):
    """target is not among in_policy_candidates(task). Structurally
    impossible for an agent that only ever acts on what it was shown --
    a hallucinated id, or a real-but-filtered-out id, is a bug in the
    caller, not a policy question. Never caught; always crashes the trial."""

class DuplicatePurchaseAttempt(PolicyViolation):
    """A second pay() call in one trial. Today's model is one purchase per
    task -- a second attempt cannot be a legitimate retry (nothing in this
    codebase issues retries yet; that's Week 8), so it is always a bug.
    Never caught; always crashes the trial."""

class PriceAnomaly(PolicyViolation):
    """The offered price exceeds its own reference_price by more than the
    mandate's price_sanity_multiplier. Not a bug -- a legitimate reason to
    escalate instead of buying. Agents are expected to catch this
    specifically and convert it into Escalation(reason="price_anomaly")."""


def check_purchase(
    task: TaskSpec, target: str, already_purchased: list[ExecutedPurchase]
) -> Vendor:
    """Run before every payment. Raises a PolicyViolation subclass, or
    returns the matched Vendor if the purchase may proceed. Never mutates
    anything -- a pure function over its three inputs, independently
    testable with no agent, executor, or LLM involved."""
```

`target` is matched against `in_policy_candidates(task)` by **either**
`vendor_id` **or** `url` (whichever the caller passed) — `claude_planner.py`
already passes `chosen.url or chosen.vendor_id` to satisfy both
`SyntheticExecutor` (vendor_id-keyed) and `RealX402Executor` (url-keyed);
`check_purchase` must accept the same either-or shape rather than forcing
every caller back onto one convention.

Check order inside `check_purchase`: (1) `already_purchased` non-empty →
`DuplicatePurchaseAttempt`; (2) `target` not found in
`in_policy_candidates(task)` → `VendorNotOffered`; (3) the matched vendor has
`reference_price_usdc` set, the mandate has `price_sanity_multiplier` set,
and `price_usdc > reference_price_usdc * price_sanity_multiplier` →
`PriceAnomaly`; (4) otherwise return the matched `Vendor`. Order matters:
idempotency first means a hostile double-pay attempt never leaks *which*
later check it would have failed.

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

Two changes, both simplifications relative to today:

1. **Delete the inline `by_id`/`chosen` membership check** (current lines
   82-97) — `check_purchase` now does this, and doing it twice risks exactly
   the "two filters that could drift apart" problem the module's own
   docstring already warns against for `in_policy_candidates`.
   `check_purchase` needs the trial's `already_purchased` list, which lives
   inside `evals.harness`'s `_recording_view` closure, not something
   `run_task` has direct access to — so `check_purchase` runs *inside*
   `_recording_view`, not inside `run_task`. `run_task` calls
   `executor.pay(chosen.url or chosen.vendor_id, ...)` exactly as it does
   today, unaware that the executor it was handed (the `_View` from
   `_recording_view`) now invokes `check_purchase` before delegating to the
   real executor. `run_task` no longer does its own membership lookup at
   all; it just calls `pay()` and either gets a result or an exception.
   `_build_prompt` does **not** need to show the LLM `reference_price_usdc`
   — policy enforcement here stays deterministic and LLM-independent, the
   same principle Week 5's design already established for category/budget/
   allowlist ("a plain-Python pre-filter... before the LLM ever sees them").
   The guardrail catches a bad choice after the fact regardless of why the
   LLM made it; the LLM is never asked to reason about price sanity itself.
2. **Catch `PriceAnomaly` around the `executor.pay(...)` call**, converting
   it into `AgentResult(purchases=[], touchpoints=2,
   escalations=[Escalation(reason="price_anomaly")], cost_usdc=cost,
   trace=[...])` — the same shape as the existing "no in-policy candidate"
   and "LLM escalated" return paths just above it.
   `VendorNotOffered`/`DuplicatePurchaseAttempt` are **not** caught — they
   propagate, matching `evals/harness.py`'s own documented convention ("An
   agent that raises... is a bug... It is never recorded as a FAIL").

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
calls `executor.pay()` twice in one trial must have its second call raise
`DuplicatePurchaseAttempt`, and the trial must propagate that as a bug (no
`EvalReport` produced), mirroring the existing "vendor outside candidates
raises before paying" test pattern from Week 5's fix wave.

## Testing

- `evals/guardrail.py`'s `check_purchase` is a pure function — tested
  directly, with hand-built `TaskSpec`/`Vendor` fixtures, no agent or
  executor involved. Covers all three violations plus the pass-through case,
  matching `.claude/agents/tests.md`'s own priority: "Policy enforcement is
  tested independently of the agent."
- `evals/harness.py`'s wiring is tested via `run_eval` with small fake
  agents (the same pattern `tests/test_harness.py` already uses for
  `_recording_view`'s existing recording behavior) — one for the duplicate-
  payment case, one confirming a legitimate single payment still succeeds
  unchanged.
- `claude_planner.py`'s price-anomaly handling is tested via
  `tests/test_claude_planner.py`'s existing monkeypatch-`_ask_claude`
  pattern: fake a decision that would trigger `PriceAnomaly`, assert the
  agent escalates with the right reason rather than crashing.
- `evals/tasks/price_anomaly_escalates.json` is exercised the same way
  `no_in_policy_vendor_escalates.json` already is in
  `tests/test_task_specs.py`'s parametrized "all tasks" tests (which already
  branch on `expected_purchase is None`, so no further changes needed there)
  and in `tests/test_run_stub_evals.py` (the stub's blanket escalation
  happens to pass this task too, for the same "right state, not-yet-a-real-
  agent-decision" reason already documented for
  `no_in_policy_vendor_escalates`).
- Offline, CI-run, no network calls anywhere in this week's work — none of
  it touches `claude_planner.py`'s LLM call path except the one new
  monkeypatched test case above.

## Known limitations (stated plainly, not glossed over)

- **`reference_price_usdc` is a static, task-author-declared number**, not a
  learned or continuously-updated baseline. It cannot catch a genuinely novel
  price spike from a vendor with no declared reference — this is a
  deliberate placeholder for Week 7's trained vendor-selection/price-anomaly
  classifier, not a claim that price anomalies are "solved."
- **Idempotency is enforced as "at most one successful payment per trial,"
  full stop** — not a general-purpose idempotency-key protocol. This is
  correct for today's single-item-purchase model and deliberately simple;
  Week 8 ("Failure/recovery + retries") is where a legitimate retry after an
  ambiguous outcome needs to exist *without* tripping this guard, which will
  need a real idempotency-key design at that point, not an extension of this
  one.
- **This guardrail only protects the `SyntheticExecutor`/off-chain path.**
  It runs identically for `RealX402Executor`, but it cannot add any
  guarantee beyond what that executor's own code already provides — it
  cannot, for instance, make a real payment atomic with a policy check the
  way the on-chain Spend Permission cap would. That gap is exactly the
  "on-chain enforcement" half this spec defers.

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
