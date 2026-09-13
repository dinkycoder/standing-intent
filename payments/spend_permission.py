"""Base Spend Permission: account provisioning, the nested EIP-712 signing
math, and the open-ended (bare-spend, custodial-hop) path. See
docs/superpowers/specs/2026-09-13-spend-permission-account-design.md.

Every hash formula below was read directly from primary source (not
inferred): SpendPermissionManager's own domain and struct-hash from
src/SpendPermissionManager.sol; the account-side wrapping from
src/ERC1271.sol; both build on Solady's EIP712._buildDomainSeparator, itself
read directly rather than assumed.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_utils import keccak
from web3 import Web3

from payments.chain import get_web3, wait_for_receipt
from payments.constants import (
    SMART_WALLET_DOMAIN_NAME,
    SMART_WALLET_DOMAIN_VERSION,
    SMART_WALLET_FACTORY_V1_1,
    SPEND_PERMISSION_MANAGER,
    SPEND_PERMISSION_TYPE_STRING,
)
from payments.errors import PaymentError
from payments.wallet import Wallet

# This module grows across Tasks 4-7; each task's own "-- append" snippet
# below adds ONLY the imports its new code actually uses (Decimal, Web3,
# get_web3/wait_for_receipt, Wallet, the error types) rather than
# front-loading them here. Add each import line at the task that first uses
# it, or ruff's unused-import check fails on this task's diff alone.

# uint48 max -- the contract's own "no expiry" sentinel (SpendPermissionManager
# .sol's `end` field is uint48; there is no separate "no expiry" flag, so the
# convention -- confirmed against the type, not assumed -- is the max value).
NO_EXPIRY = 2**48 - 1

_DOMAIN_TYPE_STRING = "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
_MESSAGE_TYPE_STRING = "CoinbaseSmartWalletMessage(bytes32 hash)"


@dataclass(frozen=True)
class SpendPermission:
    account: str
    spender: str
    token: str
    allowance: int          # atomic USDC (10**6 per whole unit) -- matches the
                             # on-chain uint160, not a Decimal whole-USDC value
    period: int              # seconds
    start: int = 0
    end: int = NO_EXPIRY
    salt: int = 0
    extra_data: bytes = b""


def _left_pad32(b: bytes) -> bytes:
    return b.rjust(32, b"\x00")


def _address_bytes(addr: str) -> bytes:
    return _left_pad32(bytes.fromhex(addr[2:].lower()))


def _uint(n: int) -> bytes:
    return n.to_bytes(32, "big")


def _domain_separator(name: str, version: str, chain_id: int, verifying_contract: str) -> bytes:
    return keccak(
        keccak(text=_DOMAIN_TYPE_STRING)
        + keccak(text=name)
        + keccak(text=version)
        + _uint(chain_id)
        + _address_bytes(verifying_contract)
    )


def _spend_permission_hash(permission: SpendPermission, chain_id: int) -> bytes:
    """SpendPermissionManager.getHash(permission) -- the `inner` hash."""
    struct_hash = keccak(
        keccak(text=SPEND_PERMISSION_TYPE_STRING)
        + _address_bytes(permission.account)
        + _address_bytes(permission.spender)
        + _address_bytes(permission.token)
        + _uint(permission.allowance)
        + _uint(permission.period)
        + _uint(permission.start)
        + _uint(permission.end)
        + _uint(permission.salt)
        + keccak(permission.extra_data)
    )
    domain = _domain_separator("Spend Permission Manager", "1", chain_id, SPEND_PERMISSION_MANAGER)
    return keccak(b"\x19\x01" + domain + struct_hash)


def _replay_safe_hash(inner_hash: bytes, chain_id: int, account_address: str) -> bytes:
    """account.isValidSignature's replaySafeHash(inner_hash) -- the `outer`
    wrap, through the ACCOUNT's own domain (src/ERC1271.sol), not
    SpendPermissionManager's."""
    message_hash = keccak(keccak(text=_MESSAGE_TYPE_STRING) + inner_hash)
    domain = _domain_separator(
        SMART_WALLET_DOMAIN_NAME, SMART_WALLET_DOMAIN_VERSION, chain_id, account_address
    )
    return keccak(b"\x19\x01" + domain + message_hash)


_FACTORY_ABI = [
    {"type": "function", "name": "createAccount", "stateMutability": "payable",
     "inputs": [{"name": "owners", "type": "bytes[]"}, {"name": "nonce", "type": "uint256"}],
     "outputs": [{"name": "account", "type": "address"}]},
    {"type": "function", "name": "getAddress", "stateMutability": "view",
     "inputs": [{"name": "owners", "type": "bytes[]"}, {"name": "nonce", "type": "uint256"}],
     "outputs": [{"name": "", "type": "address"}]},
]


class OnChainTransactionReverted(PaymentError):
    """A broadcast transaction's receipt came back with status != 1 --
    generic on-chain revert (bad initcode, out-of-gas, an unhandled
    contract-level check), not a signing problem. SigningError is the
    wrong class for this: it means "the wallet failed to produce a
    signature," a different failure mode entirely -- flagged in Task 5's
    review. Used across this module wherever a revert isn't one of the
    two specific SpendPermissionManager errors (SpendCapExceeded,
    SpendPermissionUnauthorized) that get their own typed exception."""


@dataclass(frozen=True)
class SmartWalletAccount:
    address: str
    owner: Wallet


def _owner_bytes(address: str) -> bytes:
    """abi.encode(address) as the factory expects for an address-typed
    owner -- a single left-padded 32-byte word (src/CoinbaseSmartWalletFactory
    .sol: "Each item should be an ABI encoded address or 64 byte public
    key")."""
    return _address_bytes(address)


def provision_smart_wallet_account(owner: Wallet, network: int, nonce: int = 0) -> SmartWalletAccount:
    """Deploy (or reuse, if already deployed) a Coinbase Smart Wallet owned by
    `owner`, with SpendPermissionManager baked into the initial owner set --
    see the design spec for why this avoids needing addOwnerAddress/a
    bundler. Idempotent: same (owner, nonce) always resolves to the same
    counterfactual address; a second call is a cheap no-op deploy attempt
    against an address that already has code."""
    w3 = get_web3(network)
    factory = w3.eth.contract(
        address=Web3.to_checksum_address(SMART_WALLET_FACTORY_V1_1), abi=_FACTORY_ABI
    )
    owners = [_owner_bytes(owner.address), _owner_bytes(SPEND_PERMISSION_MANAGER)]

    address = factory.functions.getAddress(owners, nonce).call()
    if w3.eth.get_code(address) == b"":
        # gasPrice must be explicit: build_transaction on an EIP-1559 chain
        # (Base Sepolia/mainnet both are) auto-fills maxFeePerGas/
        # maxPriorityFeePerGas when gasPrice is absent, and
        # Wallet.send_transaction's setdefault("gasPrice", ...) then adds a
        # gasPrice on top of those -- eth_account.sign_transaction rejects
        # that combination outright. Passing gasPrice here makes
        # build_transaction emit a legacy-type dict with no EIP-1559 fields,
        # so send_transaction's setdefault becomes a no-op. Confirmed by
        # reproducing the conflict live against the pinned web3/eth-account
        # versions during Task 5's review -- this is not a hypothetical.
        tx = factory.functions.createAccount(owners, nonce).build_transaction({
            "from": owner.address, "gas": 700_000, "gasPrice": w3.eth.gas_price,
        })
        tx_hash = owner.send_transaction(w3, tx)
        receipt = wait_for_receipt(w3, tx_hash)
        if receipt["status"] != 1:
            raise OnChainTransactionReverted(f"createAccount reverted: {tx_hash}")

    return SmartWalletAccount(address=address, owner=owner)
