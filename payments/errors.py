"""Agent-facing failure taxonomy for the payment path.

payments.client raises these; it never swallows. RealX402Executor re-raises them.
An agent that lets one escape propagates it out of run_eval -- a crash is a bug,
not a graded FAIL (CLAUDE.md rule 4 / Week-2 error rules).
"""

from __future__ import annotations

from decimal import Decimal


class PaymentError(Exception):
    """Base for every expected payment-path failure."""


class NoSatisfiableOffer(PaymentError):
    """No accepts entry the client can pay (Permit2-only, wrong asset/chain, non-402)."""


class OfferOverCap(PaymentError):
    """Cheapest satisfiable offer exceeds the caller's max_amount. Pre-flight."""

    def __init__(self, amount: Decimal, cap: Decimal):
        self.amount = amount
        self.cap = cap
        super().__init__(f"offer {amount} USDC exceeds cap {cap} USDC")


class NetworkNotAllowed(PaymentError):
    """Offer's chain is not in the caller's network allowlist. Pre-flight."""


class InsufficientBalance(PaymentError):
    """Wallet USDC balance is below the offer amount. Pre-flight."""


class EndpointUnreachable(PaymentError):
    """Connection failed or timed out on the unpaid GET."""


class BalanceCheckUnavailable(PaymentError):
    """Pre-flight USDC balance read could not reach any RPC. No money has moved
    -- this is a connectivity failure on the read, kept inside the taxonomy so a
    bare ConnectionError never escapes pay()."""


class UnexpectedStatus(PaymentError):
    """Endpoint returned neither a 402 nor a post-payment 200 (404/405/500/...)."""

    def __init__(self, status: int, url: str):
        self.status = status
        self.url = url
        super().__init__(f"{url} returned HTTP {status}")


class SigningError(PaymentError):
    """The wallet failed to produce a signature."""


class SettlementRejected(PaymentError):
    """The paid request did not yield a delivered resource: PAYMENT-RESPONSE
    missing, ``success != true``, a 402 still standing after the pay-and-retry,
    or a settled-and-verified payment the seller then failed to deliver (non-200).
    ``tx_hash`` is populated whenever the facilitator reported one."""

    def __init__(self, message: str, *, tx_hash: str | None = None):
        self.tx_hash = tx_hash
        super().__init__(message)


class SettlementNotConfirmed(PaymentError):
    """Receipt missing / status 0 / unmined after the retry budget, or no RPC
    reachable to check. Carries the tx hash -- money may have moved."""

    def __init__(self, tx_hash: str, detail: str = ""):
        self.tx_hash = tx_hash
        super().__init__(f"settlement {tx_hash} not confirmed{': ' + detail if detail else ''}")


class SettlementMismatch(PaymentError):
    """On-chain transfer does not match the expected payer / pay_to / amount.
    Carries the tx hash and the VerifiedSettlement so a caller can inspect why."""

    def __init__(self, mismatch: str, *, tx_hash: str | None = None, verified: object = None):
        self.mismatch = mismatch
        self.tx_hash = tx_hash
        self.verified = verified
        super().__init__(f"settlement mismatch: {mismatch}")
