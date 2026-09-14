# Week 4 Spend Permission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `tests/test_payments_spend_permission.py` (PR #8, currently red by design) pass for real against Base Sepolia, and add the atomic-routing path for allowlisted mandates — turning the Week-4 design spec into working, tested code.

**Architecture:** Raw `web3.py` + `eth_account` calls against the already-verified `SpendPermissionManager` and `CoinbaseSmartWalletFactory` contracts — no CDP API dependency (still blocked by business verification). Two spend paths, chosen by whether a mandate has `vendor_allowlist`: a bare `spend()` into our own wallet plus a separate forward (open-ended mandates, Phase 1 — the custodial hop, explicitly gated Sepolia-only), and a `SpendRouter`-routed atomic path (allowlisted mandates, Phase 2 — needs a Foundry deployment first).

**Tech Stack:** Python 3.11+, `web3==7.16.0`, `eth-account==0.14.0`, `pytest`. Phase 2 additionally needs Foundry (`forge`) — not yet installed anywhere in this repo.

**Spec:** `docs/superpowers/specs/2026-09-13-spend-permission-account-design.md`

## Global Constraints

- **No CDP API dependency.** `CdpWallet` remains a stub (`payments/wallet.py`); every task here uses `LocalWallet` / raw contract calls, matching the Week-3 precedent.
- **No unverified on-chain constants (CLAUDE.md rule 2).** Every new address gets a source-URL comment in `payments/constants.py` and an on-chain pin test before any other code depends on it.
- **The custodial hop (Phase 1) is Sepolia-only.** No task in Phase 1 wires it to a mainnet chain id. It stays gated until the money-transmission opinion `docs/PMF_AND_BUILD_PLAN.md`'s Caveats section calls for actually exists — that gate is not something this plan closes.
- **`Wallet` never leaks a raw private key to a caller** (existing invariant, `payments/wallet.py`). New `Wallet` methods return signatures/tx hashes, never the key.
- **Every constant, selector, and struct-hash formula below was read from primary source and independently re-derived — see the design spec's "Sources" section.** Don't second-guess the formulas by re-deriving them differently; do add the on-chain pin tests that check them against reality.

---

### Task 1: `Wallet` gains raw-digest signing and transaction sending

**Files:**
- Modify: `payments/wallet.py`
- Test: `tests/test_payments_wallet.py`

**Interfaces:**
- Produces: `Wallet.sign_digest(digest: bytes) -> bytes` (65-byte packed `r||s||v`), `Wallet.send_transaction(w3: Web3, tx: dict) -> str` (`0x`-prefixed tx hash). Both added to the `Wallet` `Protocol` and implemented on `LocalWallet`. `CdpWallet` is untouched (still raises).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_payments_wallet.py -- append

def test_sign_digest_recovers_to_wallet_address(throwaway_key):
    wallet = LocalWallet(throwaway_key)
    digest = b"\x11" * 32
    sig = wallet.sign_digest(digest)
    assert len(sig) == 65
    r, s, v = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:64], "big"), sig[64]
    recovered = Account._recover_hash(digest, vrs=(v, r, s))
    assert recovered.lower() == wallet.address.lower()


def test_send_transaction_returns_a_tx_hash(monkeypatch, throwaway_key):
    from web3 import Web3
    wallet = LocalWallet(throwaway_key)
    w3 = Web3(Web3.HTTPProvider("https://base-sepolia-rpc.publicnode.com", request_kwargs={"timeout": 20}))
    sent = {}

    def fake_send_raw_transaction(raw):
        sent["raw"] = raw
        return b"\xab" * 32

    monkeypatch.setattr(w3.eth, "send_raw_transaction", fake_send_raw_transaction)
    monkeypatch.setattr(w3.eth, "get_transaction_count", lambda addr: 7)
    monkeypatch.setattr(w3.eth, "gas_price", 1_000_000, raising=False)
    tx = {"to": "0x000000000000000000000000000000000000bEEF", "data": "0x", "value": 0,
          "gas": 21000, "chainId": 84532}
    tx_hash = wallet.send_transaction(w3, tx)
    assert tx_hash == "0x" + "ab" * 32
    assert "raw" in sent
```

Reuse the existing `throwaway_key` pytest fixture already defined in this file (`Account.create().key.hex()`, generated fresh per test) — don't add a second key mechanism. `Account` is already imported at module level in this file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_payments_wallet.py -k "sign_digest or send_transaction" -v`
Expected: FAIL — `AttributeError: 'LocalWallet' object has no attribute 'sign_digest'`

- [ ] **Step 3: Implement**

```python
# payments/wallet.py -- add to the Wallet Protocol
@runtime_checkable
class Wallet(Protocol):
    @property
    def address(self) -> str: ...
    def x402_signer(self) -> object: ...
    def usdc_balance(self, network: int) -> Decimal: ...
    def sign_digest(self, digest: bytes) -> bytes: ...
    def send_transaction(self, w3, tx: dict) -> str: ...
```

```python
# payments/wallet.py -- add to LocalWallet
    def sign_digest(self, digest: bytes) -> bytes:
        """Raw ECDSA signature (r||s||v, 65 bytes) over a pre-computed 32-byte
        digest. Used for the Spend Permission's nested EIP-712 hash
        (payments/spend_permission.py), which this project computes itself --
        see the design spec's "Signing" section for why the digest can't go
        through eth_account's own typed-data hasher."""
        signed = self._account.unsafe_sign_hash(digest)
        return bytes(signed.signature)

    def send_transaction(self, w3, tx: dict) -> str:
        """Fill in from/nonce/chainId/gasPrice if absent, sign, broadcast.
        Returns the tx hash; the caller waits for the receipt separately
        (payments/chain.py.wait_for_receipt) -- same split as pay()/
        verify_settlement in payments/client.py and payments/settlement.py."""
        filled = dict(tx)
        filled.setdefault("from", self.address)
        filled.setdefault("nonce", w3.eth.get_transaction_count(self.address))
        filled.setdefault("gasPrice", w3.eth.gas_price)
        signed = self._account.sign_transaction(filled)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        return "0x" + tx_hash.hex().removeprefix("0x")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_payments_wallet.py -k "sign_digest or send_transaction" -v`
Expected: PASS. If `unsafe_sign_hash` or `.raw_transaction` don't exist under those exact names in the pinned `eth-account==0.14.0`, this is where that surfaces — fix the attribute name, not the design (both were confirmed present via a live interpreter check during planning).

- [ ] **Step 5: Commit**

```bash
git add payments/wallet.py tests/test_payments_wallet.py
git commit -m "Add raw-digest signing and transaction sending to Wallet"
```

---

### Task 2: `payments/chain.py` — Web3 connection and receipt waiting

**Files:**
- Create: `payments/chain.py`
- Test: `tests/test_payments_chain.py`

**Interfaces:**
- Consumes: `constants.rpc_urls(chain_id) -> tuple[str, ...]` (existing).
- Produces: `get_web3(chain_id: int) -> Web3`, `wait_for_receipt(w3, tx_hash: str, retries: int = 5, delay: float = 2.0) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_payments_chain.py
import pytest

from payments import constants
from payments.chain import get_web3, wait_for_receipt


def test_get_web3_connects_to_base_sepolia():
    w3 = get_web3(constants.CHAIN_ID_BASE_SEPOLIA)
    assert w3.eth.chain_id == constants.CHAIN_ID_BASE_SEPOLIA


def test_wait_for_receipt_raises_after_retries_exhausted():
    w3 = get_web3(constants.CHAIN_ID_BASE_SEPOLIA)
    with pytest.raises(TimeoutError):
        wait_for_receipt(w3, "0x" + "00" * 32, retries=1, delay=0.01)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_payments_chain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'payments.chain'`

- [ ] **Step 3: Implement**

```python
# payments/chain.py
"""Thin Web3 connection + receipt-waiting helpers, shared by every Spend
Permission operation (payments/spend_permission.py, payments/spend_router.py).
Retries a small public-RPC list, same convention as payments/wallet.py's
_usdc_balance_of and payments/settlement.py's verify_settlement -- never a
silent pass, always a clear error or an explicit skip in the tests that call
this."""

from __future__ import annotations

import time

from web3 import Web3

from payments.constants import rpc_urls


def get_web3(chain_id: int) -> Web3:
    last = None
    for url in rpc_urls(chain_id):
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={
            "timeout": 20, "headers": {"User-Agent": "Mozilla/5.0"}}))
        try:
            if w3.eth.chain_id == chain_id:
                return w3
        except Exception as exc:  # pragma: no cover - network/RPC transport only
            last = exc
            continue
    raise ConnectionError(f"no RPC reachable for chain {chain_id}: {last!r}")


def wait_for_receipt(w3: Web3, tx_hash: str, retries: int = 5, delay: float = 2.0) -> dict:
    """Poll for a receipt; Base block time is ~2s (payments/settlement.py's
    own retry budget uses the same figure)."""
    for _ in range(retries):
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is not None:
                return receipt
        except Exception:  # pragma: no cover - "not found yet" on some providers
            pass
        time.sleep(delay)
    raise TimeoutError(f"no receipt for {tx_hash} after {retries} retries")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_payments_chain.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add payments/chain.py tests/test_payments_chain.py
git commit -m "Add payments/chain.py: Web3 connection + receipt waiting"
```

---

### Task 3: New `PaymentError` subclasses for the Spend Permission path

**Files:**
- Modify: `payments/errors.py`
- Test: `tests/test_payments_errors.py`

**Interfaces:**
- Produces: `SpendCapExceeded(PaymentError)` (carries `value: Decimal`, `allowance: Decimal`), `SpendPermissionUnauthorized(PaymentError)`. These are the exact names `tests/test_payments_spend_permission.py` (PR #8) already imports.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_payments_errors.py -- append
def test_spend_cap_exceeded_carries_value_and_allowance():
    from decimal import Decimal
    from payments.errors import SpendCapExceeded
    err = SpendCapExceeded(Decimal("0.06"), Decimal("0.05"))
    assert err.value == Decimal("0.06")
    assert err.allowance == Decimal("0.05")
    assert "0.06" in str(err) and "0.05" in str(err)


def test_spend_permission_unauthorized_is_a_payment_error():
    from payments.errors import PaymentError, SpendPermissionUnauthorized
    assert issubclass(SpendPermissionUnauthorized, PaymentError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_payments_errors.py -k "SpendCap or SpendPermissionUnauthorized" -v`
Expected: FAIL — `ImportError: cannot import name 'SpendCapExceeded'`

- [ ] **Step 3: Implement**

```python
# payments/errors.py -- append
class SpendCapExceeded(PaymentError):
    """The on-chain SpendPermissionManager rejected a spend as exceeding the
    signed allowance for the current period -- ExceededSpendPermission(value,
    allowance) on the real contract (src/SpendPermissionManager.sol)."""

    def __init__(self, value: Decimal, allowance: Decimal):
        self.value = value
        self.allowance = allowance
        super().__init__(f"spend {value} USDC exceeds allowance {allowance} USDC")


class SpendPermissionUnauthorized(PaymentError):
    """The permission is not currently approved-and-not-revoked --
    UnauthorizedSpendPermission() on the real contract. Raised both for a
    permission that was never approved and one that has been revoked."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_payments_errors.py -k "SpendCap or SpendPermissionUnauthorized" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add payments/errors.py tests/test_payments_errors.py
git commit -m "Add SpendCapExceeded and SpendPermissionUnauthorized errors"
```

---

### Task 4: `payments/spend_permission.py` — struct, ABI, and the nested signing hash

This is the highest-risk task in the plan (the design spec's flagged "trap"). It is entirely offline-testable — no live chain call needed to verify the hash math, only to verify it against the *real* contract later (Task 6).

**Files:**
- Create: `payments/spend_permission.py`
- Test: `tests/test_spend_permission_signing.py`

**Interfaces:**
- Consumes: `constants.SPEND_PERMISSION_MANAGER`, `constants.SPEND_PERMISSION_TYPE_STRING`, `constants.SMART_WALLET_DOMAIN_NAME`, `constants.SMART_WALLET_DOMAIN_VERSION` (all already on `main`).
- Produces: `SpendPermission` (frozen dataclass), `_domain_separator(name, version, chain_id, verifying_contract) -> bytes`, `_spend_permission_hash(permission, chain_id) -> bytes` (32 bytes — the `inner`/`getHash()` equivalent), `_replay_safe_hash(inner_hash, chain_id, account_address) -> bytes` (32 bytes — the `outer` wrap). The leading underscore marks these as the module's internal hash-math API; Task 6 (`sign_spend_permission`) is the public entry point that calls them.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_spend_permission_signing.py
"""Offline test of the nested EIP-712 hash math (design spec, "Signing --
the trap that needs its own test"). No network call: every input here is
either a fixed constant or hand-computable, so a wrong formula shows up as a
wrong hash immediately, not as a mysterious on-chain revert three tasks later.
"""
from eth_utils import keccak

from payments.constants import (
    CHAIN_ID_BASE_SEPOLIA,
    SMART_WALLET_DOMAIN_NAME,
    SMART_WALLET_DOMAIN_VERSION,
    SPEND_PERMISSION_MANAGER,
)
from payments.spend_permission import (
    SpendPermission,
    _domain_separator,
    _replay_safe_hash,
    _spend_permission_hash,
)

_ACCOUNT = "0x000000000000000000000000000000000000dEaD"
_SPENDER = "0x000000000000000000000000000000000000bEEF"
_TOKEN = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # USDC_BASE_SEPOLIA


def _permission() -> SpendPermission:
    return SpendPermission(
        account=_ACCOUNT, spender=_SPENDER, token=_TOKEN,
        allowance=1_000_000, period=86400, start=0, end=281474976710655,
        salt=0, extra_data=b"",
    )


def test_domain_separator_matches_hand_derivation():
    # keccak256(abi.encode(EIP712_DOMAIN_TYPEHASH, keccak(name), keccak(version),
    # chainId, verifyingContract)) -- Solady's EIP712._buildDomainSeparator,
    # confirmed by direct source read during planning.
    domain_typehash = keccak(
        text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    )
    expected = keccak(
        domain_typehash
        + keccak(text="Spend Permission Manager")
        + keccak(text="1")
        + CHAIN_ID_BASE_SEPOLIA.to_bytes(32, "big")
        + bytes.fromhex(SPEND_PERMISSION_MANAGER[2:].lower()).rjust(32, b"\x00")
    )
    got = _domain_separator(
        "Spend Permission Manager", "1", CHAIN_ID_BASE_SEPOLIA, SPEND_PERMISSION_MANAGER
    )
    assert got == expected


def test_spend_permission_hash_changes_if_any_field_changes():
    # Not a golden value (none exists yet -- Task 6 gets the first live
    # cross-check against the real getHash()). What this DOES prove: the hash
    # is a real function of every field, so two permissions differing in one
    # field never collide -- the property a wrong/short-circuited
    # implementation would most plausibly get wrong.
    base = _permission()
    h1 = _spend_permission_hash(base, CHAIN_ID_BASE_SEPOLIA)
    assert len(h1) == 32
    for changed in [
        base.__class__(**{**base.__dict__, "allowance": base.allowance + 1}),
        base.__class__(**{**base.__dict__, "salt": 1}),
        base.__class__(**{**base.__dict__, "extra_data": b"x"}),
        base.__class__(**{**base.__dict__, "spender": _ACCOUNT}),
    ]:
        assert _spend_permission_hash(changed, CHAIN_ID_BASE_SEPOLIA) != h1


def test_replay_safe_hash_differs_from_the_inner_hash():
    # The whole point of the nesting: signing the inner hash directly must
    # produce something different from signing the wrapped hash, or the
    # "wrap through the account's own domain" step isn't doing anything.
    inner = _spend_permission_hash(_permission(), CHAIN_ID_BASE_SEPOLIA)
    outer = _replay_safe_hash(inner, CHAIN_ID_BASE_SEPOLIA, _ACCOUNT)
    assert outer != inner
    assert len(outer) == 32


def test_replay_safe_hash_differs_per_account():
    # account.domainSeparator() includes verifyingContract = the account's
    # OWN address -- two different accounts must get two different wrapped
    # hashes for the identical inner hash (this is the anti-replay property
    # ERC1271.sol's own comment names explicitly).
    inner = _spend_permission_hash(_permission(), CHAIN_ID_BASE_SEPOLIA)
    a = _replay_safe_hash(inner, CHAIN_ID_BASE_SEPOLIA, _ACCOUNT)
    b = _replay_safe_hash(inner, CHAIN_ID_BASE_SEPOLIA, _SPENDER)
    assert a != b
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_spend_permission_signing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'payments.spend_permission'`

- [ ] **Step 3: Implement**

```python
# payments/spend_permission.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_spend_permission_signing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add payments/spend_permission.py tests/test_spend_permission_signing.py
git commit -m "Add SpendPermission struct and the nested EIP-712 hash math"
```

---

### Task 5: `provision_smart_wallet_account` — deploy the test Smart Wallet

**Files:**
- Modify: `payments/spend_permission.py`
- Modify: `payments/constants.py` (add `SMART_WALLET_FACTORY_ABI` is code, not a constant needing a pin -- no change needed there beyond what's already merged)
- Test: `tests/test_payments_spend_permission_provisioning.py` (`@pytest.mark.integration` — needs a funded Base Sepolia gas key)

**Interfaces:**
- Consumes: `constants.SMART_WALLET_FACTORY_V1_1`, `constants.SPEND_PERMISSION_MANAGER` (both already on `main`); `chain.get_web3`, `chain.wait_for_receipt` (Task 2); `Wallet.send_transaction` (Task 1).
- Produces: `SmartWalletAccount` (frozen dataclass: `address: str`, `owner: Wallet`), `provision_smart_wallet_account(owner: Wallet, network: int, nonce: int = 0) -> SmartWalletAccount`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_payments_spend_permission_provisioning.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_payments_spend_permission_provisioning.py -v -m integration`
Expected: FAIL — `ImportError: cannot import name 'provision_smart_wallet_account'` (or SKIPPED if `SPEND_PERMISSION_ACCOUNT_KEY` is unset — fund a throwaway Sepolia key and set the env var first; the Week-1 buyer wallet or a fresh Circle-faucet key both work, it only needs a little Sepolia ETH for gas, no USDC yet).

- [ ] **Step 3: Implement**

```python
# payments/spend_permission.py -- append these imports to the existing block
from web3 import Web3

from payments.chain import get_web3, wait_for_receipt
from payments.constants import SMART_WALLET_FACTORY_V1_1
from payments.errors import PaymentError
from payments.wallet import Wallet

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_payments_spend_permission_provisioning.py -v -m integration`
Expected: PASS (first run deploys and pays gas; second run in the same test is a fast idempotent check).

- [ ] **Step 5: Commit**

```bash
git add payments/spend_permission.py tests/test_payments_spend_permission_provisioning.py
git commit -m "Add provision_smart_wallet_account: deploy the test Smart Wallet"
```

---

### Task 6: `sign_spend_permission` + `register_spend_permission` — approve on chain

**Files:**
- Modify: `payments/spend_permission.py`
- Modify: `tests/test_payments_spend_permission_provisioning.py`

**Interfaces:**
- Consumes: `Wallet.sign_digest` (Task 1), `_spend_permission_hash`/`_replay_safe_hash` (Task 4), `SmartWalletAccount` (Task 5).
- Produces: `sign_spend_permission(permission: SpendPermission, account: SmartWalletAccount, network: int) -> bytes`, `register_spend_permission(permission: SpendPermission, signature: bytes, spender: Wallet, network: int) -> str` (tx hash).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_payments_spend_permission_provisioning.py -- append
from decimal import Decimal

from payments.spend_permission import (
    SpendPermission,
    register_spend_permission,
    sign_spend_permission,
)
from payments.constants import USDC_BASE_SEPOLIA


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
    # _PERMISSION_COMPONENTS_FOR_TEST defined at module scope in this file --
    # see the implementation step for the shared components list.
```

(This test file grows a module-level `_PERMISSION_COMPONENTS_FOR_TEST` matching `payments.spend_permission._PERMISSION_COMPONENTS` — import it directly instead of redefining, see implementation.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_payments_spend_permission_provisioning.py -k register -v -m integration`
Expected: FAIL — `ImportError: cannot import name 'sign_spend_permission'`

- [ ] **Step 3: Implement**

```python
# payments/spend_permission.py -- append this import to the existing block
from payments.errors import SpendPermissionUnauthorized

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_payments_spend_permission_provisioning.py -k register -v -m integration`
Expected: PASS. **This is the first live check of the Task 4 hash math against the real contract** — if the nested-hash formula were subtly wrong, `approveWithSignature` reverts `InvalidSignature` here, not silently. If it does, re-derive against `SpendPermissionManager.getHash(permission)` called directly (add a throwaway `getHash` ABI entry and compare `_spend_permission_hash`'s output to the live call) before touching the replay-safe wrap.

- [ ] **Step 5: Commit**

```bash
git add payments/spend_permission.py tests/test_payments_spend_permission_provisioning.py
git commit -m "Add sign_spend_permission and register_spend_permission"
```

---

### Task 7: `spend` + `revoke_spend_permission` — the open-ended path, with typed errors

**Files:**
- Modify: `payments/spend_permission.py`
- Modify: `tests/test_payments_spend_permission_provisioning.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: `spend(permission: SpendPermission, value: Decimal, spender: Wallet, network: int) -> str`, `revoke_spend_permission(permission: SpendPermission, revoker: Wallet, network: int) -> str`. Both raise `SpendCapExceeded` / `SpendPermissionUnauthorized` (Task 3) instead of a bare `ContractCustomError` — this is what makes PR #8's three tests assert-able the way they're already written.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_payments_spend_permission_provisioning.py -- append
from payments.errors import SpendCapExceeded, SpendPermissionUnauthorized
from payments.spend_permission import revoke_spend_permission, spend


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_payments_spend_permission_provisioning.py -k above_cap -v -m integration`
Expected: FAIL — `ImportError: cannot import name 'spend'`

- [ ] **Step 3: Implement**

```python
# payments/spend_permission.py -- append this import to the existing block
from decimal import Decimal

import web3.exceptions as _web3_exceptions

from payments.errors import SpendCapExceeded

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


def revoke_spend_permission(permission: SpendPermission, spender: Wallet, network: int) -> str:
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
        "from": spender.address, "gas": 150_000, "gasPrice": w3.eth.gas_price,
    })
    tx_hash = spender.send_transaction(w3, tx)
    receipt = wait_for_receipt(w3, tx_hash)
    if receipt["status"] != 1:
        raise OnChainTransactionReverted(f"revokeAsSpender reverted: {tx_hash}")
    return tx_hash
```

`_MANAGER_ABI` (above, this same task) needs a `revokeAsSpender` entry alongside `revoke` — same shape, name changed:

```python
    {"type": "function", "name": "revokeAsSpender", "stateMutability": "nonpayable",
     "inputs": [{"name": "spendPermission", "type": "tuple", "components": _PERMISSION_COMPONENTS}],
     "outputs": []},
```

(The plain `revoke()` entry can stay in the ABI too — a real user's own wallet-initiated revocation goes through it eventually, via the wallet's own UserOp/execute path, just not from this module's `Wallet.send_transaction`, which only ever signs as a plain EOA.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_payments_spend_permission_provisioning.py -k above_cap -v -m integration`
Expected: PASS once the `revoke` vs `revokeAsSpender` question above is resolved.

- [ ] **Step 5: Commit**

```bash
git add payments/spend_permission.py tests/test_payments_spend_permission_provisioning.py
git commit -m "Add spend() and revoke_spend_permission() with typed errors"
```

---

### Task 8: Wire `spend_permission_account` — make PR #8 pass for real

**Files:**
- Modify: `payments/testing/fixtures.py`
- Modify: `tests/test_payments_spend_permission.py` (bring in from PR #8's branch, then reconcile — see Step 1)

**Interfaces:**
- Consumes: `provision_smart_wallet_account` (Task 5), `sign_spend_permission`/`register_spend_permission` (Task 6), `spend`/`revoke_spend_permission` (Task 7).
- Produces: pytest fixture `spend_permission_account` yielding a `SmartWalletAccount`, funded with test USDC.

**Preflight finding, ruled on before this task was dispatched (see ledger):**
PR #8's branch (`week4-spend-permission-cap-spec`, commit `d089f33`) isn't
merged and this implementation branch doesn't have the file yet — Step 1
below brings it in. Its `signed_permission` fixture also calls the API with a
shape from *before* the design spec fixed the final signatures: no `network`
argument anywhere, `token="USDC"` (symbolic, not an address), `allowance` as
a whole-USDC `Decimal`, and the field name `period_seconds` rather than
`period`. This is not a conflict to resolve in this module's favor by
guesswork — the file's own docstring says so directly: *"Week 4 is free to
reshape names as long as these three terminal-state assertions hold once
it's built."* Ruling: update the fixture's construction calls to the Tasks
4–7 signatures (which implement the actual binding spec,
`docs/superpowers/specs/2026-09-13-spend-permission-account-design.md`);
leave the three `test_*` function bodies' assertions untouched — only what
they call changes, not what they check.

- [ ] **Step 1: Bring in PR #8's file and reconcile it against the finalized API**

```bash
git show origin/week4-spend-permission-cap-spec:tests/test_payments_spend_permission.py > tests/test_payments_spend_permission.py
```

Then edit `signed_permission` in that file to:

```python
# tests/test_payments_spend_permission.py -- replace the signed_permission fixture
@pytest.fixture
def signed_permission(spend_permission_account):
    from payments.constants import CHAIN_ID_BASE_SEPOLIA, USDC_BASE_SEPOLIA
    account = spend_permission_account
    spender = LocalWallet.from_env()
    permission = SpendPermission(
        account=account.address,
        spender=spender.address,
        token=USDC_BASE_SEPOLIA,
        allowance=50_000,       # atomic USDC: Decimal("0.05") * 10**6
        period=86400,
    )
    signature = sign_spend_permission(permission, account, CHAIN_ID_BASE_SEPOLIA)
    register_spend_permission(permission, signature, spender, CHAIN_ID_BASE_SEPOLIA)
    return permission, spender
```

And each `spend(...)`/`revoke_spend_permission(...)` call in the three test
bodies gains a trailing `, CHAIN_ID_BASE_SEPOLIA` argument (e.g.
`spend(permission, _CAP_USDC - Decimal("0.02"), spender, CHAIN_ID_BASE_SEPOLIA)`).
`_CAP_USDC` (a `Decimal`, used for the *comparison* values in the test bodies)
stays as-is — only the `SpendPermission.allowance` field itself is atomic.

- [ ] **Step 2: Run the tests to confirm the failure mode is now import-clean but fixture-incomplete**

Run: `python -m pytest tests/test_payments_spend_permission.py -v -m integration`
Expected: FAIL — `fixture 'spend_permission_account' not found` (no more `ImportError`; the reconciliation in Step 1 is what made the file importable at all).

- [ ] **Step 3: Implement the fixture**

```python
# payments/testing/fixtures.py -- append
import os

import pytest

from payments.constants import CHAIN_ID_BASE_SEPOLIA, USDC_BASE_SEPOLIA
from payments.spend_permission import SmartWalletAccount, provision_smart_wallet_account
from payments.wallet import LocalWallet

_ACCOUNT_KEY = os.environ.get("SPEND_PERMISSION_ACCOUNT_KEY")


@pytest.fixture
def spend_permission_account() -> SmartWalletAccount:
    """A funded Coinbase Smart Wallet on Base Sepolia, SpendPermissionManager
    already an owner -- see docs/superpowers/specs/2026-09-13-spend-permission
    -account-design.md. Requires SPEND_PERMISSION_ACCOUNT_KEY (a throwaway
    owner key, never a real user's) funded with a little Sepolia ETH for gas
    and enough test USDC to cover the fixture's 0.05 USDC/day cap."""
    if not _ACCOUNT_KEY:
        pytest.skip("SPEND_PERMISSION_ACCOUNT_KEY unset")
    owner = LocalWallet(_ACCOUNT_KEY)
    account = provision_smart_wallet_account(owner, CHAIN_ID_BASE_SEPOLIA, nonce=0)
    if account.owner.usdc_balance(CHAIN_ID_BASE_SEPOLIA) < 1:  # whole USDC, generous vs a 0.05 cap
        pytest.skip(
            f"fund {account.address} with Base Sepolia test USDC before running this suite"
        )
    return account
```

- [ ] **Step 4: Run the reconciled tests**

Run: `python -m pytest tests/test_payments_spend_permission.py -v -m integration`
Expected: PASS on all three (`test_spend_within_cap_settles_on_chain`,
`test_spend_above_cap_is_rejected_on_chain`, `test_revoked_permission_rejects_further_spend`) — the exact three assertions the design spec named as the crux demo. The bodies are unchanged from PR #8; only the fixture and each call's trailing `network` argument were touched (Step 1).

- [ ] **Step 5: Close out PR #8**

The PR is currently marked "DO NOT MERGE" / draft, on its own branch
(`week4-spend-permission-cap-spec`), separate from this implementation
branch. Once this task's tests pass here, that branch's one commit is
superseded by this task's reconciled version — close PR #8 referencing this
plan/branch rather than merging it as-is (`gh pr close 8 --comment "..."`),
so the repo doesn't end up with two divergent copies of this test file.

- [ ] **Step 6: Commit**

```bash
git add payments/testing/fixtures.py tests/test_payments_spend_permission.py
git commit -m "Wire spend_permission_account: PR #8's failing spec now passes"
```

---

## Phase 1 checkpoint

After Task 8, the open-ended (custodial-hop) path is fully working and tested end-to-end on Base Sepolia. This is a real, demoable increment of the Week-4 crux: one signature, a cap that holds on-chain, revocation that works. **It is gated Sepolia-only** (Global Constraints) until the legal-opinion question is resolved — nothing in Phase 1 should be pointed at `CHAIN_ID_BASE_MAINNET`.

Phase 2 (below) adds the atomic-routing path for allowlisted mandates and needs new tooling (Foundry) first.

---

### Task 9: Foundry setup + compile `SpendRouter`

**Files:**
- Create: `contracts/spend-router/` (a git submodule or shallow clone of `coinbase/spend-permissions` pinned at `e0004e6`, the same commit already cited in `payments/constants.py`)
- Create: `docs/FOUNDRY_SETUP.md` (short — install steps actually run, not copied boilerplate)

- [ ] **Step 1: Install Foundry**

Confirm whether `forge` runs natively on Windows or needs WSL (design spec open item #3) — try native first:

```powershell
# PowerShell, per CLAUDE.md's environment conventions
irm https://foundry.paradigm.xyz | iex
foundryup
forge --version
```

If that fails, fall back to WSL and record which path actually worked in `docs/FOUNDRY_SETUP.md` — don't guess in advance which one succeeds.

- [ ] **Step 2: Clone and build at the pinned commit**

```powershell
git clone https://github.com/coinbase/spend-permissions contracts/spend-router
cd contracts/spend-router
git checkout e0004e63edc4e17de7aa978293800ac7a16892e5
forge install   # pulls solady + magicspend per the repo's own foundry.toml
forge build
```

- [ ] **Step 3: Confirm the build artifact exists**

Run: `Test-Path contracts/spend-router/out/SpendRouter.sol/SpendRouter.json`
Expected: `True`. This JSON has the ABI and deployed bytecode Task 10 needs.

- [ ] **Step 4: Commit**

`contracts/spend-router/` is a clone of external source at a pinned commit — either add it as a real git submodule (preferred, keeps history out of this repo) or `.gitignore` the clone and document the pinned commit + clone command in `docs/FOUNDRY_SETUP.md` so a fresh checkout can reproduce it. Decide which before committing; don't vendor the full external history into this repo's own commits.

```bash
git add docs/FOUNDRY_SETUP.md .gitmodules  # if submodule
git commit -m "Add Foundry setup for compiling SpendRouter"
```

---

### Task 10: Deploy `SpendRouter` to Base Sepolia

**Files:**
- Modify: `payments/constants.py` (add `SPEND_ROUTER`, once deployed)
- Create: `docs/week4-spend-router-deploy.md` (recorded like `docs/week3-mainnet-gate.md`)
- Test: `tests/test_spend_router_deploy.py` (`@pytest.mark.manual`)

- [ ] **Step 1: Write the manual deployment test**

```python
# tests/test_spend_router_deploy.py
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
        "from": deployer.address, "gas": 2_000_000, "gasPrice": w3.eth.gas_price,
    })
    tx_hash = deployer.send_transaction(w3, tx)
    receipt = wait_for_receipt(w3, tx_hash, retries=10)
    assert receipt["status"] == 1
    print(f"SpendRouter deployed at {receipt['contractAddress']}, tx {tx_hash}")
    # Record receipt['contractAddress'] and tx_hash in docs/week4-spend-router-deploy.md
    # and in payments/constants.py (SPEND_ROUTER) by hand after this passes --
    # this test's job is the deploy, not the bookkeeping.
```

- [ ] **Step 2: Run it**

Run: `python -m pytest tests/test_spend_router_deploy.py -v -m manual`
Expected: PASS, printing the deployed address.

- [ ] **Step 3: Record the result**

```python
# payments/constants.py -- append, using the printed address
# SpendRouter -- OUR OWN deployment (not a Coinbase canonical address; the
# upstream repo lists it "TBD"). Deployed from src/SpendRouter.sol at the same
# pinned commit as SPEND_PERMISSION_MANAGER (e0004e6). Recorded:
# docs/week4-spend-router-deploy.md
SPEND_ROUTER = "0x..."  # <- the printed contractAddress
```

```markdown
# docs/week4-spend-router-deploy.md
Deployed `SpendRouter` (coinbase/spend-permissions@e0004e6) to Base Sepolia.

- Address: `0x...`
- Constructor arg: `SPEND_PERMISSION_MANAGER` (`0xf85210B2...`)
- Tx: `0x...`
- Deployed by: `tests/test_spend_router_deploy.py::test_deploy_spend_router_to_base_sepolia`
```

- [ ] **Step 4: Commit**

```bash
git add payments/constants.py docs/week4-spend-router-deploy.md tests/test_spend_router_deploy.py
git commit -m "Deploy SpendRouter to Base Sepolia, record the address"
```

---

### Task 11: On-chain pin for our deployed `SpendRouter`

**Files:**
- Create: `tests/test_spend_router_constants.py`

**Interfaces:**
- Consumes: `constants.SPEND_ROUTER`, `constants.SPEND_PERMISSION_MANAGER`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_spend_router_constants.py
from web3 import Web3

from payments import constants
from payments.chain import get_web3

_ABI = [{"type": "function", "name": "PERMISSION_MANAGER", "stateMutability": "view",
         "inputs": [], "outputs": [{"name": "", "type": "address"}]}]


def test_spend_router_is_bound_to_the_real_spend_permission_manager():
    w3 = get_web3(constants.CHAIN_ID_BASE_SEPOLIA)
    router = w3.eth.contract(address=Web3.to_checksum_address(constants.SPEND_ROUTER), abi=_ABI)
    got = router.functions.PERMISSION_MANAGER().call()
    assert got.lower() == constants.SPEND_PERMISSION_MANAGER.lower()
```

- [ ] **Step 2: Run it to verify it fails**

Before Task 10 lands, `constants.SPEND_ROUTER` doesn't exist — `AttributeError`. After Task 10, it should already pass; this task is really "confirm Task 10's deploy is correctly bound," written as its own committed pin rather than a one-off print statement.

- [ ] **Step 3: Run it to verify it passes**

Run: `python -m pytest tests/test_spend_router_constants.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_spend_router_constants.py
git commit -m "Pin our deployed SpendRouter to the real SpendPermissionManager"
```

---

### Task 12: `payments/spend_router.py` — the allowlisted, atomic-routing path

**Files:**
- Create: `payments/spend_router.py`
- Test: `tests/test_payments_spend_router.py` (`@pytest.mark.integration`)

**Interfaces:**
- Consumes: `SpendPermission`, `_permission_tuple`, `sign_spend_permission`-style hash helpers (Task 4/6), `constants.SPEND_ROUTER` (Task 10).
- Produces: `encode_extra_data(executor: str, recipient: str) -> bytes`, `spend_and_route(permission: SpendPermission, value: Decimal, spender: Wallet, network: int) -> str`, `spend_and_route_with_signature(permission, value, signature, spender, network) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_payments_spend_router.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_payments_spend_router.py -v -m integration`
Expected: FAIL — `ModuleNotFoundError: No module named 'payments.spend_router'`

- [ ] **Step 3: Implement**

```python
# payments/spend_router.py
"""SpendRouter: atomic spend-and-forward for allowlisted mandates. See the
design spec's "Two paths, chosen by Mandate.vendor_allowlist" section --
this is the clean path (funds never touch our own wallet); the open-ended
custodial-hop path lives in payments/spend_permission.py's bare spend().
"""

from __future__ import annotations

from decimal import Decimal

from web3 import Web3

from payments.chain import get_web3, wait_for_receipt
from payments.constants import SPEND_ROUTER
from payments.spend_permission import OnChainTransactionReverted, _permission_tuple, SpendPermission
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


def encode_extra_data(executor: str, recipient: str) -> bytes:
    """abi.encode(executor, recipient) -- two static addresses, 64 bytes,
    matching SpendRouter.encodeExtraData exactly (src/SpendRouter.sol)."""
    def _pad(addr: str) -> bytes:
        return bytes.fromhex(addr[2:].lower()).rjust(32, b"\x00")
    return _pad(executor) + _pad(recipient)


def spend_and_route_with_signature(
    permission: SpendPermission, value: Decimal, signature: bytes, spender: Wallet, network: int
) -> str:
    w3 = get_web3(network)
    router = _router_contract(w3)
    atomic_value = int(value * Decimal(10) ** 6)
    # gasPrice explicit -- see Task 5's build_transaction comment.
    tx = router.functions.spendAndRouteWithSignature(
        _permission_tuple(permission), atomic_value, signature
    ).build_transaction({"from": spender.address, "gas": 300_000, "gasPrice": w3.eth.gas_price})
    tx_hash = spender.send_transaction(w3, tx)
    receipt = wait_for_receipt(w3, tx_hash)
    if receipt["status"] != 1:
        raise OnChainTransactionReverted(f"spendAndRouteWithSignature reverted: {tx_hash}")
    return tx_hash


def spend_and_route(permission: SpendPermission, value: Decimal, spender: Wallet, network: int) -> str:
    """Same as above, for a permission already approved on-chain (skips the
    signature -- use after a prior approveBatchWithSignature call, not built
    in this plan; single-permission batch-signing is Task 12's known gap,
    same TODO as _PERMISSION_COMPONENTS above)."""
    w3 = get_web3(network)
    router = _router_contract(w3)
    atomic_value = int(value * Decimal(10) ** 6)
    # gasPrice explicit -- see Task 5's build_transaction comment.
    tx = router.functions.spendAndRoute(
        _permission_tuple(permission), atomic_value
    ).build_transaction({"from": spender.address, "gas": 250_000, "gasPrice": w3.eth.gas_price})
    tx_hash = spender.send_transaction(w3, tx)
    receipt = wait_for_receipt(w3, tx_hash)
    if receipt["status"] != 1:
        raise OnChainTransactionReverted(f"spendAndRoute reverted: {tx_hash}")
    return tx_hash
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_payments_spend_router.py -v -m integration`
Expected: PASS. The balance assertion (`executor.usdc_balance(...) == executor_balance_before`) is the test that actually proves the custody claim, not just that the call succeeded.

- [ ] **Step 5: Commit**

```bash
git add payments/spend_router.py tests/test_payments_spend_router.py
git commit -m "Add SpendRouter integration: the allowlisted atomic-routing path"
```

---

## Self-review notes (per writing-plans skill)

- **Spec coverage:** every numbered item in the design spec's "Architecture" section has a task (`spend_permission.py` → Tasks 4/5/6/7; `spend_router.py` → Task 12; the on-chain pins → Tasks 10/11). The `approveBatchWithSignature` batch-signing case (allowlisted mandates with *multiple* vendors signed in one shot) is explicitly named as NOT built here (Task 12's docstring) — flagged as a gap, not silently dropped.
- **Placeholder scan:** the one deliberate exception is `_PERMISSION_COMPONENTS` duplicated in `payments/spend_router.py` (Task 12) — called out inline as a TODO rather than presented as final, per the skill's own instruction that a flagged gap beats a silent one.
- **Type consistency:** `SpendPermission.allowance`/values are atomic ints (matching the on-chain `uint160`) everywhere in `payments/spend_permission.py` and `payments/spend_router.py`; `spend()`/`spend_and_route*()` take `Decimal` whole-USDC `value` and convert once at the call boundary — checked consistent across Tasks 4, 6, 7, 12.
- **One question surfaced and resolved during planning, not left open:** Task 7 initially wasn't sure whether `revoke()` or `revokeAsSpender()` was callable by our own EOA spender. Checked directly against `src/SpendPermissionManager.sol`'s two `requireSender` clauses (`account` vs `spender`) rather than guessed — `revokeAsSpender()` is correct, and the task now uses it.
