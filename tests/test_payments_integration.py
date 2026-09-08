import os
from decimal import Decimal

import pytest

from payments.client import pay
from payments.errors import NoSatisfiableOffer, UnexpectedStatus
from payments.settlement import ExpectedSettlement, verify_settlement
from payments.wallet import LocalWallet
from payments.testing.fixtures import x402_seller  # noqa: F401

pytestmark = pytest.mark.integration

_KEY = os.environ.get("X402_WALLET_KEY")
skip_no_key = pytest.mark.skipif(not _KEY, reason="X402_WALLET_KEY unset")


@skip_no_key
def test_pay_end_to_end_on_sepolia(x402_seller):
    wallet = LocalWallet.from_env()
    outcome = pay(f"{x402_seller}/weather-data", wallet,
                  max_amount=Decimal("0.05"), network_allowlist=(84532,))
    assert outcome.paid is True
    assert outcome.amount_paid == Decimal("0.01")
    assert outcome.tx_hash.startswith("0x")
    # independent re-verification
    v = verify_settlement(outcome.tx_hash,
                          ExpectedSettlement(wallet.address, outcome.pay_to,
                                             outcome.offer.asset, Decimal("0.01")),
                          84532)
    assert v.matches_expected is True


@skip_no_key
def test_permit2_route_has_no_satisfiable_offer(x402_seller):
    with pytest.raises(NoSatisfiableOffer):
        pay(f"{x402_seller}/permit2-only", LocalWallet.from_env(),
            max_amount=Decimal("1"), network_allowlist=(84532,))


@skip_no_key
def test_missing_route_raises_unexpected_status(x402_seller):
    with pytest.raises(UnexpectedStatus):
        pay(f"{x402_seller}/does-not-exist", LocalWallet.from_env(),
            max_amount=Decimal("1"), network_allowlist=(84532,))
