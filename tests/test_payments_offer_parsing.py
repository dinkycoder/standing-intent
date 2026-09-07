import json
from decimal import Decimal
from pathlib import Path

import pytest

from payments.client import Offer, PaymentQuote, parse_terms

DATA = Path("tests/data")


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
