"""One real payment against a live Bazaar endpoint on Base MAINNET, exercising the
permanent payments/ module. Run by hand:

    python -m pytest tests/test_payments_mainnet_gate.py -m manual -s

Requires X402_WALLET_KEY pointing at a mainnet-funded throwaway wallet
(0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0 holds ~1.999 USDC). Record the
result in docs/week3-mainnet-gate.md.
"""
import os
from decimal import Decimal

import pytest

from payments.client import pay
from payments.wallet import LocalWallet

pytestmark = pytest.mark.manual

ENDPOINT = os.environ.get("W3_GATE_ENDPOINT", "https://x402.ottoai.services/crypto-news")


@pytest.mark.skipif(not os.environ.get("X402_WALLET_KEY"), reason="X402_WALLET_KEY unset")
def test_one_real_mainnet_settlement():
    wallet = LocalWallet.from_env()
    outcome = pay(ENDPOINT, wallet, max_amount=Decimal("0.01"), network_allowlist=(8453,))
    assert outcome.paid is True
    assert outcome.chain_id == 8453
    assert outcome.verified.matches_expected is True
    assert outcome.verified.payer_paid_gas is False
    print(f"\nMAINNET GATE: tx={outcome.tx_hash} amount={outcome.amount_paid} "
          f"pay_to={outcome.pay_to} block={outcome.verified.block_number}")
