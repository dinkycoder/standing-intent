from pathlib import Path

import pytest

from evals import guardrail
from evals.harness import in_policy_candidates
from evals.models import TaskSpec, Vendor

TASK_DIR = Path("evals/tasks")
TASK_FILES = sorted(TASK_DIR.glob("*.json"))


def test_at_least_four_task_specs_shipped():
    assert len(TASK_FILES) >= 4


@pytest.mark.parametrize("path", TASK_FILES, ids=[p.stem for p in TASK_FILES])
def test_task_spec_loads(path):
    task = TaskSpec.from_json_file(path)
    assert task.task_id == path.stem


def _is_unpurchasable(task: TaskSpec, vendor: Vendor) -> bool:
    """A candidate that can never be the terminal state of a correct
    purchase: permanently down (Week 8 fault injection), or price-anomalous.

    Deliberately excludes fails_next_n_attempts > 0 -- a transient fault
    eventually succeeds, so that vendor stays a legitimate purchase target
    for this static self-consistency check (which has no notion of retries).
    """
    if vendor.down:
        return True
    try:
        guardrail.check_purchase(task, vendor.vendor_id)
    except guardrail.PriceAnomaly:
        return True
    return False


def _cheapest_purchasable(task: TaskSpec) -> Vendor | None:
    purchasable = [c for c in in_policy_candidates(task) if not _is_unpurchasable(task, c)]
    if not purchasable:
        return None
    return min(purchasable, key=lambda v: v.price_usdc)


@pytest.mark.parametrize("path", TASK_FILES, ids=[p.stem for p in TASK_FILES])
def test_task_spec_is_self_consistent(path):
    task = TaskSpec.from_json_file(path)
    target = _cheapest_purchasable(task)
    if task.grading.expected_purchase is None:
        # A null expected_purchase asserts no purchasable in-policy vendor
        # exists -- whether because none are in policy at all
        # (no_in_policy_vendor_escalates), every candidate is price-anomalous
        # (price_anomaly_escalates), every candidate is permanently down
        # (vendor_down_no_fallback_escalates), or some mix. A purchasable
        # target existing anyway would mean a correct agent should have
        # bought it, making the null expected_purchase wrong.
        assert target is None, (
            f"{path.stem}: {target.vendor_id if target else None} is "
            "purchasable in-policy, but grading expects no purchase at all"
        )
        return
    assert target is not None, f"{path.stem}: no purchasable in-policy vendor satisfies the mandate"
    assert target.vendor_id == task.grading.expected_purchase.vendor_id, (
        f"{path.stem}: cheapest purchasable in-policy vendor is {target.vendor_id}, "
        f"but grading expects {task.grading.expected_purchase.vendor_id}"
    )


@pytest.mark.parametrize("path", TASK_FILES, ids=[p.stem for p in TASK_FILES])
def test_expected_price_within_max(path):
    task = TaskSpec.from_json_file(path)
    if task.grading.expected_purchase is None:
        return
    target = _cheapest_purchasable(task)
    assert target.price_usdc <= task.grading.expected_purchase.max_price_usdc


@pytest.mark.parametrize("path", TASK_FILES, ids=[p.stem for p in TASK_FILES])
def test_real_x402_specs_ship_null_urls_and_wire_to_non_null(path):
    # A real_x402 spec ships `url: null` by design; wire_real_x402_task is
    # mandatory and must populate every vendor url (M-9). An unwired spec would
    # degrade to requests.get(None) -> a confusing EndpointUnreachable.
    task = TaskSpec.from_json_file(path)
    if task.environment.kind != "real_x402":
        return
    assert all(v.url is None for v in task.environment.vendors)
    from payments.testing.fixtures import wire_real_x402_task
    wired = wire_real_x402_task(task, "http://127.0.0.1:9")
    assert all(v.url for v in wired.environment.vendors)
