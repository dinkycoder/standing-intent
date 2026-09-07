from decimal import Decimal
from unittest.mock import patch

import pytest

from payments import client
from payments.client import Offer, PaymentQuote
from payments.errors import (
    InsufficientBalance, NetworkNotAllowed, NoSatisfiableOffer, OfferOverCap,
)


class _FakeWallet:
    address = "0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0"

    def __init__(self, balance):
        self._balance = Decimal(balance)

    def x402_signer(self):
        raise AssertionError("pre-flight must reject before signing")

    def usdc_balance(self, network):
        return self._balance


def _quote(*, satisfiable=True, amount="0.01", chain_id=84532):
    o = Offer(scheme="exact", network=f"eip155:{chain_id}", chain_id=chain_id,
              asset="0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount=Decimal(amount),
              pay_to="0xdead", max_timeout_seconds=300,
              transfer_method="transferWithAuthorization",
              satisfiable=satisfiable, unsatisfiable_reason=None if satisfiable else "nope")
    return PaymentQuote(url="u", x402_version=2, offers=(o,),
                        best_satisfiable=o if satisfiable else None, raw_terms={})


def test_no_satisfiable_offer_raises():
    with patch.object(client, "inspect_offer", return_value=_quote(satisfiable=False)):
        with pytest.raises(NoSatisfiableOffer):
            client.pay("u", _FakeWallet("100"), max_amount=Decimal("1"))


def test_over_cap_raises_with_data():
    with patch.object(client, "inspect_offer", return_value=_quote(amount="5")):
        with pytest.raises(OfferOverCap) as ei:
            client.pay("u", _FakeWallet("100"), max_amount=Decimal("1"))
    assert ei.value.amount == Decimal("5") and ei.value.cap == Decimal("1")


def test_network_not_allowed_raises():
    with patch.object(client, "inspect_offer", return_value=_quote(chain_id=8453)):
        with pytest.raises(NetworkNotAllowed):
            client.pay("u", _FakeWallet("100"), max_amount=Decimal("1"),
                       network_allowlist=(84532,))


def test_insufficient_balance_raises():
    with patch.object(client, "inspect_offer", return_value=_quote(amount="0.5")):
        with pytest.raises(InsufficientBalance):
            client.pay("u", _FakeWallet("0.1"), max_amount=Decimal("1"))
