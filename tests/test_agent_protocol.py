import pytest

from evals.agent_protocol import agent, require_agent_id
from evals.models import AgentResult


def test_agent_decorator_attaches_id_and_preserves_call():
    @agent("demo-v1")
    def run_task(task, rng_seed):
        return AgentResult(touchpoints=1)

    assert run_task.agent_id == "demo-v1"
    result = run_task(None, 0)
    assert isinstance(result, AgentResult)


def test_require_agent_id_returns_the_id():
    @agent("demo-v1")
    def run_task(task, rng_seed):
        return AgentResult(touchpoints=1)

    assert require_agent_id(run_task) == "demo-v1"


def test_require_agent_id_raises_for_undecorated_function():
    def run_task(task, rng_seed):
        return AgentResult(touchpoints=1)

    with pytest.raises(TypeError, match="@agent"):
        require_agent_id(run_task)


def test_require_agent_id_rejects_empty_id():
    with pytest.raises(ValueError):

        @agent("")
        def run_task(task, rng_seed):
            return AgentResult(touchpoints=1)


def test_agent_run_task_is_three_arg():
    import inspect
    from evals.agents.stub import run_task
    assert list(inspect.signature(run_task).parameters)[:3] == ["task", "rng_seed", "executor"]
