import os
from decimal import Decimal
from pathlib import Path

import pytest

from evals.agent_protocol import agent
from evals.environments import resolve_executor
from evals.harness import run_eval
from evals.models import AgentResult, Purchase, TaskSpec
from payments.testing.fixtures import wire_real_x402_task, x402_seller  # noqa: F401
from payments.wallet import LocalWallet

pytestmark = pytest.mark.integration
skip_no_key = pytest.mark.skipif(not os.environ.get("X402_WALLET_KEY"), reason="X402_WALLET_KEY unset")


@agent("real-buyer")
def real_buyer(task, _rng_seed, executor):
    vendor = task.environment.vendors[0]
    p = executor.pay(vendor.url, max_amount=Decimal("0.05"))
    return AgentResult(purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
                       touchpoints=1)


@skip_no_key
def test_real_x402_task_grades_a_real_settlement(x402_seller):
    task = TaskSpec.from_json_file(Path("evals/tasks/real_weather_sepolia.json"))
    task = wire_real_x402_task(task, x402_seller)
    wallet = LocalWallet.from_env()
    report = run_eval(task, real_buyer, n_trials=1,
                      executor=resolve_executor(task, wallet=wallet, network_allowlist=(84532,)))
    assert report.pass_1 == 1.0
    assert report.unverified_claims == 0
    assert len(report.settled_tx_hashes) == 1 and report.settled_tx_hashes[0].startswith("0x")
