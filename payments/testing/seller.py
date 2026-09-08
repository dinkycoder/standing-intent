"""Self-hosted x402 test seller (Base Sepolia).

A deterministic local endpoint so the payment integration tests (Task 7) and the
harness `real_x402` test (Task 13) can run a real 402 -> sign -> settle -> verify
loop without depending on a third-party vendor being up.

`/weather-data` ($0.01) and `/news-data` ($0.02) are gated by the real
`x402[flask]` middleware, so verify + settle are forwarded to the configured
facilitator (`payments.constants.FACILITATOR_TESTNET`) exactly as a production
seller would. `/permit2-only` is a hand-built 402 whose single `accepts` entry
advertises a Permit2-only transfer method -- `payments.client.inspect_offer`
must classify it unsatisfiable. `/free` needs no payment.

There is no private key here: `pay_to` is a plain address passed in by the
caller (CLAUDE.md hard rule 1 -- this process never holds keys or funds).

The middleware's sync facilitator client needs `httpx` (it is not pulled by
`x402[flask]`); it is pinned in requirements.txt for this reason.
"""

from __future__ import annotations

import base64
import json
import logging

from flask import Flask, jsonify

from payments.constants import FACILITATOR_TESTNET, USDC_BASE_SEPOLIA

DEFAULT_NETWORK = "eip155:84532"  # CAIP-2, Base Sepolia (payments.constants.CHAIN_ID_BASE_SEPOLIA)

# category -> advertised price string the middleware understands ("$" => USDC)
_GATED_ROUTES = {"weather-data": "$0.01", "news-data": "$0.02"}


def _permit2_only_terms(pay_to: str, network: str) -> dict:
    """A v2 402 body advertising one Permit2-only exact-USDC offer.

    Shape mirrors docs/archive/probe/findings.md section 3. `inspect_offer`
    rejects it because `extra.assetTransferMethod != "transferWithAuthorization"`.
    """
    return {
        "x402Version": 2,
        "accepts": [
            {
                "scheme": "exact",
                "network": network,
                "asset": USDC_BASE_SEPOLIA,
                "amount": "30000",  # 0.03 USDC in 6-dp base units
                "payTo": pay_to,
                "resource": "/permit2-only",
                "description": "permit2-only feed (unsatisfiable by design)",
                "mimeType": "application/json",
                "maxTimeoutSeconds": 300,
                "extra": {"name": "USDC", "version": "2", "assetTransferMethod": "permit2"},
            }
        ],
    }


def build_seller_app(pay_to: str, *, network: str = DEFAULT_NETWORK) -> Flask:
    """A Flask app serving the gated + hand-built x402 routes for `pay_to`."""
    from x402.http import FacilitatorConfig, HTTPFacilitatorClientSync, PaymentOption
    from x402.http.middleware.flask import payment_middleware
    from x402.http.types import RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.server import x402ResourceServerSync

    app = Flask(__name__)

    facilitator = HTTPFacilitatorClientSync(FacilitatorConfig(url=FACILITATOR_TESTNET))
    server = x402ResourceServerSync(facilitator)
    server.register(network, ExactEvmServerScheme())

    routes = {
        f"GET /{category}": RouteConfig(
            accepts=[
                PaymentOption(scheme="exact", pay_to=pay_to, price=price, network=network)
            ],
            mime_type="application/json",
            description=f"{category} feed",
        )
        for category, price in _GATED_ROUTES.items()
    }
    # sync_facilitator_on_start=True (default): the first protected request pulls
    # the facilitator's /supported list before it can build a 402. That is one
    # network GET to FACILITATOR_TESTNET -- the same dependency tests/
    # test_payments_constants.py already relies on.
    payment_middleware(app, routes=routes, server=server)

    @app.get("/weather-data")
    def weather_data():
        return jsonify({"feed": "weather-data", "temp_c": 21, "paid": True})

    @app.get("/news-data")
    def news_data():
        return jsonify({"feed": "news-data", "headline": "all quiet on Base", "paid": True})

    @app.get("/permit2-only")
    def permit2_only():
        terms = _permit2_only_terms(pay_to, network)
        body = json.dumps(terms)
        header = base64.b64encode(body.encode()).decode()
        return body, 402, {"Content-Type": "application/json", "PAYMENT-REQUIRED": header}

    @app.get("/free")
    def free():
        return jsonify({"feed": "free", "paid": False})

    return app


def _silence_werkzeug() -> None:
    """Quiet the dev-server request log and Flask's startup banner.

    The banner is a bare ``print`` (not a log record), so the logger level alone
    does not remove it. This monkeypatches ``flask.cli.show_server_banner``
    process-wide with no restore -- acceptable in a test-only fixture helper.
    """
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    import flask.cli

    flask.cli.show_server_banner = lambda *a, **k: None  # type: ignore[assignment]
