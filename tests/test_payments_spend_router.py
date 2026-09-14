import os
from decimal import Decimal

import pytest

from payments.constants import CHAIN_ID_BASE_SEPOLIA, SPEND_ROUTER, USDC_BASE_SEPOLIA
from payments.spend_permission import (
    SpendPermission,
    provision_smart_wallet_account,
    sign_spend_permission,
)
from payments.spend_router import encode_extra_data, spend_and_route_with_signature
from payments.wallet import LocalWallet

pytestmark = pytest.mark.integration

_ACCOUNT_KEY = os.environ.get("SPEND_PERMISSION_ACCOUNT_KEY")
skip_no_key = pytest.mark.skipif(not _ACCOUNT_KEY, reason="SPEND_PERMISSION_ACCOUNT_KEY unset")


@skip_no_key
def test_spend_and_route_pays_the_recipient_directly_not_our_wallet():
    owner = LocalWallet(_ACCOUNT_KEY)
    account = provision_smart_wallet_account(owner, CHAIN_ID_BASE_SEPOLIA, nonce=2)
    executor = LocalWallet.from_env()  # our agent's own wallet -- only ever the caller, never the payee
    recipient = "0x000000000000000000000000000000000000bEEF"  # a vendor's x402 pay_to, stand-in

    permission = SpendPermission(
        account=account.address, spender=SPEND_ROUTER, token=USDC_BASE_SEPOLIA,
        allowance=50_000, period=86400,
        extra_data=encode_extra_data(executor.address, recipient),
    )
    signature = sign_spend_permission(permission, account, CHAIN_ID_BASE_SEPOLIA)

    executor_balance_before = executor.usdc_balance(CHAIN_ID_BASE_SEPOLIA)
    tx_hash = spend_and_route_with_signature(
        permission, Decimal("0.03"), signature, executor, CHAIN_ID_BASE_SEPOLIA
    )
    assert tx_hash.startswith("0x")
    assert executor.usdc_balance(CHAIN_ID_BASE_SEPOLIA) == executor_balance_before  # never touched our wallet
