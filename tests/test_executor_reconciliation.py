from decimal import Decimal

from evals.agent_protocol import agent
from evals.harness import run_eval
from evals.models import AgentResult, Purchase


@agent("honest")
def honest(task, rng_seed, executor):
    p = executor.pay("v1", max_amount=Decimal("0.05"))
    return AgentResult(purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
                       touchpoints=1)


@agent("liar")
def liar(task, rng_seed, executor):
    # claims a purchase it never executed
    return AgentResult(purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))],
                       touchpoints=1)


@agent("overpay-liar")
def overpay_liar(task, rng_seed, executor):
    executor.pay("v1", max_amount=Decimal("0.05"))          # really buys at 0.01
    return AgentResult(purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.005"))],
                       touchpoints=1)                        # but claims a different price


def test_honest_agent_passes_on_verified_amount(sample_task):
    report = run_eval(sample_task, honest, n_trials=8)
    assert report.pass_1 == 1.0
    assert report.unverified_claims == 0
    assert report.best_price_capture_rate == 1.0


def test_fabricated_claim_is_flagged(sample_task):
    report = run_eval(sample_task, liar, n_trials=8)
    assert report.pass_1 == 0.0
    assert report.unverified_claims == 8


def test_price_misreport_is_flagged(sample_task):
    report = run_eval(sample_task, overpay_liar, n_trials=8)
    assert report.unverified_claims == 8
