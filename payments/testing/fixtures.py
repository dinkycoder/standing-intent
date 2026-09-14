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
import os
import socket
import threading
from decimal import Decimal

import pytest

from payments import constants
from payments.constants import CHAIN_ID_BASE_SEPOLIA
from payments.spend_permission import SmartWalletAccount, provision_smart_wallet_account
from payments.testing.seller import _silence_werkzeug, build_seller_app
from payments.wallet import LocalWallet, _usdc_balance_of

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
        server.server_close()   # release the listening socket, not just the serve loop


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


_ACCOUNT_KEY = os.environ.get("SPEND_PERMISSION_ACCOUNT_KEY")

# Every Spend Permission integration test provisions the Smart Wallet at this
# nonce, so ONE funded address unblocks the whole suite. Permissions are
# distinguished by salt (see SpendPermission.salt), not by using a different
# wallet per test -- which is what earlier revisions did, at the cost of
# needing three separately funded wallets.
SPEND_PERMISSION_ACCOUNT_NONCE = 0


def skip_unless_funded(address: str, minimum: Decimal = Decimal("1")) -> None:
    """Skip (never fail) when `address` holds less than `minimum` test USDC.

    Checks the SMART WALLET, which is what SpendPermissionManager.spend()
    debits -- not its owner EOA, which only ever pays gas. An empty wallet is
    an environment fact, not a defect, and this repo's convention is to skip
    on those with a message that says exactly what to do (see
    tests/test_payments_constants.py). A real revert still fails loudly: the
    threshold is far below any single test's spend, so this cannot mask an
    under-funded-by-a-little failure.
    """
    try:
        balance = _usdc_balance_of(address, CHAIN_ID_BASE_SEPOLIA)
    except ConnectionError as exc:  # RPC outage is not a funding verdict
        pytest.skip(f"cannot read {address}'s USDC balance: {exc!r}")
    if balance < minimum:
        pytest.skip(
            f"fund {address} (the Smart Wallet, not its owner) with Base Sepolia test "
            f"USDC before running this suite -- it holds {balance}"
        )


@pytest.fixture
def spend_permission_account() -> SmartWalletAccount:
    """A funded Coinbase Smart Wallet on Base Sepolia, SpendPermissionManager
    already an owner -- see docs/superpowers/specs/2026-09-13-spend-permission
    -account-design.md. Requires SPEND_PERMISSION_ACCOUNT_KEY (a throwaway
    owner key, never a real user's) funded with a little Sepolia ETH for gas
    and enough test USDC to cover the fixture's 0.05 USDC/day cap."""
    if not _ACCOUNT_KEY:
        pytest.skip("SPEND_PERMISSION_ACCOUNT_KEY unset")
    owner = LocalWallet(_ACCOUNT_KEY)
    account = provision_smart_wallet_account(
        owner, CHAIN_ID_BASE_SEPOLIA, nonce=SPEND_PERMISSION_ACCOUNT_NONCE
    )
    # Check the SMART WALLET's balance, not the owner EOA's: spend() pulls USDC
    # from permission.account -- the wallet -- and the owner EOA only ever pays
    # gas. Reading owner.usdc_balance() here made the guard skip (or, worse,
    # pass) on a balance that has nothing to do with whether the spend can
    # settle, while the skip message named the wallet address.
    skip_unless_funded(account.address)
    return account
