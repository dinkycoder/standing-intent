import os
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
from payments.wallet import LocalWallet

pytestmark = pytest.mark.integration

_KEY = os.environ.get("SPEND_PERMISSION_ACCOUNT_KEY")
skip_no_key = pytest.mark.skipif(not _KEY, reason="SPEND_PERMISSION_ACCOUNT_KEY unset")

_PERMISSION_COMPONENTS_FOR_TEST = _PERMISSION_COMPONENTS


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
def test_spend_within_cap_then_above_cap_then_revoke():
    owner = LocalWallet(_KEY)
    account = provision_smart_wallet_account(owner, CHAIN_ID_BASE_SEPOLIA, nonce=1)  # fresh nonce, clean permission
    spender = LocalWallet.from_env()
    permission = SpendPermission(
        account=account.address, spender=spender.address, token=USDC_BASE_SEPOLIA,
        allowance=50_000, period=86400,
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
