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
