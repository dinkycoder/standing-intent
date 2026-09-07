from pathlib import Path

import pytest

from evals.harness import cheapest_in_policy_vendor
from evals.models import TaskSpec

TASK_DIR = Path("evals/tasks")
TASK_FILES = sorted(TASK_DIR.glob("*.json"))


def test_at_least_four_task_specs_shipped():
    assert len(TASK_FILES) >= 4


@pytest.mark.parametrize("path", TASK_FILES, ids=[p.stem for p in TASK_FILES])
def test_task_spec_loads(path):
    task = TaskSpec.from_json_file(path)
    assert task.task_id == path.stem


@pytest.mark.parametrize("path", TASK_FILES, ids=[p.stem for p in TASK_FILES])
def test_task_spec_is_self_consistent(path):
    task = TaskSpec.from_json_file(path)
    target = cheapest_in_policy_vendor(task)
    assert target is not None, f"{path.stem}: no in-policy vendor satisfies the mandate"
    assert target.vendor_id == task.grading.expected_purchase.vendor_id, (
        f"{path.stem}: cheapest in-policy vendor is {target.vendor_id}, "
        f"but grading expects {task.grading.expected_purchase.vendor_id}"
    )


@pytest.mark.parametrize("path", TASK_FILES, ids=[p.stem for p in TASK_FILES])
def test_expected_price_within_max(path):
    task = TaskSpec.from_json_file(path)
    target = cheapest_in_policy_vendor(task)
    assert target.price_usdc <= task.grading.expected_purchase.max_price_usdc
