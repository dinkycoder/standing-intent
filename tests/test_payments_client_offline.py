"""Deterministic offline coverage of pay() past the pre-flight.

The live x402 SDK call sequence in pay() -- x402ClientSync, set_spend_controls,
register_exact_evm_client, x402HTTPClientSync, x402_requests,
get_payment_settle_response, .success, .transaction -- otherwise has ZERO
executed coverage in any tier that runs in CI (test_payments_errors.py stops at
the pre-flight; test_payments_seller.py exercises only the server half; every
buyer-path integration test skips without X402_WALLET_KEY).

This file monkeypatches the requests session and verify_settlement, and drives
pay() through the real SDK construction. No wallet key, no network, no chain --
it runs in the default pytest selection.
"""

import base64
import contextlib
import json
from decimal import Decimal

import pytest
from eth_account import Account

from payments import client
from payments.client import Offer, PaymentQuote
from payments.errors import SettlementRejected
from payments.settlement import VerifiedSettlement
from payments.wallet import LocalWallet

_USDC_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
# The tx hash / network are the real Week-1 mainnet settlement recorded in
# docs/archive/probe/findings.md (probe_03); findings.md records the decoded
# JSON, not a verbatim header, so the base64 wrapper here is assembled, not
# copied. get_payment_settle_response only needs success / transaction / network.
_REAL_TX = "0x44cb0f1e7bd5794e1d57ff10974fa1e544a43bd90796922e14d6a7e1cd43fcc3"
_SELLER_PAYTO = "0x0E84dDEdAaE6A779c462C22a59F301EC31B6b808"


class _OfflineWallet:
    """Real EthAccountSigner (so register_exact_evm_client runs for real) with a
    canned balance and no network."""

    def __init__(self, balance="100"):
        self._inner = LocalWallet(Account.create().key.hex())
        self._balance = Decimal(balance)

    @property
    def address(self):
        return self._inner.address

    def x402_signer(self):
        return self._inner.x402_signer()

    def usdc_balance(self, network):
        return self._balance


def _quote(amount="0.002", pay_to="0xQUOTEonly000000000000000000000000000000"):
    # amount / pay_to deliberately DIFFER from the verified values below, so the
    # test can prove the outcome is populated from `verified`, not the quote.
    o = Offer(scheme="exact", network="eip155:84532", chain_id=84532,
              asset=_USDC_SEPOLIA, amount=Decimal(amount), pay_to=pay_to,
              max_timeout_seconds=300, transfer_method="transferWithAuthorization",
              satisfiable=True, unsatisfiable_reason=None)
    return PaymentQuote(url="u", x402_version=2, offers=(o,), best_satisfiable=o,
                        raw_terms={})


class _Resp:
    def __init__(self, status_code=200, headers=None, json_body=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_body = json_body if json_body is not None else {"feed": "weather", "paid": True}
        self.content = b"body"

    def json(self):
        return self._json_body


class _Session:
    def __init__(self, resp):
        self._resp = resp

    def get(self, url, timeout=None):
        return self._resp


def _fake_x402_requests(resp):
    @contextlib.contextmanager
    def _cm(_x_client):
        yield _Session(resp)

    return _cm


def _payment_response_header(*, success=True, tx=_REAL_TX, network="eip155:84532"):
    payload = {"success": success, "errorReason": None, "transaction": tx, "network": network}
    return base64.b64encode(json.dumps(payload).encode()).decode()


def _verified(**over):
    kw = dict(
        tx_hash=_REAL_TX, network=84532, block_number=50997392, status_ok=True,
        transfer_from="0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0",
        transfer_to=_SELLER_PAYTO, amount_atomic=1000, amount_usdc=Decimal("0.001"),
        submitted_by="0xe74817f4cdc15844314812b2271276e64e890fae",
        payer_paid_gas=False, matches_expected=True, mismatch=None,
    )
    kw.update(over)
    return VerifiedSettlement(**kw)


def _patch(monkeypatch, *, resp, verify):
    monkeypatch.setattr(client, "inspect_offer", lambda *a, **k: _quote())
    monkeypatch.setattr("x402.http.clients.x402_requests", _fake_x402_requests(resp),
                        raising=False)
    monkeypatch.setattr(client, "verify_settlement", verify)


def test_pay_returns_outcome_populated_from_verified_settlement(monkeypatch):
    resp = _Resp(200, {"PAYMENT-RESPONSE": _payment_response_header()})
    _patch(monkeypatch, resp=resp, verify=lambda *a, **k: _verified())

    outcome = client.pay("u", _OfflineWallet(), max_amount=Decimal("0.05"),
                         network_allowlist=(84532,))

    assert outcome.paid is True
    assert outcome.tx_hash == _REAL_TX
    # amount_paid and pay_to come from the on-chain Transfer log (verified),
    # NOT the SDK's claim and NOT the pre-flight quote (0.002 / 0xQUOTEonly...).
    assert outcome.amount_paid == Decimal("0.001")
    assert outcome.pay_to == _SELLER_PAYTO
    assert outcome.verified.block_number == 50997392
    assert outcome.resource == {"feed": "weather", "paid": True}


def test_pay_raises_settlement_rejected_when_success_false(monkeypatch):
    resp = _Resp(200, {"PAYMENT-RESPONSE": _payment_response_header(success=False)})

    def _should_not_run(*a, **k):
        raise AssertionError("verify_settlement must not be reached on success=false")

    _patch(monkeypatch, resp=resp, verify=_should_not_run)
    with pytest.raises(SettlementRejected):
        client.pay("u", _OfflineWallet(), max_amount=Decimal("0.05"),
                   network_allowlist=(84532,))


def test_pay_raises_settlement_rejected_when_header_absent(monkeypatch):
    # No PAYMENT-RESPONSE header at all -> get_payment_settle_response raises
    # ValueError -> the taxonomy branch for a 200 with no settlement proof.
    resp = _Resp(200, headers={})

    def _should_not_run(*a, **k):
        raise AssertionError("verify_settlement must not be reached with no header")

    _patch(monkeypatch, resp=resp, verify=_should_not_run)
    with pytest.raises(SettlementRejected):
        client.pay("u", _OfflineWallet(), max_amount=Decimal("0.05"),
                   network_allowlist=(84532,))
