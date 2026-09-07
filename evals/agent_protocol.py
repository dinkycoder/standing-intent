"""The one interface every agent under test implements.

An agent is a callable ``run_task(task: TaskSpec, rng_seed: int) -> AgentResult``.
It carries a stable string id, attached by the ``@agent("...")`` decorator, which
the harness records in every EvalReport.
"""

from __future__ import annotations

from typing import Callable

from evals.models import AgentResult, TaskSpec

AgentFn = Callable[[TaskSpec, int], AgentResult]


def agent(agent_id: str) -> Callable[[AgentFn], AgentFn]:
    if not agent_id:
        raise ValueError("agent_id must be a non-empty string")

    def decorate(fn: AgentFn) -> AgentFn:
        fn.agent_id = agent_id  # type: ignore[attr-defined]
        return fn

    return decorate


def require_agent_id(fn: object) -> str:
    agent_id = getattr(fn, "agent_id", None)
    if not isinstance(agent_id, str) or not agent_id:
        raise TypeError(
            "agent function has no agent_id; wrap it with @agent(\"your-id\") "
            "from evals.agent_protocol"
        )
    return agent_id
