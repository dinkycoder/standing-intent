# Week 5 — Planner-Executor Agent v1: Design

**Date:** 2026-09-15
**Status:** approved, pending implementation plan

## Why this exists

`docs/PMF_AND_BUILD_PLAN.md`'s Deliverable E names Week 5 as "Planner-executor
agent v1. LangChain planner decomposes mandate; executor discovers + buys;
memory in vector DB" — one line, three bundled decisions that don't survive
first contact with the current harness. This spec narrows it to what actually
belongs in v1, and defers the rest with reasons, not silence.

`evals/agents/stub.py` is the only agent that exists today, and it always
fails by design (CLAUDE.md rule 3's literal, runnable failing eval). Five task
specs already ship in `evals/tasks/` and already stress-test real reasoning —
allowlist exclusion, over-budget fallback, a decoy in another category — none
of which the stub can pass. Week 5 replaces the stub with an agent that can.

## Scope decisions made during brainstorming

1. **Single-item, not multi-item.** The current `Mandate`/`Grading` model
   (`evals/models.py`) is single-purchase: one `ExpectedPurchase`, graded via
   `len(executed) != 1 -> FAIL`. Multi-item baskets need a data-model change
   (`Mandate` carrying several goal items, `Grading` checking a basket), not
   just a smarter agent — and that change is exactly the trigger condition the
   Week-4 design spec and `docs/MATH_COURSEWORK_PLAN.md` both already flagged
   for when Optimization Models becomes relevant. v1 stays single-item against
   the existing model; multi-item baskets are their own later milestone.
2. **No vector-store memory.** The harness runs each of `n_trials` independently
   and stateless; there is no repeated interaction with the same vendor across
   trials yet for anything to remember. Standing up pgvector now, with nothing
   real to write to it, is infrastructure ahead of a need. Memory arrives once
   there's real purchase history to learn from — naturally pairs with Week 7's
   trained classifier, which needs the same vendor+price history anyway.
3. **One structured LLM call, not a tool-calling agent loop.** The task shape
   today is "reason over an already-fully-known candidate list," not "decide
   what to go look at" — there is nothing to discover step-by-step yet. A
   LangChain `AgentExecutor` with tools would spend every tool call reading the
   same catalog a single prompt already has in full. Multi-step tool-calling
   earns its place once discovery is a real action (a live x402 Bazaar query),
   not before.
4. **Policy enforcement is deterministic, not LLM-judged.** `.claude/agents/planner.md`
   already commits to this: "Keep policy enforcement out of both [planner and
   executor] — it lives in its own layer." A plain-Python pre-filter narrows
   `task.environment.vendors` to in-policy candidates (right category, in
   allowlist, under budget) *before* the LLM ever sees them — the same
   principle the on-chain Spend Permission cap already embodies for money
   movement: a hard guarantee from code, not best-effort LLM judgment. Vendor
   policy correctness cannot regress with a prompt change.
5. **No baseline agent yet.** Deliverable E says the harness must eventually
   beat "a ReAct/GPT-4o-style single-agent tool-caller" — but that comparison
   is explicitly `docs/PMF_AND_BUILD_PLAN.md`'s **Week 9** ("Eval run #1 vs
   baseline"), not Week 5. Building it now is scope creep on "v1."

## Architecture

New file, peer of the existing stub:

```
evals/agents/claude_planner.py    # @agent("claude-planner-v1")
```

Two-stage decision inside `run_task`:

1. **Deterministic pre-filter** (no LLM, no network): narrow
   `task.environment.vendors` to in-policy candidates. This reuses logic that
   already exists in `evals/harness.py::cheapest_in_policy_vendor` — that
   function's inline list comprehension (`category == mandate.goal_category`
   and `price_usdc <= budget_cap_usdc`, over `in_policy_vendors(task)`'s
   allowlist-filtered set) becomes its own function, `in_policy_candidates(task)
   -> list[Vendor]`, which `cheapest_in_policy_vendor` calls instead of
   inlining. **Grading behavior does not change** — this is an extraction, not
   a new filter. The planner calls the same function grading already trusts,
   so "the LLM saw an out-of-policy vendor" is structurally impossible, not
   just tested-for.
   - If `in_policy_candidates(task)` is empty, escalate immediately
     (`reason="no_in_policy_vendor"`) — no LLM call, no cost.
2. **One structured LLM call**, over the pre-filtered candidates only: the
   mandate, `task.description` (natural language — already a `TaskSpec` field,
   not something new), and the candidate list go in; a typed decision comes
   out. The LLM cannot pick an out-of-policy vendor because it is never shown
   one.

## Components & data flow

```python
# evals/agents/claude_planner.py
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel

class _Decision(BaseModel):
    vendor_id: str | None       # None iff escalate is True
    escalate: bool
    reason: str | None          # required iff escalate is True

@agent("claude-planner-v1")
def run_task(task: TaskSpec, rng_seed: int, executor: PaymentExecutor) -> AgentResult:
    candidates = in_policy_candidates(task)
    if not candidates:
        return AgentResult(
            purchases=[], touchpoints=2,
            escalations=[Escalation(reason="no_in_policy_vendor")],
            trace=["no in-policy candidate; escalated without an LLM call"],
        )

    decision, usage = _ask_claude(task.description, task.mandate, candidates)

    if decision.escalate or decision.vendor_id is None:
        return AgentResult(
            purchases=[], touchpoints=2,
            escalations=[Escalation(reason=decision.reason or "planner_escalated")],
            trace=[f"LLM escalated: {decision.reason}"],
        )

    executed = executor.pay(decision.vendor_id, max_amount=task.mandate.budget_cap_usdc)
    return AgentResult(
        purchases=[Purchase(vendor_id=executed.vendor_id, price_usdc=executed.amount_paid)],
        touchpoints=1,
        cost_usdc=_token_cost_usdc(usage),  # see Known limitations
        trace=[f"picked {executed.vendor_id} from {len(candidates)} in-policy candidate(s)"],
    )


def _ask_claude(description: str, mandate: Mandate, candidates: list[Vendor]) -> tuple[_Decision, dict]:
    llm = ChatAnthropic(model=_MODEL, temperature=0)
    # include_raw=True: the parsed _Decision alone drops token-usage metadata,
    # which _token_cost_usdc needs (Known limitations) -- this returns
    # {"raw": AIMessage, "parsed": _Decision | None, "parsing_error": BaseException | None}.
    # Confirmed against langchain_core's own with_structured_output source: with
    # include_raw=True a parsing failure is CAUGHT and returned in
    # parsing_error, not raised -- unlike the include_raw=False default. Must
    # check it explicitly or a parse failure silently becomes parsed=None,
    # which run_task would otherwise treat as an unexplained escalation.
    structured = llm.with_structured_output(_Decision, include_raw=True)
    result = structured.invoke(_build_prompt(description, mandate, candidates))
    if result["parsing_error"] is not None:
        raise result["parsing_error"]
    return result["parsed"], result["raw"].usage_metadata
```

`_build_prompt` renders the mandate fields, `task.description` verbatim, and
the candidate list (vendor_id + price_usdc each) into a plain instruction:
pick the candidate that best satisfies the mandate's stated intent, or
escalate with a reason if none genuinely fits. `quality_threshold` is passed
through to the prompt for the LLM to weigh even though no `Vendor` field
currently carries a quality signal for it to weigh *against* — see Known
limitations.

**Model:** `claude-haiku-4-5` by default — $1.00/$5.00 per 1M input/output
tokens, confirmed against the current pricing table rather than assumed; cheap
and fast, and nothing in today's task set needs a stronger model (see the
honesty note below). Overridable via an env var (`PLANNER_MODEL`) so a harder
future task set can swap it without a code change. **Use the bare model ID —
no date suffix.** (A date-suffixed variant appears in this project's own
tooling elsewhere; the live API model string is exactly `claude-haiku-4-5`.)

## Error handling

A Claude API failure (network, rate limit, malformed structured output that
`with_structured_output` can't coerce) **propagates as an exception** — it is
not caught and converted into an escalation. This matches the harness's
existing convention for the stub ("an agent that raises is a bug, not a graded
FAIL" — `evals/harness.py`'s own module docstring) and keeps infra flakiness
out of the pass^k numbers. Retry/recovery around LLM calls is explicitly
`docs/PMF_AND_BUILD_PLAN.md`'s **Week 8** scope ("Failure/recovery + retries"),
not v1's.

## New eval task (CLAUDE.md rule 3)

None of the five shipped task specs test the escalate-on-no-vendor path —
every one has a valid `expected_purchase`. Add
`evals/tasks/no_in_policy_vendor_escalates.json`: every vendor fails category,
budget, or allowlist, so there is no valid purchase and grading must instead
assert an escalation occurred (`len(result.escalations) >= 1` and
`len(executed) == 0`) rather than checking `expected_purchase`. This is a real
gap in the harness today, independent of who builds the agent that needs to
pass it — the stub currently "passes" this scenario only by accident (it
always escalates), so today nothing distinguishes correct escalation from the
stub's blanket failure mode.

`evals/grading.py`'s `grade()` needs a branch for this. Decided here, not left
to the plan: `Grading.expected_purchase` becomes `Optional[ExpectedPurchase]`
(currently required). When it's `None`, `grade()` asserts
`len(executed) == 0 and len(result.escalations) >= 1` (a real, intentional
escalation) instead of the vendor-match check — a task author states "this
scenario has no valid purchase" by simply omitting `expected_purchase`, rather
than a second flag that could disagree with it. The five existing task specs
are unaffected (all already set `expected_purchase`).

## Testing

Two tiers, matching the project's existing integration/offline split:

- **Offline, CI-run:** `in_policy_candidates` (pure function, already
  effectively tested via `cheapest_in_policy_vendor`'s existing tests) and
  `_ask_claude`'s response-handling, tested against a **fake** `ChatAnthropic`
  substitute (LangChain supports a fake/stub chat model for exactly this) —
  no network, no API cost, runs every build. Covers: escalation when no
  candidates exist, mapping a `_Decision` to the right `AgentResult` shape,
  and the malformed-output-propagates-as-exception path.
- **Live, cost-bearing, not CI-gated:** a real `run_eval` pass against all six
  task specs with a genuine Claude call, reporting real pass^1/pass^k. This is
  the actual "does this agent work" evidence CLAUDE.md rule 3 wants, and it
  costs real tokens per run — the exact mechanism (a new pytest marker vs. a
  standalone script mirroring `scripts/run_stub_evals.py`) is a plan-level
  decision.

**New secret:** `ANTHROPIC_API_KEY`, added to `.env.example` alongside the
existing `X402_WALLET_KEY`. Unset in CI, same convention as every other secret
in this repo.

**New dependency:** `langchain-anthropic==1.7.2` (pulling `langchain-core==1.6.3`)
— installed and confirmed to resolve cleanly during this design's writing, per
the x402 SDK's own precedent in this repo ("pin exact versions" — CLAUDE.md's
SDK caution section). `ChatAnthropic`'s constructor and
`with_structured_output`'s signature (`schema`, `include_raw`, `method`) were
both confirmed directly against the installed package's own source, not
assumed from a recalled API shape.

## Known limitations (stated plainly, not glossed over)

- **For the current six task specs, the LLM step is confirmatory, not
  differentiating.** Every task's pre-filtered candidate set has a unique
  cheapest option — a pure deterministic `min(candidates, key=price)` would
  already pass all six without any LLM call. The LLM earns its place once a
  task's `description` requires genuine judgment the numbers alone don't
  resolve (a stated preference that isn't reducible to price, an eventual
  quality or reliability signal to weigh). Building the LLM step now, against
  a natural-language `description` input rather than raw numbers, is choosing
  the right interface ahead of the harder task specs that will need it — not
  pretending today's version is solving a hard problem it isn't.
- **`quality_threshold` stays effectively unused**, same as everywhere else in
  the codebase — `Vendor` carries no quality field for the LLM to weigh it
  against. Passed through to the prompt for forward-compatibility, not because
  it changes today's outcomes.
- **`cost_usdc` on `AgentResult` needs a real number**, not a placeholder.
  LangChain's `ChatAnthropic` response carries token usage; converting that to
  a USDC estimate (at whatever the model's per-token price is) is an
  implementation-task detail, not a design one — flagged so it isn't silently
  left at `Decimal("0")`.

## Out of scope (deferred, not forgotten)

- Multi-item basket decomposition — own future milestone.
- Vector-store vendor memory — Week 7-adjacent, once there's real history.
- The ReAct/GPT-4o baseline agent — Week 9.
- Retry/recovery around LLM or settlement failures — Week 8.
- Live vendor discovery (a real x402 Bazaar query) — the trigger for
  multi-step tool-calling, not before.
