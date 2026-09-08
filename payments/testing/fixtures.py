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

import pytest

from payments.testing.seller import run_seller

# Overridden when X402_WALLET_KEY is set -- see x402_seller below. Checksum-cased
# so it round-trips through eth_account / the x402 middleware unchanged.
_TEST_PAY_TO = "0x000000000000000000000000000000000000bEEF"

_READY_TIMEOUT_SECONDS = 5.0


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_listening(port: int, timeout: float = _READY_TIMEOUT_SECONDS) -> None:
    """Block until 127.0.0.1:`port` accepts a TCP connection, or fail.

    A threaded Werkzeug dev server is not guaranteed to be up after a fixed
    sleep; poll instead so the fixture is deterministic.
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


@pytest.fixture
def x402_seller():
    """Start the x402 test seller in a daemon thread; yield its base URL."""
    import os

    pay_to = _TEST_PAY_TO
    key = os.environ.get("X402_WALLET_KEY")
    if key:
        from eth_account import Account

        pay_to = Account.from_key(key).address

    port = _free_port()
    run_seller(pay_to, port)
    _wait_until_listening(port)
    yield f"http://127.0.0.1:{port}"
    # daemon thread dies with the process; no explicit stop needed


def wire_real_x402_task(task, base_url):
    """Return a copy of `task` with each vendor `url` set to `{base_url}/{category}`.

    The `real_x402` task specs (Task 13) carry `environment.kind == "real_x402"`
    and vendors with `url: null`; this points them at a live seller instance.
    """
    data = task.model_dump()
    for vendor in data["environment"]["vendors"]:
        vendor["url"] = f"{base_url}/{vendor['category']}"
    return type(task).model_validate(data)
