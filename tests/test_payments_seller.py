"""Smoke test for the self-hosted x402 test seller.

CI-safe: it starts the Flask seller and asserts the 402 shape only. It never
signs a payment or settles on chain, so it needs no wallet key and no testnet
funds. It does require FACILITATOR_TESTNET to be reachable (the middleware pulls
its /supported list to build the 402) -- the same dependency
tests/test_payments_constants.py already has. NOT marked `integration`.
"""

import base64
import json

import requests

from payments.testing.fixtures import x402_seller  # noqa: F401


def test_seller_serves_a_402(x402_seller):
    r = requests.get(f"{x402_seller}/weather-data", timeout=15)
    assert r.status_code == 402
    header = r.headers.get("payment-required")
    assert header or "accepts" in r.json()
    if header:
        terms = json.loads(base64.b64decode(header))
        assert terms["accepts"][0]["scheme"] == "exact"
        assert terms["accepts"][0]["network"].endswith("84532")
