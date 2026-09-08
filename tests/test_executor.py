from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from evals.executor import (ExecutedPurchase, PaymentExecutor, RealX402Executor,
                            SyntheticExecutor)
from payments.errors import NoSatisfiableOffer, OfferOverCap


def test_synthetic_pays_at_catalog_price(sample_task):
    ex = SyntheticExecutor(sample_task)
    p = ex.pay("v1", max_amount=Decimal("0.05"))
    assert isinstance(p, ExecutedPurchase)
    assert p.vendor_id == "v1" and p.amount_paid == Decimal("0.01")
    assert p.verified is True and p.tx_hash is None and p.url is None


def test_synthetic_over_cap_raises(sample_task):
    with pytest.raises(OfferOverCap):
        SyntheticExecutor(sample_task).pay("v2", max_amount=Decimal("0.05"))  # v2 = 0.08


def test_synthetic_unknown_vendor_raises_keyerror(sample_task):
    with pytest.raises(KeyError):
        SyntheticExecutor(sample_task).pay("nope", max_amount=Decimal("1"))


def test_synthetic_is_a_payment_executor(sample_task):
    assert isinstance(SyntheticExecutor(sample_task), PaymentExecutor)


def test_real_executor_maps_outcome():
    outcome = Mock(paid=True, amount_paid=Decimal("0.01"), pay_to="0xabc",
                   tx_hash="0xdead", resource={"ok": 1})
    wallet = Mock()
    with patch("evals.executor.pay", return_value=outcome) as pay_mock:
        ex = RealX402Executor(wallet=wallet, network_allowlist=(84532,))
        p = ex.pay("http://seller/weather-data", max_amount=Decimal("0.05"))
    # Assert the forwarded args, not just the call count: a bare
    # assert_called_once() would pass a swapped-argument bug (punch-list #7).
    pay_mock.assert_called_once_with("http://seller/weather-data", wallet,
                                     max_amount=Decimal("0.05"),
                                     network_allowlist=(84532,))
    assert p.verified is True and p.amount_paid == Decimal("0.01")
    assert p.tx_hash == "0xdead" and p.url == "http://seller/weather-data"
    assert p.pay_to == "0xabc" and p.resource == {"ok": 1}
    # No task -> URL is unmapped -> a sentinel that can never equal a catalog id,
    # never the bare URL (I-4).
    assert p.vendor_id == "unmapped:http://seller/weather-data"


def test_real_executor_rejects_duplicate_vendor_urls(sample_task_dict):
    from evals.models import TaskSpec

    sample_task_dict["environment"]["kind"] = "real_x402"
    sample_task_dict["environment"]["vendors"][0]["url"] = "http://seller/weather-data"
    sample_task_dict["environment"]["vendors"][1]["url"] = "http://seller/weather-data"
    task = TaskSpec.model_validate(sample_task_dict)
    with pytest.raises(ValueError, match="share url"):
        RealX402Executor(wallet=Mock(), task=task)


def test_real_executor_reraises_payment_error():
    with patch("evals.executor.pay", side_effect=NoSatisfiableOffer("x")):
        ex = RealX402Executor(wallet=Mock())
        with pytest.raises(NoSatisfiableOffer):
            ex.pay("http://seller/permit2-only", max_amount=Decimal("1"))
