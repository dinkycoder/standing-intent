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


@pytest.fixture
def make_executed():
    from decimal import Decimal

    from evals.executor import ExecutedPurchase

    def _make(items=None):
        return [
            ExecutedPurchase(vendor_id=vid, url=None, amount_paid=Decimal(str(amt)),
                             pay_to=None, tx_hash=None, verified=True, resource=None)
            for vid, amt in (items or [])
        ]
    return _make


@pytest.fixture
def make_result():
    from decimal import Decimal

    from evals.models import AgentResult, Escalation, Purchase

    def _make(purchases=None, touchpoints=1, escalations=None, cost_usdc="0", trace=None):
        return AgentResult(
            purchases=[
                Purchase(vendor_id=vid, price_usdc=Decimal(str(price)))
                for vid, price in (purchases or [])
            ],
            touchpoints=touchpoints,
            escalations=[Escalation(reason=r) for r in (escalations or [])],
            cost_usdc=Decimal(str(cost_usdc)),
            trace=trace or [],
        )

    return _make
