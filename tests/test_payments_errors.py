import base64
import contextlib
import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from eth_account import Account

from payments import client
from payments.client import Offer, PaymentQuote
from payments.errors import (
    BalanceCheckUnavailable, InsufficientBalance, NetworkNotAllowed, NoSatisfiableOffer,
    OfferOverCap, SettlementMismatch, SettlementNotConfirmed, SettlementRejected,
    UnexpectedStatus,
)
from payments.settlement import VerifiedSettlement
from payments.wallet import LocalWallet


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


# --- money-moved / taxonomy paths past the pre-flight (I-1, I-2, M-1) ----------
#
# These drive pay() through the real x402 SDK construction (x402ClientSync,
# set_spend_controls, register_exact_evm_client, x402HTTPClientSync,
# get_payment_settle_response) with a fake requests session and a fake
# verify_settlement -- fully offline, no wallet key, no chain.

_USDC_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
_TX = "0x" + "ab" * 32


class _RealishWallet:
    """A real EthAccountSigner (so register_exact_evm_client is exercised) with a
    canned balance and no network."""

    def __init__(self, balance="100", *, balance_raises=False):
        self._inner = LocalWallet(Account.create().key.hex())
        self._balance = Decimal(balance)
        self._balance_raises = balance_raises

    @property
    def address(self):
        return self._inner.address

    def x402_signer(self):
        return self._inner.x402_signer()

    def usdc_balance(self, network):
        if self._balance_raises:
            raise ConnectionError(f"no RPC reachable for chain {network}")
        return self._balance


def _offer(amount="0.01", chain_id=84532,
           pay_to="0x000000000000000000000000000000000000dEaD"):
    return Offer(scheme="exact", network=f"eip155:{chain_id}", chain_id=chain_id,
                 asset=_USDC_SEPOLIA, amount=Decimal(amount), pay_to=pay_to,
                 max_timeout_seconds=300, transfer_method="transferWithAuthorization",
                 satisfiable=True, unsatisfiable_reason=None)


def _quote_for(offer):
    return PaymentQuote(url="u", x402_version=2, offers=(offer,),
                        best_satisfiable=offer, raw_terms={})


class _Resp:
    def __init__(self, status_code=200, headers=None, json_body=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_body = json_body
        self.content = b""

    def json(self):
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


class _Session:
    def __init__(self, resp, exc):
        self._resp = resp
        self._exc = exc

    def get(self, url, timeout=None):
        if self._exc is not None:
            raise self._exc
        return self._resp


def _fake_x402_requests(resp, exc):
    @contextlib.contextmanager
    def _cm(_x_client):
        yield _Session(resp, exc)

    return _cm


def _settle_header(*, success=True, tx=_TX, network="eip155:84532"):
    return base64.b64encode(
        json.dumps({"success": success, "transaction": tx, "network": network}).encode()
    ).decode()


def _verified(*, matches=True, mismatch=None):
    return VerifiedSettlement(
        tx_hash=_TX, network=84532, block_number=1, status_ok=True,
        transfer_from="0x000000000000000000000000000000000000bEEF",
        transfer_to="0x000000000000000000000000000000000000dEaD",
        amount_atomic=10000, amount_usdc=Decimal("0.01"),
        submitted_by="0x00000000000000000000000000000000000Re1ay",
        payer_paid_gas=False, matches_expected=matches, mismatch=mismatch)


def _drive(monkeypatch, *, wallet, resp=None, session_exc=None, verify=None,
           offer=None, max_amount="1"):
    offer = offer or _offer()
    monkeypatch.setattr(client, "inspect_offer", lambda *a, **k: _quote_for(offer))
    monkeypatch.setattr("x402.http.clients.x402_requests",
                        _fake_x402_requests(resp, session_exc), raising=False)
    if verify is not None:
        monkeypatch.setattr(client, "verify_settlement", verify)
    return client.pay("u", wallet, max_amount=Decimal(max_amount),
                      network_allowlist=(84532,))


def test_preflight_balance_connection_error_is_wrapped(monkeypatch):
    with pytest.raises(BalanceCheckUnavailable):
        _drive(monkeypatch, wallet=_RealishWallet(balance_raises=True))


def test_seller_reprice_raises_no_satisfiable_offer(monkeypatch):
    from x402 import NoMatchingRequirementsError

    with pytest.raises(NoSatisfiableOffer):
        _drive(monkeypatch, wallet=_RealishWallet(),
               session_exc=NoMatchingRequirementsError("re-priced above cap"))


def test_verify_connection_error_becomes_not_confirmed_with_hash(monkeypatch):
    def _boom(*a, **k):
        raise ConnectionError("every RPC down")

    resp = _Resp(200, {"PAYMENT-RESPONSE": _settle_header()})
    with pytest.raises(SettlementNotConfirmed) as ei:
        _drive(monkeypatch, wallet=_RealishWallet(), resp=resp, verify=_boom)
    assert ei.value.tx_hash == _TX


def test_settlement_mismatch_carries_hash_and_verified(monkeypatch):
    v = _verified(matches=False, mismatch="amount 5 atomic != expected 10000")
    resp = _Resp(200, {"PAYMENT-RESPONSE": _settle_header()})
    with pytest.raises(SettlementMismatch) as ei:
        _drive(monkeypatch, wallet=_RealishWallet(), resp=resp,
               verify=lambda *a, **k: v)
    assert ei.value.tx_hash == _TX
    assert ei.value.verified is v


def test_settled_then_non_200_delivery_surfaces_hash(monkeypatch):
    resp = _Resp(500, {"PAYMENT-RESPONSE": _settle_header()})
    with pytest.raises(SettlementRejected) as ei:
        _drive(monkeypatch, wallet=_RealishWallet(), resp=resp,
               verify=lambda *a, **k: _verified())
    assert ei.value.tx_hash == _TX


def test_402_after_retry_is_settlement_rejected_not_unexpected_status(monkeypatch):
    resp = _Resp(402, {})  # no PAYMENT-RESPONSE, still 402 after the SDK retry
    with pytest.raises(SettlementRejected):
        _drive(monkeypatch, wallet=_RealishWallet(), resp=resp)


def test_non_402_non_200_without_settlement_is_unexpected_status(monkeypatch):
    resp = _Resp(503, {})
    with pytest.raises(UnexpectedStatus):
        _drive(monkeypatch, wallet=_RealishWallet(), resp=resp)


def test_spend_control_authorizes_offer_amount_as_plain_decimal(monkeypatch):
    # I-2: the SDK spend control is set to the agreed price, not max_amount.
    # M-1: it must be a plain decimal string, not exponent form.
    from x402.schemas.helpers import parse_money

    captured = {}

    class _CaptureClient:
        def set_spend_controls(self, controls):
            captured["controls"] = controls
            raise RuntimeError("stop here -- pre-SDK-call assertion only")

    monkeypatch.setattr(client, "inspect_offer",
                        lambda *a, **k: _quote_for(_offer(amount="0.01")))
    monkeypatch.setattr("x402.x402ClientSync", lambda *a, **k: _CaptureClient())
    with pytest.raises(RuntimeError, match="stop here"):
        client.pay("u", _RealishWallet(), max_amount=Decimal("4.99"),
                   network_allowlist=(84532,))
    got = captured["controls"]["max_amount_per_payment"]
    assert got == "$0.01"                       # the agreed price, not $4.99
    assert "E" not in got and "e" not in got    # plain decimal, not exponent form
    assert parse_money(got)["amount"] == "0.01"


def test_spend_cap_exceeded_carries_value_and_allowance():
    from payments.errors import SpendCapExceeded
    err = SpendCapExceeded(Decimal("0.06"), Decimal("0.05"))
    assert err.value == Decimal("0.06")
    assert err.allowance == Decimal("0.05")
    assert "0.06" in str(err) and "0.05" in str(err)


def test_spend_permission_unauthorized_is_a_payment_error():
    from payments.errors import PaymentError, SpendPermissionUnauthorized
    assert issubclass(SpendPermissionUnauthorized, PaymentError)
