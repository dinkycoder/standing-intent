"""pytest fixtures for the self-hosted x402 test seller.

`x402_seller` is a plain fixture (an unmarked fixture is not an integration
gate on its own): the CI smoke test in tests/test_payments_seller.py uses it to
assert the 402 shape only -- no signing, no settlement. Task 7 / Task 13 mark
*their* consuming tests `@pytest.mark.integration`.

`wire_real_x402_task` rewrites a `real_x402` task spec's vendor URLs to point at
a running seller instance.
"""

from __future__ import annotations

import contextlib
import socket
import threading

import pytest

from payments import constants
from payments.testing.seller import _silence_werkzeug, build_seller_app

# The seller's recipient. Deliberately NOT the buyer's own address: with a
# self-send, expected.payer == expected.pay_to and verify_settlement's
# transfer_from / transfer_to checks are both satisfied by the same address, so a
# swapped-direction log decode would go undetected in the one end-to-end test
# (I-6). Costs a fraction of a testnet USDC per manual integration run.
# Checksum-cased so it round-trips through eth_account / the x402 middleware.
_TEST_PAY_TO = "0x000000000000000000000000000000000000bEEF"

_READY_TIMEOUT_SECONDS = 5.0
_FACILITATOR_PROBE_TIMEOUT_SECONDS = 5.0


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_listening(port: int, timeout: float = _READY_TIMEOUT_SECONDS) -> None:
    """Block until 127.0.0.1:`port` accepts a TCP connection, or fail.

    A threaded Werkzeug server is not guaranteed to be up the instant the thread
    starts; poll instead so the fixture is deterministic.
    """
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"x402 test seller did not come up on port {port} within {timeout}s")


def _require_testnet_facilitator() -> None:
    """Skip (do not fail) when the x402 testnet facilitator handshake would fail.

    The middleware pulls the facilitator's `/supported` capability list on the
    first protected request to build the 402; if that call does not return 200
    the gated route 500s. Probe with the *same* client the middleware uses (a
    bare `urllib` GET is 403'd by x402.org on User-Agent) so the fixture yields
    only when a paid request could actually be validated. A CI smoke test must
    not go red on a third-party outage, and Task 7/13's integration tests --
    which could not settle anyway -- share this fixture.
    """
    from x402.http import FacilitatorConfig, HTTPFacilitatorClientSync

    client = HTTPFacilitatorClientSync(
        FacilitatorConfig(
            url=constants.FACILITATOR_TESTNET, timeout=_FACILITATOR_PROBE_TIMEOUT_SECONDS
        )
    )
    try:
        client.get_supported()
    except Exception as exc:  # noqa: BLE001 -- any failure here is a liveness skip, not a bug
        pytest.skip(f"x402 testnet facilitator handshake failed: {exc}")
    finally:
        client.close()


@pytest.fixture
def x402_seller():
    """Start the x402 test seller on a controllable server; yield its base URL.

    The seller pays to `_TEST_PAY_TO`, which is never the buyer wallet -- so the
    integration test's transfer_from / transfer_to reconciliation is real (I-6).
    """
    from werkzeug.serving import make_server

    _require_testnet_facilitator()

    pay_to = _TEST_PAY_TO

    _silence_werkzeug()
    port = _free_port()
    app = build_seller_app(pay_to)
    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _wait_until_listening(port)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def wire_real_x402_task(task, base_url):
    """Return a copy of `task` with each vendor `url` pointed at a live seller.

    The `real_x402` task specs (Task 13) carry `environment.kind == "real_x402"`
    and vendors with `url: null`; this points them at a running seller instance.

    The URL is `{base_url}/{category}?v={vendor_id}`: the seller routes on the
    path (`/weather-data`, `/news-data`) and ignores the query string, but the
    `?v=` segment keeps the URL unique per vendor so `RealX402Executor._url_to_id`
    does not collapse two same-category vendors onto one id (I-4). One URL must
    resolve to exactly one vendor_id.
    """
    data = task.model_dump()
    for vendor in data["environment"]["vendors"]:
        vendor["url"] = f"{base_url}/{vendor['category']}?v={vendor['vendor_id']}"
    return type(task).model_validate(data)
