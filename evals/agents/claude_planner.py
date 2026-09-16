"""claude-planner-v1: a single structured LLM call over a deterministically
pre-filtered candidate list.

See docs/superpowers/specs/2026-09-15-week5-planner-v1-design.md.

Policy enforcement (category, budget, allowlist) happens entirely in
evals.harness.in_policy_candidates -- the same function
evals.harness.cheapest_in_policy_vendor calls for grading's own target-vendor
metric. The LLM below is never shown a vendor that function excludes, and
run_task re-checks the returned vendor_id against that same candidate list
before it spends anything -- so "the LLM picked an out-of-policy vendor" is
structurally impossible (no payment can be issued for one), not just
tested-for.
"""

from __future__ import annotations

import os
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import UsageMetadata
from pydantic import BaseModel, Field

from evals.agent_protocol import agent
from evals.executor import PaymentExecutor
from evals.harness import in_policy_candidates
from evals.models import AgentResult, Escalation, Mandate, Purchase, TaskSpec, Vendor

# Bare model id, no date suffix -- confirmed against the live API's current
# pricing table (claude-api skill, 2026-09-15). A date-suffixed variant is
# used elsewhere in this project's own tooling; that is a different string.
_MODEL = os.environ.get("PLANNER_MODEL", "claude-haiku-4-5")

# USDC per token, keyed by the exact model id in _MODEL. Sourced from the
# claude-api skill's pricing table, not assumed. Add an entry here -- do not
# guess a price -- before pointing PLANNER_MODEL at a different model.
_PRICE_PER_MILLION_TOKENS_USDC: dict[str, tuple[Decimal, Decimal]] = {
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
}


class _Decision(BaseModel):
    vendor_id: Optional[str] = Field(
        default=None,
        description="The chosen vendor_id from the candidate list, or null if escalating.",
    )
    escalate: bool = Field(
        description="True if no candidate genuinely satisfies the task; false otherwise.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Required when escalate is true: a short reason a human can act on.",
    )


@agent("claude-planner-v1")
def run_task(task: TaskSpec, rng_seed: int, executor: PaymentExecutor) -> AgentResult:
    candidates = in_policy_candidates(task)
    if not candidates:
        return AgentResult(
            purchases=[],
            touchpoints=2,
            escalations=[Escalation(reason="no_in_policy_vendor")],
            trace=["no in-policy candidate; escalated without an LLM call"],
        )

    decision, usage = _ask_claude(task.description, task.mandate, candidates)
    cost = _token_cost_usdc(usage)

    if decision.escalate or decision.vendor_id is None:
        return AgentResult(
            purchases=[],
            touchpoints=2,
            escalations=[Escalation(reason=decision.reason or "planner_escalated")],
            cost_usdc=cost,
            trace=[f"LLM escalated: {decision.reason}"],
        )

    # decision.vendor_id is free-form model output. Membership in `candidates`
    # is what makes this module's "structurally impossible" claim true: without
    # it, a hallucinated id reaches SyntheticExecutor as a raw KeyError that
    # aborts the whole n-trial run, and a real-but-filtered-out id (the
    # executor is keyed off the FULL catalog, not the candidate set) gets PAID
    # before grading ever sees it -- on a real_x402 environment, on-chain.
    # Raised, not escalated: out-of-contract model output is a bug, handled the
    # same way as _ask_claude's parsing_error, never downgraded into a grade.
    by_id = {c.vendor_id: c for c in candidates}
    chosen = by_id.get(decision.vendor_id)
    if chosen is None:
        raise ValueError(
            f"LLM returned vendor_id {decision.vendor_id!r}, not among the "
            f"{len(candidates)} offered candidate(s): "
            f"{[c.vendor_id for c in candidates]}"
        )
    # SyntheticExecutor.pay() takes a vendor_id; RealX402Executor.pay() takes a
    # URL. Vendor.url is set exactly on the specs that need the latter, so the
    # url-else-vendor_id target satisfies both without the agent knowing which
    # executor it was handed.
    executed = executor.pay(
        chosen.url or chosen.vendor_id, max_amount=task.mandate.budget_cap_usdc
    )
    return AgentResult(
        purchases=[Purchase(vendor_id=executed.vendor_id, price_usdc=executed.amount_paid)],
        touchpoints=1,
        cost_usdc=cost,
        trace=[f"picked {executed.vendor_id} from {len(candidates)} in-policy candidate(s)"],
    )


def _ask_claude(
    description: str,
    mandate: Mandate,
    candidates: list[Vendor],
    llm: BaseChatModel | None = None,
) -> tuple[_Decision, UsageMetadata | None]:
    llm = llm or ChatAnthropic(model=_MODEL, temperature=0)
    # include_raw=True: the parsed _Decision alone drops token-usage metadata,
    # which _token_cost_usdc needs. Confirmed against langchain_core's own
    # with_structured_output source: with include_raw=True a parsing failure
    # is CAUGHT and returned in parsing_error, not raised -- unlike the
    # include_raw=False default. Must check it explicitly, or a parse failure
    # silently becomes parsed=None, which run_task would otherwise misreport
    # as an agent decision instead of an LLM/parsing bug.
    structured = llm.with_structured_output(_Decision, include_raw=True)
    result = structured.invoke(_build_prompt(description, mandate, candidates))
    if result["parsing_error"] is not None:
        raise result["parsing_error"]
    return result["parsed"], result["raw"].usage_metadata


def _build_prompt(description: str, mandate: Mandate, candidates: list[Vendor]) -> str:
    candidate_lines = "\n".join(
        f"- vendor_id={c.vendor_id!r}, price_usdc={c.price_usdc}" for c in candidates
    )
    quality_line = (
        f"Quality threshold (informational only -- no vendor field carries a "
        f"quality score yet): {mandate.quality_threshold}\n"
        if mandate.quality_threshold is not None
        else ""
    )
    return (
        "You are a procurement agent buying a single digital good under a "
        "fixed budget, on behalf of a human who will not be consulted again.\n"
        f"Task: {description}\n"
        f"Goal category: {mandate.goal_category}\n"
        f"Budget cap (USDC): {mandate.budget_cap_usdc}\n"
        f"{quality_line}"
        "Candidates (already filtered to in-policy vendors -- category, "
        "allowlist, and budget are already satisfied by every one of these; "
        "pick one or escalate):\n"
        f"{candidate_lines}\n\n"
        "Pick the candidate that best satisfies the task's stated intent. If "
        "none of the candidates genuinely fit the task, set escalate=true and "
        "give a short reason. Otherwise set vendor_id to the chosen "
        "candidate's vendor_id and escalate=false."
    )


def _token_cost_usdc(usage: UsageMetadata | None) -> Decimal:
    if not usage:
        return Decimal("0")
    try:
        price_in, price_out = _PRICE_PER_MILLION_TOKENS_USDC[_MODEL]
    except KeyError:
        raise ValueError(
            f"no known USDC pricing for model {_MODEL!r}; add it to "
            "_PRICE_PER_MILLION_TOKENS_USDC in evals/agents/claude_planner.py "
            "before using this model"
        )
    million = Decimal(1_000_000)
    cost = (
        Decimal(usage["input_tokens"]) * price_in
        + Decimal(usage["output_tokens"]) * price_out
    ) / million
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
