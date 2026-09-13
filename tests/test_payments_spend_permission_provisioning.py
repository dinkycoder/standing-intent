import os

import pytest

from payments.constants import CHAIN_ID_BASE_SEPOLIA
from payments.spend_permission import provision_smart_wallet_account
from payments.wallet import LocalWallet

pytestmark = pytest.mark.integration

_KEY = os.environ.get("SPEND_PERMISSION_ACCOUNT_KEY")
skip_no_key = pytest.mark.skipif(not _KEY, reason="SPEND_PERMISSION_ACCOUNT_KEY unset")


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
