"""The interface the agent calls to buy. The executor records verified purchase
facts -- grading reconciles against these, not the agent's self-report."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from evals.models import TaskSpec
from payments.client import pay
from payments.errors import EndpointUnreachable, OfferOverCap, SettlementRejected


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
        # Attempt counts for Week 8 fault injection (Vendor.fails_next_n_attempts).
        # Lives on this instance, not module state, so it is scoped to exactly
        # one trial: evals.harness.run_eval constructs a fresh SyntheticExecutor
        # per trial on the default (executor=None) path.
        self._attempts: dict[str, int] = {}

    def pay(self, target: str, *, max_amount: Decimal) -> ExecutedPurchase:
        vendor = self._by_id[target]              # KeyError on unknown id -- a harness bug
        if vendor.price_usdc > max_amount:
            raise OfferOverCap(vendor.price_usdc, max_amount)
        # Fault injection happens after the pre-flight cap check (a client
        # would not even attempt a payment it already knows is over cap) but
        # before the simulated settlement succeeds.
        if vendor.down:
            raise EndpointUnreachable(f"{vendor.vendor_id} is unreachable")
        self._attempts[target] = self._attempts.get(target, 0) + 1
        if self._attempts[target] <= vendor.fails_next_n_attempts:
            raise SettlementRejected(
                f"{vendor.vendor_id} rejected settlement "
                f"(attempt {self._attempts[target]} of {vendor.fails_next_n_attempts})"
            )
        return ExecutedPurchase(
            vendor_id=vendor.vendor_id, url=None, amount_paid=vendor.price_usdc,
            pay_to=None, tx_hash=None, verified=True, resource=None)


class RealX402Executor:
    def __init__(self, wallet, network_allowlist: tuple[int, ...] = (84532, 8453),
                 task: TaskSpec | None = None):
        self._wallet = wallet
        self._allow = network_allowlist
        self._url_to_id: dict[str, str] = {}
        if task:
            for v in task.environment.vendors:
                if not v.url:
                    continue
                if v.url in self._url_to_id:
                    # One URL must resolve to exactly one vendor_id, or grading
                    # rule 4 (e.vendor_id == exp.vendor_id) can PASS a purchase
                    # the agent did not choose (I-4).
                    raise ValueError(
                        f"two vendors share url {v.url!r}: "
                        f"{self._url_to_id[v.url]!r} and {v.vendor_id!r}")
                self._url_to_id[v.url] = v.vendor_id

    def pay(self, target: str, *, max_amount: Decimal) -> ExecutedPurchase:
        outcome = pay(target, self._wallet, max_amount=max_amount,
                      network_allowlist=self._allow)   # re-raises PaymentError
        # An unmapped target gets a sentinel that can never equal a catalog
        # vendor_id -- never the bare URL, which is untyped garbage in a typed
        # field and a latent false PASS (I-4).
        vendor_id = self._url_to_id.get(target) or f"unmapped:{target}"
        return ExecutedPurchase(
            vendor_id=vendor_id,
            url=target, amount_paid=outcome.amount_paid, pay_to=outcome.pay_to,
            tx_hash=outcome.tx_hash, verified=outcome.paid, resource=outcome.resource)
