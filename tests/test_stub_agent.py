from decimal import Decimal

from evals.agents.stub import run_task
from evals.agent_protocol import require_agent_id
from evals.executor import SyntheticExecutor
from evals.grading import GradeOutcome, grade
from evals.harness import run_eval


def test_stub_has_id():
    assert require_agent_id(run_task) == "stub-v0"


def test_stub_returns_failing_shape(sample_task):
    result = run_task(sample_task, 0, SyntheticExecutor(sample_task))
    assert result.purchases == []
    assert [e.reason for e in result.escalations] == ["not_implemented"]
    assert result.touchpoints == 2
    assert result.cost_usdc == Decimal("0")


def test_stub_grades_fail_on_sample(sample_task):
    assert grade(run_task(sample_task, 0, SyntheticExecutor(sample_task)), sample_task) is GradeOutcome.FAIL


def test_stub_eval_scores_zero(sample_task):
    report = run_eval(sample_task, run_task, n_trials=8)
    assert report.pass_1 == 0.0
    assert report.pass_k == {4: 0.0, 8: 0.0}
    assert report.budget_violations == 0
    assert report.best_price_capture_rate == 0.0
    assert report.escalation_rate == 1.0
    assert report.escalation_reasons == {"not_implemented": 8}
    assert report.cost_per_completed_tx_usdc is None
    assert report.touchpoints_per_basket == 2.0
