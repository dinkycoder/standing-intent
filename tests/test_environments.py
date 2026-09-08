import pytest

from evals.environments import resolve_executor
from evals.executor import RealX402Executor, SyntheticExecutor


def test_synthetic_env_resolves_synthetic_executor(sample_task):
    assert isinstance(resolve_executor(sample_task), SyntheticExecutor)


def test_real_x402_env_needs_a_wallet(sample_task_dict):
    from evals.models import TaskSpec
    sample_task_dict["environment"]["kind"] = "real_x402"
    task = TaskSpec.model_validate(sample_task_dict)
    with pytest.raises(ValueError):
        resolve_executor(task, wallet=None)
    assert isinstance(resolve_executor(task, wallet=object()), RealX402Executor)
