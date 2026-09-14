"""Wallet abstraction. LocalWallet (env key, throwaway) now; CdpWallet is a
documented seam. Callers never see a raw key or a concrete signer type."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Protocol, runtime_checkable

from eth_account import Account
from web3 import Web3

from payments.constants import USDC_BY_CHAIN, rpc_urls

_BALANCE_OF_SELECTOR = "0x70a08231"


@runtime_checkable
class Wallet(Protocol):
    @property
    def address(self) -> str: ...
    def x402_signer(self) -> object: ...
    def usdc_balance(self, network: int) -> Decimal: ...
    def sign_digest(self, digest: bytes) -> bytes: ...
    def send_transaction(self, w3, tx: dict) -> str: ...


def _usdc_balance_of(address: str, network: int) -> Decimal:
    to = Web3.to_checksum_address(USDC_BY_CHAIN[network])   # KeyError here = a real bug, not connectivity
    owner = Web3.to_checksum_address(address)   # bad address = ValueError now, not "no RPC reachable" after every endpoint
    data = _BALANCE_OF_SELECTOR + "0" * 24 + owner.lower().removeprefix("0x")
    last = None
    for url in rpc_urls(network):
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={
                "timeout": 20, "headers": {"User-Agent": "Mozilla/5.0"}}))
            raw = w3.eth.call({"to": to, "data": data})
        except Exception as exc:  # pragma: no cover - network / RPC transport only
            last = exc
            continue
        return Decimal(int(raw.hex(), 16)) / Decimal(10) ** 6   # decode outside the guard
    raise ConnectionError(f"no RPC reachable for chain {network}: {last!r}")


class LocalWallet:
    def __init__(self, private_key: str):
        self._account = Account.from_key(private_key)

    @classmethod
    def from_env(cls, var: str = "X402_WALLET_KEY") -> "LocalWallet":
        key = os.environ.get(var)
        if not key:
            raise RuntimeError(f"{var} is not set")
        return cls(key)

    @property
    def address(self) -> str:
        return self._account.address

    def x402_signer(self) -> object:
        from x402.mechanisms.evm import EthAccountSigner
        return EthAccountSigner(self._account)

    def usdc_balance(self, network: int) -> Decimal:
        return _usdc_balance_of(self.address, network)

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


class CdpWallet:
    """Seam for Coinbase CDP Server Wallet v2 (MPC key in AWS Nitro; no raw key
    on disk). NOT implemented -- CDP API credentials are blocked by CDP business
    verification as of 2026-09. A real implementation returns a remote-signing
    shim from x402_signer() (satisfying register_exact_evm_client) and reads
    balance via the CDP API or an RPC. See docs/superpowers/specs/2026-09-07-
    payments-spine-design.md."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "CdpWallet is a seam; use LocalWallet. See the payments-spine design spec.")
