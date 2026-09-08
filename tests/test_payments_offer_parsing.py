import base64
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from payments.client import Offer, PaymentQuote, inspect_offer, parse_terms
from payments.errors import EndpointUnreachable, UnexpectedStatus

DATA = Path("tests/data")

_USDC_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


def _good_entry(amount="1000"):
    return {
        "scheme": "exact",
        "network": "eip155:84532",
        "asset": _USDC_SEPOLIA,
        "amount": amount,
        "payTo": "0x000000000000000000000000000000000000dEaD",
        "maxTimeoutSeconds": 300,
        "extra": {"name": "USDC", "version": "2"},
    }


def _terms(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def test_ottoai_first_offer_is_satisfiable_and_priced():
    q = parse_terms(_terms("offer_ottoai.json"), "https://x402.ottoai.services/crypto-news")
    assert isinstance(q, PaymentQuote) and q.x402_version == 2
    o = q.best_satisfiable
    assert o is not None
    assert o.scheme == "exact" and o.chain_id == 8453
    assert o.asset.lower() == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    assert o.amount == Decimal("0.001")            # "1000" atomic / 1e6
    assert o.pay_to == "0x0E84dDEdAaE6A779c462C22a59F301EC31B6b808"
    assert o.transfer_method == "transferWithAuthorization"


def test_ottoai_permit2_entry_is_unsatisfiable():
    q = parse_terms(_terms("offer_ottoai.json"), "u")
    permit2 = [o for o in q.offers if o.transfer_method == "permit2"]
    assert permit2 and all(o.satisfiable is False for o in permit2)
    assert "permit2" in permit2[0].unsatisfiable_reason


def test_ottoai_solana_entry_is_unsatisfiable():
    q = parse_terms(_terms("offer_ottoai.json"), "u")
    sol = [o for o in q.offers if o.chain_id is None]
    assert sol and all(o.satisfiable is False for o in sol)


def test_permit2_only_has_no_satisfiable_offer():
    q = parse_terms(_terms("offer_permit2_only.json"), "u")
    assert q.best_satisfiable is None
    assert all(o.satisfiable is False for o in q.offers)


def test_v1_terms_parse_and_price():
    q = parse_terms(_terms("offer_v1.json"), "u")
    assert q.x402_version == 1
    assert q.best_satisfiable is not None
    assert q.best_satisfiable.amount == Decimal("0.01")


def test_raw_terms_kept_verbatim():
    raw = _terms("offer_ottoai.json")
    q = parse_terms(raw, "u")
    assert q.raw_terms == raw


def test_malformed_amount_degrades_offer_not_call():
    raw = {"x402Version": 2, "accepts": [{**_good_entry(), "amount": "$5"}]}
    q = parse_terms(raw, "u")
    assert isinstance(q, PaymentQuote)
    assert len(q.offers) == 1
    bad = q.offers[0]
    assert bad.satisfiable is False
    assert bad.amount == Decimal(0)
    assert "amount" in bad.unsatisfiable_reason
    assert q.best_satisfiable is None


def test_negative_amount_is_unsatisfiable_and_not_cheapest():
    # I-7: an untrusted vendor offer with a negative price parses fine
    # (Decimal("-5000") / 1e6) so nothing else rejects it, and min(..., key=amount)
    # would pick it over every legitimate offer.
    raw = {
        "x402Version": 2,
        "accepts": [
            {**_good_entry(), "amount": "-5000"},
            _good_entry(amount="2000"),
        ],
    }
    q = parse_terms(raw, "u")
    assert q.offers[0].satisfiable is False
    assert "negative" in q.offers[0].unsatisfiable_reason
    assert q.best_satisfiable is q.offers[1]


def test_negative_amount_only_offer_leaves_no_satisfiable():
    raw = {"x402Version": 2, "accepts": [{**_good_entry(), "amount": "-1"}]}
    q = parse_terms(raw, "u")
    assert q.best_satisfiable is None
    assert q.offers[0].satisfiable is False and "negative" in q.offers[0].unsatisfiable_reason


@pytest.mark.parametrize("bad", ["v2", {"nested": 1}, [1, 2], None])
def test_non_numeric_x402_version_falls_back_to_1(bad):
    raw = {"x402Version": bad, "accepts": [_good_entry(amount="2000")]}
    assert parse_terms(raw, "u").x402_version == 1


@pytest.mark.parametrize("bad", ["soon", {"nested": 1}, [1], None])
def test_non_numeric_max_timeout_falls_back_to_0(bad):
    raw = {"x402Version": 2, "accepts": [{**_good_entry(amount="2000"), "maxTimeoutSeconds": bad}]}
    q = parse_terms(raw, "u")
    assert q.offers[0].max_timeout_seconds == 0
    assert q.offers[0].satisfiable is True   # a junk timeout must not sink an otherwise-good offer


@pytest.mark.parametrize("entry_amount", [None, "MISSING"])
def test_missing_or_none_amount_degrades_offer(entry_amount):
    entry = _good_entry()
    if entry_amount == "MISSING":
        entry.pop("amount")
    else:
        entry["amount"] = None
    q = parse_terms({"x402Version": 2, "accepts": [entry]}, "u")
    bad = q.offers[0]
    # A dropped "amount" key defaults to "0" (satisfiable, free); an explicit
    # null is unparseable and degrades the offer.
    if entry_amount is None:
        assert bad.satisfiable is False and "amount" in bad.unsatisfiable_reason
    else:
        assert bad.amount == Decimal("0")


def test_raw_terms_is_deep_copied_not_a_live_view():
    raw = {"x402Version": 2, "accepts": [_good_entry(amount="2000")]}
    q = parse_terms(raw, "u")
    raw["accepts"][0]["amount"] = "999999999"
    raw["x402Version"] = 99
    assert q.raw_terms["accepts"][0]["amount"] == "2000"
    assert q.raw_terms["x402Version"] == 2


def test_malformed_amount_does_not_poison_other_offers():
    raw = {
        "x402Version": 2,
        "accepts": [
            {**_good_entry(), "amount": "free"},
            _good_entry(amount="2000"),
        ],
    }
    q = parse_terms(raw, "u")
    assert q.offers[0].satisfiable is False
    assert "amount" in q.offers[0].unsatisfiable_reason
    assert q.best_satisfiable is q.offers[1]
    assert q.best_satisfiable.amount == Decimal("0.002")


# --- inspect_offer: HTTP wrapper around parse_terms (offline, mocked network) ---

_URL = "https://x402.ottoai.services/crypto-news"


class _FakeResponse:
    def __init__(self, *, status_code=402, headers=None, json_body=None,
                 json_raises=False, content=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self._json_body = json_body
        self._json_raises = json_raises
        self.content = content

    def json(self):
        if self._json_raises:
            raise ValueError("no JSON body")
        return self._json_body


def test_inspect_offer_header_path_matches_parse_terms():
    terms = _terms("offer_ottoai.json")
    header = base64.b64encode(json.dumps(terms).encode()).decode()
    resp = _FakeResponse(status_code=402, headers={"payment-required": header},
                         json_raises=True)
    with patch("payments.client.requests.get", return_value=resp):
        q = inspect_offer(_URL)
    expected = parse_terms(terms, _URL)
    assert q == expected
    assert q.x402_version == expected.x402_version == 2
    assert q.best_satisfiable == expected.best_satisfiable
    assert q.best_satisfiable is not None


def test_inspect_offer_body_fallback_matches_parse_terms():
    terms = _terms("offer_ottoai.json")
    resp = _FakeResponse(status_code=402, headers={}, json_body=terms)
    with patch("payments.client.requests.get", return_value=resp):
        q = inspect_offer(_URL)
    expected = parse_terms(terms, _URL)
    assert q == expected
    assert q.x402_version == expected.x402_version == 2
    assert q.best_satisfiable == expected.best_satisfiable


def test_inspect_offer_connection_failure_raises_endpoint_unreachable():
    with patch("payments.client.requests.get",
               side_effect=requests.RequestException("connection refused")):
        with pytest.raises(EndpointUnreachable):
            inspect_offer(_URL)


def test_inspect_offer_unexpected_status_raises():
    resp = _FakeResponse(status_code=404, headers={}, json_raises=True)
    with patch("payments.client.requests.get", return_value=resp):
        with pytest.raises(UnexpectedStatus):
            inspect_offer(_URL)


def test_inspect_offer_malformed_header_degrades_to_body():
    terms = _terms("offer_ottoai.json")
    resp = _FakeResponse(status_code=402,
                         headers={"payment-required": "!!!not-base64!!!"},
                         json_body=terms)
    with patch("payments.client.requests.get", return_value=resp):
        q = inspect_offer(_URL)
    assert q == parse_terms(terms, _URL)
    assert q.best_satisfiable is not None


def test_inspect_offer_non_object_json_header_degrades_to_body():
    # Valid base64 of valid JSON that is not an object (an array): decodes fine
    # but is not payment terms -> must fall through to the body, not raise.
    terms = _terms("offer_ottoai.json")
    header = base64.b64encode(json.dumps([1, 2, 3]).encode()).decode()
    resp = _FakeResponse(status_code=402, headers={"payment-required": header},
                         json_body=terms)
    with patch("payments.client.requests.get", return_value=resp):
        q = inspect_offer(_URL)
    assert q == parse_terms(terms, _URL)
    assert q.best_satisfiable is not None


def test_inspect_offer_non_object_json_header_no_usable_body():
    # Non-object header AND no usable body: the header must not blow up parse_terms.
    # Non-402 status -> UnexpectedStatus (still inside the PaymentError taxonomy).
    header = base64.b64encode(json.dumps([1, 2, 3]).encode()).decode()
    resp404 = _FakeResponse(status_code=404, headers={"payment-required": header},
                            json_body=[1, 2, 3])
    with patch("payments.client.requests.get", return_value=resp404):
        with pytest.raises(UnexpectedStatus):
            inspect_offer(_URL)

    # 402 with nothing parseable -> the pre-existing Task-4 branch returns an
    # empty PaymentQuote (still "returns a PaymentQuote", never a raw exception).
    resp402 = _FakeResponse(status_code=402, headers={"payment-required": header},
                            json_raises=True)
    with patch("payments.client.requests.get", return_value=resp402):
        q = inspect_offer(_URL)
    assert isinstance(q, PaymentQuote) and q.best_satisfiable is None
