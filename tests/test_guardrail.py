from decimal import Decimal

import pytest

from evals.executor import ExecutedPurchase
from evals.guardrail import (
    DuplicatePurchaseAttempt,
    PriceAnomaly,
    VendorNotOffered,
    check_not_duplicate,
    check_purchase,
)
from evals.models import TaskSpec


# ---- check_purchase: vendor membership -------------------------------

def test_check_purchase_returns_the_matched_vendor(sample_task):
    vendor = check_purchase(sample_task, "v1")
    assert vendor.vendor_id == "v1"


def test_check_purchase_matches_by_url_when_caller_passes_a_url(sample_task_dict):
    sample_task_dict["environment"]["vendors"][0]["url"] = "https://example.test/wx"
    task = TaskSpec.model_validate(sample_task_dict)
    vendor = check_purchase(task, "https://example.test/wx")
    assert vendor.vendor_id == "v1"


def test_check_purchase_rejects_a_vendor_outside_in_policy_candidates(sample_task):
    # v2 is a real vendor in sample_task's catalog (0.08) but over the 0.05
    # cap, so it's excluded from in_policy_candidates.
    with pytest.raises(VendorNotOffered, match="'v2'"):
        check_purchase(sample_task, "v2")


def test_check_purchase_rejects_an_id_in_no_catalog_at_all(sample_task):
    with pytest.raises(VendorNotOffered, match="'nonexistent'"):
        check_purchase(sample_task, "nonexistent")


# ---- check_purchase: price sanity -------------------------------------

def test_check_purchase_rejects_a_price_far_above_reference(sample_task_dict):
    sample_task_dict["mandate"]["price_sanity_multiplier"] = "2"
    sample_task_dict["environment"]["vendors"][0]["reference_price_usdc"] = "0.001"
    # v1's price is 0.01; 2x its reference (0.001) is 0.002 -- 0.01 > 0.002.
    task = TaskSpec.model_validate(sample_task_dict)
    with pytest.raises(PriceAnomaly, match="'v1'"):
        check_purchase(task, "v1")


def test_check_purchase_allows_a_price_within_the_multiplier(sample_task_dict):
    sample_task_dict["mandate"]["price_sanity_multiplier"] = "2"
    sample_task_dict["environment"]["vendors"][0]["reference_price_usdc"] = "0.01"
    # v1's price (0.01) does not exceed 2x its reference (0.02).
    task = TaskSpec.model_validate(sample_task_dict)
    vendor = check_purchase(task, "v1")
    assert vendor.vendor_id == "v1"


def test_check_purchase_skips_price_check_when_reference_price_unset(sample_task):
    # sample_task's vendors carry no reference_price_usdc -- must be a
    # no-op, not an error, for every existing task spec.
    vendor = check_purchase(sample_task, "v1")
    assert vendor.vendor_id == "v1"


def test_check_purchase_skips_price_check_when_multiplier_unset(sample_task_dict):
    sample_task_dict["environment"]["vendors"][0]["reference_price_usdc"] = "0.001"
    # No price_sanity_multiplier on the mandate -- must not fire even though
    # the price is wildly above this reference.
    task = TaskSpec.model_validate(sample_task_dict)
    vendor = check_purchase(task, "v1")
    assert vendor.vendor_id == "v1"


# ---- check_not_duplicate -----------------------------------------------

def _executed(vendor_id, url=None, amount="0.01"):
    return ExecutedPurchase(vendor_id=vendor_id, url=url, amount_paid=Decimal(amount),
                             pay_to=None, tx_hash=None, verified=True, resource=None)


def test_check_not_duplicate_allows_the_first_payment():
    check_not_duplicate("v1", [])  # must not raise


def test_check_not_duplicate_rejects_the_same_vendor_twice():
    already = [_executed("v1")]
    with pytest.raises(DuplicatePurchaseAttempt, match="'v1'"):
        check_not_duplicate("v1", already)


def test_check_not_duplicate_allows_a_different_vendor():
    already = [_executed("v1")]
    check_not_duplicate("v2", already)  # must not raise


def test_check_not_duplicate_matches_by_url_too():
    already = [_executed("v1", url="https://example.test/wx")]
    with pytest.raises(DuplicatePurchaseAttempt):
        check_not_duplicate("https://example.test/wx", already)
