"""SpendRouter: atomic spend-and-forward for allowlisted mandates. See the
design spec's "Two paths, chosen by Mandate.vendor_allowlist" section --
this is the clean path (funds never touch our own wallet); the open-ended
custodial-hop path lives in payments/spend_permission.py's bare spend().
"""

from __future__ import annotations

from decimal import Decimal

from web3 import Web3

from payments.chain import get_web3
from payments.constants import CHAIN_ID_BASE_SEPOLIA, SPEND_ROUTER
from payments.errors import PaymentError
from payments.spend_permission import (
    OnChainTransactionReverted,
    SpendPermission,
    _permission_tuple,
    _receipt_or_raise,
)
from payments.wallet import Wallet

_PERMISSION_COMPONENTS = [  # duplicated from spend_permission.py's _PERMISSION_COMPONENTS
    {"name": "account", "type": "address"}, {"name": "spender", "type": "address"},
    {"name": "token", "type": "address"}, {"name": "allowance", "type": "uint160"},
    {"name": "period", "type": "uint48"}, {"name": "start", "type": "uint48"},
    {"name": "end", "type": "uint48"}, {"name": "salt", "type": "uint256"},
    {"name": "extraData", "type": "bytes"},
]  # TODO at implementation time: import the one in spend_permission.py instead
   # of duplicating -- left inline here only because this plan step must be
   # self-contained code, not because duplication is the intended final shape.

_ROUTER_ABI = [
    {"type": "function", "name": "spendAndRoute", "stateMutability": "nonpayable",
     "inputs": [{"name": "permission", "type": "tuple", "components": _PERMISSION_COMPONENTS},
                {"name": "value", "type": "uint160"}], "outputs": []},
    {"type": "function", "name": "spendAndRouteWithSignature", "stateMutability": "nonpayable",
     "inputs": [{"name": "permission", "type": "tuple", "components": _PERMISSION_COMPONENTS},
                {"name": "value", "type": "uint160"}, {"name": "signature", "type": "bytes"}],
     "outputs": []},
    {"type": "function", "name": "encodeExtraData", "stateMutability": "pure",
     "inputs": [{"name": "executor", "type": "address"}, {"name": "recipient", "type": "address"}],
     "outputs": [{"name": "extraData", "type": "bytes"}]},
]


def _router_contract(w3: Web3):
    return w3.eth.contract(address=Web3.to_checksum_address(SPEND_ROUTER), abi=_ROUTER_ABI)


def _require_router_chain(network: int) -> None:
    """SPEND_ROUTER is a single Base-Sepolia address (payments/constants.py --
    our own deployment, not a canonical cross-chain one). Calling the router
    on any other chain does NOT revert: the EVM treats a call to a codeless
    address as a success with empty return data, so the transaction mines with
    status=1 and this module reports a tx hash as though a payment had
    settled, while nothing moved. Refuse the chain instead of silently
    no-opping -- CLAUDE.md rule 2's "a plausible but wrong address that fails
    silently is worse than a crash." Lift this by making SPEND_ROUTER a
    chain-keyed dict once the router is deployed elsewhere."""
    if network != CHAIN_ID_BASE_SEPOLIA:
        raise PaymentError(
            f"SpendRouter is only deployed on Base Sepolia ({CHAIN_ID_BASE_SEPOLIA}); "
            f"refusing to call {SPEND_ROUTER} on chain {network}, where it has no code "
            "and the call would silently succeed without paying anyone"
        )


def encode_extra_data(executor: str, recipient: str) -> bytes:
    """abi.encode(executor, recipient) -- two static addresses, 64 bytes,
    matching SpendRouter.encodeExtraData exactly (src/SpendRouter.sol)."""
    def _pad(addr: str) -> bytes:
        return bytes.fromhex(addr[2:].lower()).rjust(32, b"\x00")
    return _pad(executor) + _pad(recipient)


def spend_and_route_with_signature(
    permission: SpendPermission, value: Decimal, signature: bytes, spender: Wallet, network: int
) -> str:
    _require_router_chain(network)
    w3 = get_web3(network)
    router = _router_contract(w3)
    atomic_value = int(value * Decimal(10) ** 6)
    # gasPrice explicit -- see Task 5's build_transaction comment.
    tx = router.functions.spendAndRouteWithSignature(
        _permission_tuple(permission), atomic_value, signature
    ).build_transaction({"from": spender.address, "gas": 300_000, "gasPrice": w3.eth.gas_price})
    tx_hash = spender.send_transaction(w3, tx)
    receipt = _receipt_or_raise(w3, tx_hash, "spendAndRouteWithSignature")
    if receipt["status"] != 1:
        raise OnChainTransactionReverted(f"spendAndRouteWithSignature reverted: {tx_hash}")
    return tx_hash


def spend_and_route(permission: SpendPermission, value: Decimal, spender: Wallet, network: int) -> str:
    """Same as above, for a permission already approved on-chain (skips the
    signature -- use after a prior approveBatchWithSignature call, not built
    in this plan; single-permission batch-signing is Task 12's known gap,
    same TODO as _PERMISSION_COMPONENTS above)."""
    _require_router_chain(network)
    w3 = get_web3(network)
    router = _router_contract(w3)
    atomic_value = int(value * Decimal(10) ** 6)
    # gasPrice explicit -- see Task 5's build_transaction comment.
    tx = router.functions.spendAndRoute(
        _permission_tuple(permission), atomic_value
    ).build_transaction({"from": spender.address, "gas": 250_000, "gasPrice": w3.eth.gas_price})
    tx_hash = spender.send_transaction(w3, tx)
    receipt = _receipt_or_raise(w3, tx_hash, "spendAndRoute")
    if receipt["status"] != 1:
        raise OnChainTransactionReverted(f"spendAndRoute reverted: {tx_hash}")
    return tx_hash
