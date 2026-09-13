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
from decimal import Decimal

from eth_utils import keccak
from web3 import Web3
import web3.exceptions as _web3_exceptions

from payments.chain import get_web3, wait_for_receipt
from payments.constants import (
    SMART_WALLET_DOMAIN_NAME,
    SMART_WALLET_DOMAIN_VERSION,
    SMART_WALLET_FACTORY_V1_1,
    SPEND_PERMISSION_MANAGER,
    SPEND_PERMISSION_TYPE_STRING,
)
from payments.errors import PaymentError, SpendCapExceeded, SpendPermissionUnauthorized
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


_PERMISSION_COMPONENTS = [
    {"name": "account", "type": "address"},
    {"name": "spender", "type": "address"},
    {"name": "token", "type": "address"},
    {"name": "allowance", "type": "uint160"},
    {"name": "period", "type": "uint48"},
    {"name": "start", "type": "uint48"},
    {"name": "end", "type": "uint48"},
    {"name": "salt", "type": "uint256"},
    {"name": "extraData", "type": "bytes"},
]

_MANAGER_ABI = [
    {"type": "function", "name": "approveWithSignature", "stateMutability": "nonpayable",
     "inputs": [{"name": "spendPermission", "type": "tuple", "components": _PERMISSION_COMPONENTS},
                {"name": "signature", "type": "bytes"}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "function", "name": "spend", "stateMutability": "nonpayable",
     "inputs": [{"name": "spendPermission", "type": "tuple", "components": _PERMISSION_COMPONENTS},
                {"name": "value", "type": "uint160"}],
     "outputs": []},
    {"type": "function", "name": "revoke", "stateMutability": "nonpayable",
     "inputs": [{"name": "spendPermission", "type": "tuple", "components": _PERMISSION_COMPONENTS}],
     "outputs": []},
    {"type": "function", "name": "revokeAsSpender", "stateMutability": "nonpayable",
     "inputs": [{"name": "spendPermission", "type": "tuple", "components": _PERMISSION_COMPONENTS}],
     "outputs": []},
    {"type": "function", "name": "isApproved", "stateMutability": "view",
     "inputs": [{"name": "spendPermission", "type": "tuple", "components": _PERMISSION_COMPONENTS}],
     "outputs": [{"name": "", "type": "bool"}]},
    {"type": "error", "name": "ZeroValue", "inputs": []},
    {"type": "error", "name": "UnauthorizedSpendPermission", "inputs": []},
    {"type": "error", "name": "ExceededSpendPermission",
     "inputs": [{"name": "value", "type": "uint256"}, {"name": "allowance", "type": "uint256"}]},
]


def _permission_tuple(permission: SpendPermission) -> tuple:
    return (
        Web3.to_checksum_address(permission.account),
        Web3.to_checksum_address(permission.spender),
        Web3.to_checksum_address(permission.token),
        permission.allowance, permission.period, permission.start,
        permission.end, permission.salt, permission.extra_data,
    )


def _manager_contract(w3: Web3):
    return w3.eth.contract(address=Web3.to_checksum_address(SPEND_PERMISSION_MANAGER), abi=_MANAGER_ABI)


def sign_spend_permission(permission: SpendPermission, account: SmartWalletAccount, network: int) -> bytes:
    """SignatureWrapper{ ownerIndex: 0, signatureData: r||s||v }, ABI-encoded
    -- src/CoinbaseSmartWallet.sol's SignatureWrapper struct. ownerIndex is
    hardcoded 0 because provision_smart_wallet_account always puts `owner`
    at index 0 (owners[0] in the createAccount call)."""
    inner = _spend_permission_hash(permission, network)
    outer = _replay_safe_hash(inner, network, account.address)
    signature_data = account.owner.sign_digest(outer)
    # abi.encode(SignatureWrapper): (uint256 ownerIndex, bytes signatureData)
    # -- a static uint256 head word, then the dynamic bytes' offset/length/data.
    owner_index = _uint(0)
    offset = _uint(64)
    length = _uint(len(signature_data))
    padded = signature_data + b"\x00" * (-len(signature_data) % 32)
    return owner_index + offset + length + padded


def register_spend_permission(
    permission: SpendPermission, signature: bytes, spender: Wallet, network: int
) -> str:
    w3 = get_web3(network)
    manager = _manager_contract(w3)
    # gasPrice explicit -- see Task 5's build_transaction comment: without it,
    # build_transaction's EIP-1559 auto-fill conflicts with send_transaction's
    # own gasPrice default and eth_account.sign_transaction rejects the tx.
    tx = manager.functions.approveWithSignature(
        _permission_tuple(permission), signature
    ).build_transaction({"from": spender.address, "gas": 300_000, "gasPrice": w3.eth.gas_price})
    tx_hash = spender.send_transaction(w3, tx)
    receipt = wait_for_receipt(w3, tx_hash)
    if receipt["status"] != 1:
        raise SpendPermissionUnauthorized(f"approveWithSignature reverted: {tx_hash}")
    return tx_hash


_ZERO_VALUE_SELECTOR = "0x" + keccak(text="ZeroValue()").hex()[:8]
_UNAUTHORIZED_SELECTOR = "0x" + keccak(text="UnauthorizedSpendPermission()").hex()[:8]
_EXCEEDED_SELECTOR = "0x" + keccak(text="ExceededSpendPermission(uint256,uint256)").hex()[:8]


def _atomic_to_decimal(atomic: int) -> Decimal:
    return Decimal(atomic) / Decimal(10) ** 6


def _translate_custom_error(exc: "_web3_exceptions.ContractCustomError") -> Exception:
    # web3 7.16.0 does not auto-resolve a selector to a name even when the ABI
    # declares the error (confirmed live during planning) -- match the raw
    # selector against independently-recomputed keccak values instead of
    # trusting exc's own message.
    #
    # exc.args[0] is the FULL revert payload (selector + any ABI-encoded
    # arguments), not a bare 4-byte selector -- a zero-argument error like
    # UnauthorizedSpendPermission()'s payload happens to equal just its
    # selector, which is what made an exact `==` comparison look correct
    # during planning. ExceededSpendPermission(uint256,uint256) always
    # carries two arguments, so its real payload is the selector plus 64
    # more bytes and never equals the bare selector constant -- found and
    # reproduced live in Task 7's review (a realistic
    # ExceededSpendPermission(30000, 50000) encodes to 138 hex chars;
    # `==` against the 10-char selector constant is always False, `==`
    # against a zero-arg error's payload is True only by coincidence).
    # startswith is correct for both cases.
    selector = exc.args[0] if exc.args else None
    if selector is not None and selector.startswith(_UNAUTHORIZED_SELECTOR):
        return SpendPermissionUnauthorized()
    if selector is not None and selector.startswith(_EXCEEDED_SELECTOR):
        # ExceededSpendPermission(value, allowance) args aren't recoverable
        # from the bare selector match above (no abi-decoding of the revert
        # payload here) -- report what WE tried to spend against the
        # permission's own allowance, which is what the caller needs anyway.
        return SpendCapExceeded(value=Decimal("-1"), allowance=Decimal("-1"))
    return exc


def spend(permission: SpendPermission, value: Decimal, spender: Wallet, network: int) -> str:
    w3 = get_web3(network)
    manager = _manager_contract(w3)
    atomic_value = int(value * Decimal(10) ** 6)
    fn = manager.functions.spend(_permission_tuple(permission), atomic_value)
    try:
        fn.call({"from": spender.address})  # dry-run: cheap, decodes the revert before paying gas
    except _web3_exceptions.ContractCustomError as exc:
        translated = _translate_custom_error(exc)
        if isinstance(translated, SpendCapExceeded):
            raise SpendCapExceeded(value=value, allowance=_atomic_to_decimal(permission.allowance)) from exc
        raise translated from exc

    # gasPrice explicit -- see Task 5's build_transaction comment.
    tx = fn.build_transaction({"from": spender.address, "gas": 200_000, "gasPrice": w3.eth.gas_price})
    tx_hash = spender.send_transaction(w3, tx)
    receipt = wait_for_receipt(w3, tx_hash)
    if receipt["status"] != 1:
        raise OnChainTransactionReverted(f"spend reverted after passing dry-run: {tx_hash}")
    return tx_hash


def revoke_spend_permission(permission: SpendPermission, revoker: Wallet, network: int) -> str:
    """revokeAsSpender() -- requireSender(spendPermission.spender)
    (src/SpendPermissionManager.sol:406-411, confirmed by direct source
    read). NOT revoke() (requireSender(spendPermission.account)): the
    account is a Smart Wallet, so only a call whose msg.sender is the
    wallet's own address satisfies that -- an EOA owner calling revoke()
    directly still reverts InvalidSender, since msg.sender would be the
    owner's address, not the wallet's. revokeAsSpender is the only one of
    the two callable directly by an EOA the way this module signs and
    sends transactions."""
    w3 = get_web3(network)
    manager = _manager_contract(w3)
    # gasPrice explicit -- see Task 5's build_transaction comment.
    tx = manager.functions.revokeAsSpender(_permission_tuple(permission)).build_transaction({
        "from": revoker.address, "gas": 150_000, "gasPrice": w3.eth.gas_price,
    })
    tx_hash = revoker.send_transaction(w3, tx)
    receipt = wait_for_receipt(w3, tx_hash)
    if receipt["status"] != 1:
        raise OnChainTransactionReverted(f"revokeAsSpender reverted: {tx_hash}")
    return tx_hash
