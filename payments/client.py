"""x402 pay flow: inspect_offer/parse_terms discover and price an offer; pay()
drives the x402 SDK session (402 -> sign -> retry) then verifies settlement
on-chain before returning. paid=True only after verify_settlement matches."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import requests

from payments.constants import USDC_BY_CHAIN
from payments.errors import (
    EndpointUnreachable, InsufficientBalance, NetworkNotAllowed, NoSatisfiableOffer,
    OfferOverCap, SettlementMismatch, SettlementRejected, UnexpectedStatus,
)
from payments.settlement import ExpectedSettlement, VerifiedSettlement, verify_settlement
from payments.wallet import Wallet

_KNOWN_BASE = {"base": 8453, "base-sepolia": 84532}


@dataclass(frozen=True)
class Offer:
    scheme: str
    network: str
    chain_id: int | None
    asset: str
    amount: Decimal
    pay_to: str
    max_timeout_seconds: int
    transfer_method: str
    satisfiable: bool
    unsatisfiable_reason: str | None


@dataclass(frozen=True)
class PaymentQuote:
    url: str
    x402_version: int
    offers: tuple[Offer, ...]
    best_satisfiable: Offer | None
    raw_terms: dict


def _chain_id_of(network: str) -> int | None:
    if not network:
        return None
    if network.startswith("eip155:"):
        try:
            return int(network.split(":", 1)[1])
        except ValueError:
            return None
    return _KNOWN_BASE.get(network)


def _offer_from_entry(entry: dict) -> Offer:
    network = str(entry.get("network", ""))
    chain_id = _chain_id_of(network)
    asset = str(entry.get("asset", ""))
    raw_amount = entry.get("amount", "0")
    try:
        amount = Decimal(str(raw_amount)) / Decimal(10) ** 6
        amount_ok = True
    except (InvalidOperation, TypeError):
        amount = Decimal(0)
        amount_ok = False
    extra = entry.get("extra") or {}
    transfer_method = extra.get("assetTransferMethod") or "transferWithAuthorization"

    reason = None
    if not amount_ok:
        reason = f"unparseable amount: {raw_amount!r}"
    elif entry.get("scheme") != "exact":
        reason = f"scheme {entry.get('scheme')!r} not supported"
    elif chain_id not in USDC_BY_CHAIN:
        reason = f"network {network!r} is not a supported Base chain"
    elif asset.lower() != USDC_BY_CHAIN[chain_id].lower():
        reason = "asset is not the pinned USDC for this chain"
    elif transfer_method != "transferWithAuthorization":
        reason = f"{transfer_method} transfer method not supported yet"

    return Offer(
        scheme=str(entry.get("scheme", "")),
        network=network,
        chain_id=chain_id,
        asset=asset,
        amount=amount,
        pay_to=str(entry.get("payTo", "")),
        max_timeout_seconds=int(entry.get("maxTimeoutSeconds", 0)),
        transfer_method=transfer_method,
        satisfiable=reason is None,
        unsatisfiable_reason=reason,
    )


def parse_terms(raw_terms: dict, url: str) -> PaymentQuote:
    version = int(raw_terms.get("x402Version", 1))
    entries = raw_terms.get("accepts") or []
    offers = tuple(_offer_from_entry(e) for e in entries)
    satisfiable = [o for o in offers if o.satisfiable]
    best = min(satisfiable, key=lambda o: o.amount) if satisfiable else None
    return PaymentQuote(url=url, x402_version=version, offers=offers,
                        best_satisfiable=best, raw_terms=raw_terms)


def _decode_header(value: str) -> dict:
    return json.loads(base64.b64decode(value))


def inspect_offer(url: str, *, timeout: float = 20) -> PaymentQuote:
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise EndpointUnreachable(str(exc)) from exc

    header = resp.headers.get("payment-required")
    if header:
        try:
            decoded = _decode_header(header)
        except (ValueError, binascii.Error):
            # Malformed base64 / non-JSON header (json.JSONDecodeError and
            # binascii.Error are both ValueError subclasses; name both for intent).
            decoded = None
        if isinstance(decoded, dict):
            return parse_terms(decoded, url)
        # Header decoded but is not an object (array / string / null / bad b64):
        # not payment terms. Degrade as if absent -> JSON-body accepts fallback,
        # then UnexpectedStatus. inspect_offer only ever raises EndpointUnreachable
        # or UnexpectedStatus, or returns a PaymentQuote.
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and "accepts" in body:
        return parse_terms(body, url)

    if resp.status_code == 402:
        # 402 but no parseable terms anywhere
        return PaymentQuote(url=url, x402_version=1, offers=(), best_satisfiable=None, raw_terms={})
    raise UnexpectedStatus(resp.status_code, url)


@dataclass(frozen=True)
class PaymentOutcome:
    url: str
    paid: bool
    offer: Offer
    tx_hash: str
    network: int
    amount_paid: Decimal
    pay_to: str
    resource: object
    verified: VerifiedSettlement
    quote: PaymentQuote


def pay(url: str, wallet: Wallet, *, max_amount: Decimal,
        network_allowlist: tuple[int, ...] = (84532, 8453),
        timeout: float = 30) -> PaymentOutcome:
    quote = inspect_offer(url, timeout=timeout)
    offer = quote.best_satisfiable
    if offer is None:
        raise NoSatisfiableOffer(f"{url}: no satisfiable accepts entry")
    if offer.amount > max_amount:
        raise OfferOverCap(offer.amount, max_amount)
    if offer.chain_id not in network_allowlist:
        raise NetworkNotAllowed(f"{offer.network} not in {network_allowlist}")
    if wallet.usdc_balance(offer.chain_id) < offer.amount:
        raise InsufficientBalance(f"balance < {offer.amount} USDC on chain {offer.chain_id}")

    from x402 import x402ClientSync
    from x402.http import x402HTTPClientSync
    from x402.http.clients import x402_requests
    from x402.mechanisms.evm.exact.register import register_exact_evm_client

    x_client = x402ClientSync().set_spend_controls({"max_amount_per_payment": f"${max_amount}"})
    register_exact_evm_client(x_client, wallet.x402_signer())
    http_client = x402HTTPClientSync(x_client)

    with x402_requests(x_client) as session:
        resp = session.get(url, timeout=timeout)

    if resp.status_code != 200:
        raise UnexpectedStatus(resp.status_code, url)

    try:
        settle = http_client.get_payment_settle_response(lambda name: resp.headers.get(name))
    except ValueError as exc:
        raise SettlementRejected(f"no PAYMENT-RESPONSE from {url}") from exc

    if not getattr(settle, "success", False):
        raise SettlementRejected(f"facilitator reported success != true for {url}")
    tx_hash = getattr(settle, "transaction", None)
    if not tx_hash:
        raise SettlementRejected(f"PAYMENT-RESPONSE for {url} carried no transaction hash")

    verified = verify_settlement(
        tx_hash,
        ExpectedSettlement(payer=wallet.address, pay_to=offer.pay_to,
                           asset=offer.asset, amount=offer.amount),
        network=offer.chain_id,
    )
    if not verified.matches_expected:
        raise SettlementMismatch(verified.mismatch or "unknown")

    try:
        resource = resp.json()
    except ValueError:
        resource = resp.content

    return PaymentOutcome(
        url=url, paid=True, offer=offer, tx_hash=tx_hash, network=offer.chain_id,
        amount_paid=verified.amount_usdc, pay_to=verified.transfer_to,
        resource=resource, verified=verified, quote=quote,
    )
