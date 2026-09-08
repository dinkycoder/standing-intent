"""Independent on-chain verification of an x402 settlement. Read-only: no key,
no spend. 'A 200 response is not proof of settlement -- the chain is.'"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

from web3 import Web3
from web3.exceptions import TransactionNotFound

from payments.constants import TRANSFER_TOPIC, USDC_BY_CHAIN, rpc_urls
from payments.errors import SettlementNotConfirmed

_RETRIES = 5
_RETRY_SLEEP = 2.0


@dataclass(frozen=True)
class ExpectedSettlement:
    payer: str
    pay_to: str
    asset: str
    amount: Decimal            # whole USDC


@dataclass(frozen=True)
class VerifiedSettlement:
    tx_hash: str
    network: int
    block_number: int
    status_ok: bool
    transfer_from: str
    transfer_to: str
    amount_atomic: int
    amount_usdc: Decimal
    submitted_by: str
    payer_paid_gas: bool
    matches_expected: bool
    mismatch: str | None


def _connect(url: str) -> Web3:
    return Web3(Web3.HTTPProvider(url, request_kwargs={
        "timeout": 20, "headers": {"User-Agent": "Mozilla/5.0"}}))


def _receipt_and_tx(chain_id: int, tx_hash: str):
    """Fetch (receipt, tx) for a tx, trying each RPC in turn.

    Returns (None, None) when an RPC answered but the tx is genuinely absent
    after the retry budget (propagation lag allowance).

    Raises ConnectionError when no RPC could serve the query at all -- a
    transport / HTTP error on every endpoint. Per the controller ruling this is
    distinct from SettlementNotConfirmed, which means "the tx is not on chain".
    Some free endpoints (publicnode) answer eth_blockNumber but 403 on
    eth_getTransactionReceipt, so liveness is judged on the receipt call itself,
    not a generic is_connected() probe.
    """
    last = None
    reachable = False
    for url in rpc_urls(chain_id):
        w3 = _connect(url)
        for _ in range(_RETRIES):
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                tx = w3.eth.get_transaction(tx_hash)
            except TransactionNotFound:
                reachable = True           # endpoint works; tx just not here yet
                time.sleep(_RETRY_SLEEP)
                continue
            except Exception as exc:       # transport / HTTP error -> next endpoint
                last = exc
                break
            return receipt, tx
    if reachable:
        return None, None
    raise ConnectionError(f"no RPC reachable for chain {chain_id}: {last!r}")


def _hexstr(value) -> str:
    """Normalise a HexBytes / bytes / str to a lowercase 0x-less hex string.

    hexbytes 1.x (web3 7.16.0) returns '0x'-prefixed from .hex(); older
    releases did not. Take whichever and strip the prefix.
    """
    if hasattr(value, "hex"):
        value = value.hex()
    return str(value).lower().removeprefix("0x")


def verify_settlement(tx_hash: str, expected: ExpectedSettlement, network: int) -> VerifiedSettlement:
    receipt, tx = _receipt_and_tx(network, tx_hash)
    if receipt is None:
        raise SettlementNotConfirmed(tx_hash, "receipt not found after retries")

    usdc = Web3.to_checksum_address(USDC_BY_CHAIN[network])
    expected_atomic = int(expected.amount * Decimal(10) ** 6)
    transfer_topic = TRANSFER_TOPIC.lower().removeprefix("0x")

    transfer = None
    for log in receipt["logs"]:
        topics = log["topics"]
        if len(topics) < 3:
            continue
        if (Web3.to_checksum_address(log["address"]) == usdc
                and _hexstr(topics[0]) == transfer_topic):
            frm = Web3.to_checksum_address("0x" + _hexstr(topics[1])[-40:])
            to = Web3.to_checksum_address("0x" + _hexstr(topics[2])[-40:])
            value = int(_hexstr(log["data"]) or "0", 16)
            transfer = (frm, to, value)
            break

    status_ok = int(receipt["status"]) == 1
    submitted_by = Web3.to_checksum_address(tx["from"])
    payer_paid_gas = submitted_by.lower() == expected.payer.lower()

    mismatches = []
    if not status_ok:
        mismatches.append("receipt status != 1")
    if transfer is None:
        mismatches.append("no USDC Transfer log for the pinned token")
        frm = to = ""
        value = 0
    else:
        frm, to, value = transfer
        if frm.lower() != expected.payer.lower():
            mismatches.append(f"transfer from {frm} != expected payer {expected.payer}")
        if to.lower() != expected.pay_to.lower():
            mismatches.append(f"transfer to {to} != expected pay_to {expected.pay_to}")
        if value != expected_atomic:
            mismatches.append(f"amount {value} atomic != expected {expected_atomic}")
    if Web3.to_checksum_address(expected.asset) != usdc:
        mismatches.append("expected.asset != pinned USDC for this chain")

    return VerifiedSettlement(
        tx_hash=tx_hash,
        network=network,
        block_number=int(receipt["blockNumber"]),
        status_ok=status_ok,
        transfer_from=frm,
        transfer_to=to,
        amount_atomic=value,
        amount_usdc=Decimal(value) / Decimal(10) ** 6,
        submitted_by=submitted_by,
        payer_paid_gas=payer_paid_gas,
        matches_expected=not mismatches,
        mismatch="; ".join(mismatches) or None,
    )
