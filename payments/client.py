"""x402 pay flow. inspect_offer/parse_terms here; pay() is added in the next task."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from decimal import Decimal

import requests

from payments.constants import USDC_BY_CHAIN
from payments.errors import EndpointUnreachable, UnexpectedStatus

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
    amount = Decimal(str(entry.get("amount", "0"))) / Decimal(10) ** 6
    extra = entry.get("extra") or {}
    transfer_method = extra.get("assetTransferMethod") or "transferWithAuthorization"

    reason = None
    if entry.get("scheme") != "exact":
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
        return parse_terms(_decode_header(header), url)
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
