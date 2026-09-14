"""Run once by hand to deploy SpendRouter to Base Sepolia; records the result
like tests/test_payments_mainnet_gate.py did for the Week-3 mainnet gate.
Not part of the CI-run tiers."""
import json
from pathlib import Path

import pytest
from web3 import Web3

from payments.chain import get_web3, wait_for_receipt
from payments.constants import CHAIN_ID_BASE_SEPOLIA, SPEND_PERMISSION_MANAGER
from payments.wallet import LocalWallet

pytestmark = pytest.mark.manual


def test_deploy_spend_router_to_base_sepolia():
    artifact = json.loads(
        Path("contracts/spend-router/out/SpendRouter.sol/SpendRouter.json").read_text()
    )
    bytecode = artifact["bytecode"]["object"]
    abi = artifact["abi"]

    w3 = get_web3(CHAIN_ID_BASE_SEPOLIA)
    deployer = LocalWallet.from_env()  # X402_WALLET_KEY, or a dedicated deploy key
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    # gasPrice explicit -- see payments/spend_permission.py Task 5's
    # build_transaction comment: without it, this conflicts with
    # send_transaction's own gasPrice default on an EIP-1559 chain.
    tx = contract.constructor(Web3.to_checksum_address(SPEND_PERMISSION_MANAGER)).build_transaction({
        "from": deployer.address, "gas": 5_000_000, "gasPrice": w3.eth.gas_price,
    })
    tx_hash = deployer.send_transaction(w3, tx)
    receipt = wait_for_receipt(w3, tx_hash, retries=10)
    assert receipt["status"] == 1
    print(f"SpendRouter deployed at {receipt['contractAddress']}, tx {tx_hash}")
    # Record receipt['contractAddress'] and tx_hash in docs/week4-spend-router-deploy.md
    # and in payments/constants.py (SPEND_ROUTER) by hand after this passes --
    # this test's job is the deploy, not the bookkeeping.
