import os
import time
from decimal import Decimal

import pytest

from payments.constants import CHAIN_ID_BASE_SEPOLIA, USDC_BASE_SEPOLIA
from payments.errors import SpendCapExceeded, SpendPermissionUnauthorized
from payments.spend_permission import (
    SpendPermission,
    _PERMISSION_COMPONENTS,
    provision_smart_wallet_account,
    register_spend_permission,
    revoke_spend_permission,
    sign_spend_permission,
    spend,
)
from payments.testing.fixtures import SPEND_PERMISSION_ACCOUNT_NONCE, skip_unless_funded
from payments.wallet import LocalWallet

pytestmark = pytest.mark.integration

_KEY = os.environ.get("SPEND_PERMISSION_ACCOUNT_KEY")
skip_no_key = pytest.mark.skipif(not _KEY, reason="SPEND_PERMISSION_ACCOUNT_KEY unset")

_PERMISSION_COMPONENTS_FOR_TEST = _PERMISSION_COMPONENTS


def _fresh_salt() -> int:
    """A salt no earlier run has used. Required, not cosmetic:
    SpendPermissionManager sets _isRevoked[hash] permanently and never clears
    it, so any permission this suite revokes is dead for that exact hash
    forever. With the default salt=0 the revoke test below would pass once and
    then make every subsequent run of this file (and of
    test_payments_spend_permission.py, same account/spender pair) fail against
    the same Smart Wallet. Nanosecond resolution also keeps two permissions
    created in the same second distinct within one run."""
    return time.time_ns()


@skip_no_key
def test_provision_is_idempotent_and_has_spend_permission_manager_as_owner():
    owner = LocalWallet(_KEY)
    account_1 = provision_smart_wallet_account(owner, CHAIN_ID_BASE_SEPOLIA, nonce=0)
    account_2 = provision_smart_wallet_account(owner, CHAIN_ID_BASE_SEPOLIA, nonce=0)
    assert account_1.address == account_2.address  # same owners+nonce -> same address, deploy-once

    from payments.chain import get_web3
    w3 = get_web3(CHAIN_ID_BASE_SEPOLIA)
    is_owner_abi = [{"type": "function", "name": "isOwnerAddress", "stateMutability": "view",
                      "inputs": [{"name": "account", "type": "address"}],
                      "outputs": [{"name": "", "type": "bool"}]}]
    from web3 import Web3
    from payments.constants import SPEND_PERMISSION_MANAGER
    wallet_contract = w3.eth.contract(address=Web3.to_checksum_address(account_1.address), abi=is_owner_abi)
    assert wallet_contract.functions.isOwnerAddress(
        Web3.to_checksum_address(SPEND_PERMISSION_MANAGER)
    ).call() is True


@skip_no_key
def test_sign_and_register_makes_the_permission_approved():
    owner = LocalWallet(_KEY)
    account = provision_smart_wallet_account(owner, CHAIN_ID_BASE_SEPOLIA, nonce=0)
    spender = LocalWallet.from_env()  # X402_WALLET_KEY, existing precedent

    permission = SpendPermission(
        account=account.address, spender=spender.address, token=USDC_BASE_SEPOLIA,
        allowance=50_000, period=86400,  # 0.05 USDC/day
        salt=_fresh_salt(),
    )
    signature = sign_spend_permission(permission, account, CHAIN_ID_BASE_SEPOLIA)
    tx_hash = register_spend_permission(permission, signature, spender, CHAIN_ID_BASE_SEPOLIA)
    assert tx_hash.startswith("0x")

    from payments.chain import get_web3
    from web3 import Web3
    from payments.constants import SPEND_PERMISSION_MANAGER
    w3 = get_web3(CHAIN_ID_BASE_SEPOLIA)
    manager_abi = [{"type": "function", "name": "isApproved", "stateMutability": "view",
                     "inputs": [{"name": "spendPermission", "type": "tuple", "components": _PERMISSION_COMPONENTS_FOR_TEST}],
                     "outputs": [{"name": "", "type": "bool"}]}]
    manager_contract = w3.eth.contract(address=Web3.to_checksum_address(SPEND_PERMISSION_MANAGER), abi=manager_abi)
    assert manager_contract.functions.isApproved(
        (
            Web3.to_checksum_address(permission.account),
            Web3.to_checksum_address(permission.spender),
            Web3.to_checksum_address(permission.token),
            permission.allowance, permission.period, permission.start,
            permission.end, permission.salt, permission.extra_data,
        )
    ).call() is True


@skip_no_key
def test_registering_a_revoked_permission_does_not_silently_succeed():
    """approveWithSignature RETURNS false for a revoked permission instead of
    reverting, so the transaction mines with status=1 and the caller is told a
    permission is live when nothing was approved. Worse, _isRevoked[hash] is
    never cleared, so this is permanent for that hash -- the agent would spend
    against a permission that can never work.

    Needs gas only (no USDC moves), so unlike the spend tests below this one
    actually runs today. It also pins the read-back's SHAPE: an
    isApproved()-only check passes here wrongly, because isApproved stays true
    across a revocation -- measured on chain, see _MANAGER_ABI's table.
    """
    owner = LocalWallet(_KEY)
    account = provision_smart_wallet_account(
        owner, CHAIN_ID_BASE_SEPOLIA, nonce=SPEND_PERMISSION_ACCOUNT_NONCE
    )
    spender = LocalWallet.from_env()
    permission = SpendPermission(
        account=account.address, spender=spender.address, token=USDC_BASE_SEPOLIA,
        allowance=50_000, period=86400, salt=_fresh_salt(),
    )
    signature = sign_spend_permission(permission, account, CHAIN_ID_BASE_SEPOLIA)
    register_spend_permission(permission, signature, spender, CHAIN_ID_BASE_SEPOLIA)
    revoke_spend_permission(permission, spender, CHAIN_ID_BASE_SEPOLIA)

    with pytest.raises(SpendPermissionUnauthorized):
        register_spend_permission(permission, signature, spender, CHAIN_ID_BASE_SEPOLIA)


@skip_no_key
def test_spend_within_cap_then_above_cap_then_revoke():
    owner = LocalWallet(_KEY)
    # Same wallet as every other test in the suite (nonce 0). A separate nonce
    # used to be how this test got a "clean permission"; the fresh salt above
    # does that now without needing a second address funded with test USDC.
    account = provision_smart_wallet_account(
        owner, CHAIN_ID_BASE_SEPOLIA, nonce=SPEND_PERMISSION_ACCOUNT_NONCE
    )
    # Skip, don't fail, on an unfunded wallet -- matching the
    # spend_permission_account fixture. Without this the test reports a red
    # "ERC20: transfer amount exceeds balance" for an empty faucet rather than
    # for a defect. A genuine revert (wrong signature, revoked permission, cap
    # exceeded) still fails loudly: the threshold is 1 USDC against 0.06 of
    # spends here.
    skip_unless_funded(account.address)
    spender = LocalWallet.from_env()
    permission = SpendPermission(
        account=account.address, spender=spender.address, token=USDC_BASE_SEPOLIA,
        allowance=50_000, period=86400, salt=_fresh_salt(),
    )
    signature = sign_spend_permission(permission, account, CHAIN_ID_BASE_SEPOLIA)
    register_spend_permission(permission, signature, spender, CHAIN_ID_BASE_SEPOLIA)

    tx_hash = spend(permission, Decimal("0.03"), spender, CHAIN_ID_BASE_SEPOLIA)
    assert tx_hash.startswith("0x")

    with pytest.raises(SpendCapExceeded):
        spend(permission, Decimal("0.03"), spender, CHAIN_ID_BASE_SEPOLIA)  # 0.03+0.03 > 0.05 cap this period

    revoke_spend_permission(permission, spender, CHAIN_ID_BASE_SEPOLIA)
    with pytest.raises(SpendPermissionUnauthorized):
        spend(permission, Decimal("0.01"), spender, CHAIN_ID_BASE_SEPOLIA)
