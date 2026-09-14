"""Offline guards on the two money-moving entry points.

Both guards exist for reasons no later test would catch cheaply:

* `spend()` is the custodial-hop path -- USDC lands in OUR wallet before being
  forwarded. The design spec gates it to Base Sepolia until a
  money-transmission opinion exists (docs/superpowers/specs/2026-09-13-spend
  -permission-account-design.md, docs/PMF_AND_BUILD_PLAN.md's Caveats). That
  gate was prose only until now.
* `spend_and_route*()` target SPEND_ROUTER, a Base-Sepolia-only address we
  deployed ourselves. A call to an address with no code SUCCEEDS on the EVM,
  so on any other chain these would mine with status=1, return a tx hash, and
  pay nobody -- the silent-failure mode CLAUDE.md rule 2 is written against.

No network is touched: every guard is the first statement in its function.
"""

from decimal import Decimal

import pytest

from payments.constants import CHAIN_ID_BASE_MAINNET, CHAIN_ID_BASE_SEPOLIA, USDC_BASE_MAINNET
from payments.errors import PaymentError, SettlementNotConfirmed
from payments.spend_permission import SpendPermission, _receipt_or_raise, spend
from payments.spend_router import spend_and_route, spend_and_route_with_signature

_PERMISSION = SpendPermission(
    account="0x000000000000000000000000000000000000dEaD",
    spender="0x000000000000000000000000000000000000bEEF",
    token=USDC_BASE_MAINNET, allowance=50_000, period=86400,
)


def test_open_ended_spend_refuses_mainnet():
    with pytest.raises(PaymentError, match="Base-Sepolia-only"):
        spend(_PERMISSION, Decimal("0.01"), spender=None, network=CHAIN_ID_BASE_MAINNET)


@pytest.mark.parametrize("call", [
    lambda: spend_and_route(_PERMISSION, Decimal("0.01"), None, CHAIN_ID_BASE_MAINNET),
    lambda: spend_and_route_with_signature(
        _PERMISSION, Decimal("0.01"), b"", None, CHAIN_ID_BASE_MAINNET
    ),
])
def test_router_refuses_a_chain_it_is_not_deployed_on(call):
    with pytest.raises(PaymentError, match="only deployed on Base Sepolia"):
        call()


def test_router_guard_names_the_chain_it_does_allow():
    # A guard that fires on everything -- including Sepolia -- would pass the
    # two tests above while breaking the only path that works.
    from payments.spend_router import _require_router_chain
    assert _require_router_chain(CHAIN_ID_BASE_SEPOLIA) is None


def test_missing_receipt_raises_a_payment_error_carrying_the_tx_hash(monkeypatch):
    # wait_for_receipt raises a bare TimeoutError, and every call site is AFTER
    # broadcast: "money may have moved and we cannot confirm it." A caller that
    # only catches PaymentError would otherwise crash instead of reconciling,
    # and the tx hash -- the one thing needed to reconcile -- would be buried
    # in a string.
    import payments.spend_permission as sp

    tx_hash = "0x" + "ab" * 32

    def _timeout(w3, h, *args, **kwargs):
        raise TimeoutError(f"no receipt for {h} after 5 retries: None")

    monkeypatch.setattr(sp, "wait_for_receipt", _timeout)
    with pytest.raises(SettlementNotConfirmed) as excinfo:
        _receipt_or_raise(None, tx_hash, "spend")
    assert isinstance(excinfo.value, PaymentError)
    assert excinfo.value.tx_hash == tx_hash
    assert "spend" in str(excinfo.value)
