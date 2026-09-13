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

from payments.constants import (
    SMART_WALLET_DOMAIN_NAME,
    SMART_WALLET_DOMAIN_VERSION,
    SPEND_PERMISSION_MANAGER,
    SPEND_PERMISSION_TYPE_STRING,
)

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
