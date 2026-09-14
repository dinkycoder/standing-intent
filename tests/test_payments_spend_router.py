import os
import time
from decimal import Decimal

import pytest

from payments.constants import CHAIN_ID_BASE_SEPOLIA, SPEND_ROUTER, USDC_BASE_SEPOLIA
from payments.spend_permission import (
    SpendPermission,
    provision_smart_wallet_account,
    sign_spend_permission,
)
from payments.spend_router import encode_extra_data, spend_and_route_with_signature
from payments.testing.fixtures import SPEND_PERMISSION_ACCOUNT_NONCE, skip_unless_funded
from payments.wallet import LocalWallet, _usdc_balance_of

pytestmark = pytest.mark.integration

_ACCOUNT_KEY = os.environ.get("SPEND_PERMISSION_ACCOUNT_KEY")
skip_no_key = pytest.mark.skipif(not _ACCOUNT_KEY, reason="SPEND_PERMISSION_ACCOUNT_KEY unset")


@skip_no_key
def test_spend_and_route_pays_the_recipient_directly_not_our_wallet():
    owner = LocalWallet(_ACCOUNT_KEY)
    # Same Smart Wallet (nonce 0) as the rest of the Spend Permission suite --
    # one address to fund; the permissions stay distinct by salt and spender.
    account = provision_smart_wallet_account(
        owner, CHAIN_ID_BASE_SEPOLIA, nonce=SPEND_PERMISSION_ACCOUNT_NONCE
    )
    skip_unless_funded(account.address)  # empty faucet is an environment fact, not a defect
    executor = LocalWallet.from_env()  # our agent's own wallet -- only ever the caller, never the payee
    recipient = "0x000000000000000000000000000000000000bEEF"  # a vendor's x402 pay_to, stand-in

    permission = SpendPermission(
        account=account.address, spender=SPEND_ROUTER, token=USDC_BASE_SEPOLIA,
        allowance=50_000, period=86400, salt=time.time_ns(),  # see _fresh_salt in the
        # provisioning suite: a reused salt is unrecoverable once revoked
        extra_data=encode_extra_data(executor.address, recipient),
    )
    signature = sign_spend_permission(permission, account, CHAIN_ID_BASE_SEPOLIA)

    amount = Decimal("0.03")
    executor_balance_before = executor.usdc_balance(CHAIN_ID_BASE_SEPOLIA)
    recipient_balance_before = _usdc_balance_of(recipient, CHAIN_ID_BASE_SEPOLIA)
    tx_hash = spend_and_route_with_signature(
        permission, amount, signature, executor, CHAIN_ID_BASE_SEPOLIA
    )
    assert tx_hash.startswith("0x")
    assert executor.usdc_balance(CHAIN_ID_BASE_SEPOLIA) == executor_balance_before  # never touched our wallet
    # Half the custody claim is "not us"; the other half is "the vendor, in
    # full." Without this, a router that burned the funds -- or did nothing at
    # all, e.g. a call to a codeless address -- would pass the assertion above
    # (CLAUDE.md rule 4: grade the terminal state, not the absence of an
    # effect).
    assert (
        _usdc_balance_of(recipient, CHAIN_ID_BASE_SEPOLIA) == recipient_balance_before + amount
    )
