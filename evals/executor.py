"""The interface the agent calls to buy. The executor records verified purchase
facts -- grading reconciles against these, not the agent's self-report."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from evals.models import TaskSpec
from payments.client import pay
from payments.errors import OfferOverCap


@dataclass(frozen=True)
class ExecutedPurchase:
    vendor_id: str
    url: str | None
    amount_paid: Decimal
    pay_to: str | None
    tx_hash: str | None
    verified: bool
    resource: object | None


@runtime_checkable
class PaymentExecutor(Protocol):
    def pay(self, target: str, *, max_amount: Decimal) -> ExecutedPurchase: ...


class SyntheticExecutor:
    def __init__(self, task: TaskSpec):
        self._by_id = {v.vendor_id: v for v in task.environment.vendors}

    def pay(self, target: str, *, max_amount: Decimal) -> ExecutedPurchase:
        vendor = self._by_id[target]              # KeyError on unknown id -- a harness bug
        if vendor.price_usdc > max_amount:
            raise OfferOverCap(vendor.price_usdc, max_amount)
        return ExecutedPurchase(
            vendor_id=vendor.vendor_id, url=None, amount_paid=vendor.price_usdc,
            pay_to=None, tx_hash=None, verified=True, resource=None)


class RealX402Executor:
    def __init__(self, wallet, network_allowlist: tuple[int, ...] = (84532, 8453),
                 task: TaskSpec | None = None):
        self._wallet = wallet
        self._allow = network_allowlist
        self._url_to_id = (
            {v.url: v.vendor_id for v in task.environment.vendors if v.url}
            if task else {})

    def pay(self, target: str, *, max_amount: Decimal) -> ExecutedPurchase:
        outcome = pay(target, self._wallet, max_amount=max_amount,
                      network_allowlist=self._allow)   # re-raises PaymentError
        return ExecutedPurchase(
            vendor_id=self._url_to_id.get(target, target),
            url=target, amount_paid=outcome.amount_paid, pay_to=outcome.pay_to,
            tx_hash=outcome.tx_hash, verified=outcome.paid, resource=outcome.resource)
