"""The Week-2 agent under test: it always fails.

This exists so CLAUDE.md rule 3 ("no capability is implemented before a failing
eval exists for it") has a literal, runnable failing eval, and so the harness is
exercised end to end before the wallet or planner exist. Replace with a real
baseline once the payments spine can make one runnable (Week 3+).
"""

from __future__ import annotations

from decimal import Decimal

from evals.agent_protocol import agent
from evals.models import AgentResult, Escalation


@agent("stub-v0")
def run_task(task, rng_seed, executor) -> AgentResult:
    return AgentResult(
        purchases=[],
        touchpoints=2,  # 1 mandate signature + 1 escalation
        escalations=[Escalation(reason="not_implemented")],
        cost_usdc=Decimal("0"),
        trace=["stub agent: no capability implemented"],
    )
