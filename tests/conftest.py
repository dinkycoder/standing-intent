import copy
import json

import pytest

SAMPLE_TASK = {
    "task_id": "sample",
    "description": "sample task for tests",
    "mandate": {
        "goal_category": "weather-data",
        "budget_cap_usdc": "0.05",
        "vendor_allowlist": None,
        "quality_threshold": None,
    },
    "environment": {
        "vendors": [
            {"vendor_id": "v1", "category": "weather-data", "price_usdc": "0.01", "in_allowlist": True},
            {"vendor_id": "v2", "category": "weather-data", "price_usdc": "0.08", "in_allowlist": True},
        ]
    },
    "grading": {
        "expected_purchase": {"vendor_id": "v1", "max_price_usdc": "0.05"},
        "budget_adherence_required": True,
    },
}


@pytest.fixture
def sample_task_dict():
    return copy.deepcopy(SAMPLE_TASK)


@pytest.fixture
def sample_task_file(tmp_path, sample_task_dict):
    path = tmp_path / "sample_task.json"
    path.write_text(json.dumps(sample_task_dict), encoding="utf-8")
    return path


@pytest.fixture
def sample_task(sample_task_file):
    from evals.models import TaskSpec

    return TaskSpec.from_json_file(sample_task_file)
