"""Week 4 -- the Base Spend Permission cap and revocation, on chain.

Written before `payments/spend_permission.py` exists (CLAUDE.md rule 3: no
capability before a failing eval). Running this file today fails at
collection with `ModuleNotFoundError` -- that failure IS the spec, not a
bug in the test. The API imported below is a design proposal driven by the
deployed contract's real interface (src/SpendPermissionManager.sol, pinned
via SPEND_PERMISSION_MANAGER / SPEND_PERMISSION_TYPE_STRING in
payments/constants.py, verified on-chain in tests/test_payments_constants.py)
-- Week 4 is free to reshape names as long as these three terminal-state
assertions hold once it's built.

Open design question this file does NOT resolve: the contract adds
SpendPermissionManager as an *owner* of a Coinbase Smart Wallet (ERC-4337) --
the `account` side of a permission cannot be a plain EOA like the existing
`LocalWallet` used for x402 payments (payments/wallet.py). Provisioning a
real or counterfactual Smart Wallet for `spend_permission_account` below is
Week-4 implementation work, not settled here.

Terminal-state grading (CLAUDE.md rule 4): each test asserts the actual
on-chain outcome (a specific revert reason, a real settlement), not that
some client-side function was merely called.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from payments.errors import SpendCapExceeded, SpendPermissionUnauthorized
from payments.spend_permission import (
    SpendPermission,
    register_spend_permission,
    revoke_spend_permission,
    sign_spend_permission,
    spend,
)
from payments.wallet import LocalWallet

pytestmark = pytest.mark.integration

_SPENDER_KEY = os.environ.get("X402_WALLET_KEY")
# A Coinbase Smart Wallet owner key, distinct from the spender EOA above --
# see the module docstring. Not read anywhere else in payments/ yet.
_ACCOUNT_KEY = os.environ.get("SPEND_PERMISSION_ACCOUNT_KEY")
skip_no_keys = pytest.mark.skipif(
    not (_SPENDER_KEY and _ACCOUNT_KEY),
    reason="X402_WALLET_KEY and/or SPEND_PERMISSION_ACCOUNT_KEY unset",
)

_CAP_USDC = Decimal("0.05")


@pytest.fixture
def signed_permission(spend_permission_account):
    """A SpendPermission capped at 0.05 USDC/day, signed and registered on
    Base Sepolia. `spend_permission_account` (payments/testing/fixtures.py,
    not yet written) must yield a funded Coinbase Smart Wallet -- the
    `account` -- distinct from the spender wallet below."""
    account = spend_permission_account
    spender = LocalWallet.from_env()
    permission = SpendPermission(
        account=account.address,
        spender=spender.address,
        token="USDC",
        allowance=_CAP_USDC,
        period_seconds=86400,
    )
    signature = sign_spend_permission(permission, account)
    register_spend_permission(permission, signature, spender)
    return permission, spender


@skip_no_keys
def test_spend_within_cap_settles_on_chain(signed_permission):
    permission, spender = signed_permission
    tx_hash = spend(permission, _CAP_USDC - Decimal("0.02"), spender)
    assert tx_hash.startswith("0x")


@skip_no_keys
def test_spend_above_cap_is_rejected_on_chain(signed_permission):
    # The crux demo: the cap has to hold even for a request a buggy or
    # hijacked *caller* might make -- so the contract, not client-side
    # pre-flight, must be what stops this. ExceededSpendPermission(value,
    # allowance) is the contract's own custom error (SpendPermissionManager.sol
    # :420-435); asserting on that specific revert, not "some exception," is
    # the point -- a client-side-only guard would pass this test wrongly.
    permission, spender = signed_permission
    with pytest.raises(SpendCapExceeded):
        spend(permission, _CAP_USDC + Decimal("0.01"), spender)


@skip_no_keys
def test_revoked_permission_rejects_further_spend(signed_permission):
    # "Capped, revocable" (README; CLAUDE.md hard rule 1) is a claim, not a
    # default. A revoked-but-not-yet-expired permission must fail every
    # further spend with UnauthorizedSpendPermission() (the contract's
    # isValid() check runs before the allowance check -- SpendPermissionManager
    # .sol:711), distinct from the over-cap error above.
    permission, spender = signed_permission
    revoke_spend_permission(permission, spender)
    with pytest.raises(SpendPermissionUnauthorized):
        spend(permission, Decimal("0.01"), spender)
