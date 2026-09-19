from decimal import Decimal

import pytest

from evals.ml.reliability import (
    beta_update,
    posterior_mean,
    vendor_reliability_from_reports,
)
from evals.models import EvalReport, VendorOutcome


def test_beta_update_success_increments_alpha():
    assert beta_update(1, 1, success=True) == (2, 1)


def test_beta_update_failure_increments_beta():
    assert beta_update(1, 1, success=False) == (1, 2)


def test_posterior_mean():
    assert posterior_mean(2, 1) == pytest.approx(2 / 3)
    assert posterior_mean(1, 1) == pytest.approx(0.5)


def _write_report(path, vendor_outcomes):
    report = EvalReport(
        task_id="t", agent_id="a", date_utc="2026-09-19", base_seed=0,
        n_trials=1, outcomes=["pass"], pass_1=1.0, pass_1_ci=(0.0, 1.0),
        pass_k={}, pass_k_ci={}, touchpoints_per_basket=1.0, budget_violations=0,
        best_price_capture_rate=None, best_price_capture_rate_ci=None,
        cost_per_completed_tx_usdc=Decimal("0"), escalation_rate=0.0,
        escalation_reasons={}, unverified_claims=0, settled_tx_hashes=[],
        vendor_outcomes=vendor_outcomes,
    )
    path.write_text(report.model_dump_json(), encoding="utf-8")


def test_vendor_reliability_from_reports_folds_a_single_file(tmp_path):
    path = tmp_path / "r1.json"
    _write_report(path, {"v1": VendorOutcome(successes=3, failures=1)})

    result = vendor_reliability_from_reports([path])

    # prior (1,1) + 3 successes + 1 failure -> alpha=4, beta=2
    assert result["v1"]["alpha"] == 4
    assert result["v1"]["beta"] == 2
    assert result["v1"]["mean"] == pytest.approx(4 / 6)
    assert result["v1"]["successes"] == 3
    assert result["v1"]["failures"] == 1
    assert result["v1"]["n_observations"] == 4


def test_vendor_reliability_from_reports_folds_across_multiple_files(tmp_path):
    path1 = tmp_path / "r1.json"
    path2 = tmp_path / "r2.json"
    _write_report(path1, {"v1": VendorOutcome(successes=2, failures=0)})
    _write_report(path2, {"v1": VendorOutcome(successes=1, failures=1)})

    result = vendor_reliability_from_reports([path1, path2])

    assert result["v1"]["successes"] == 3
    assert result["v1"]["failures"] == 1
    assert result["v1"]["n_observations"] == 4


def test_vendor_reliability_from_reports_keeps_vendors_separate(tmp_path):
    path = tmp_path / "r1.json"
    _write_report(path, {
        "v1": VendorOutcome(successes=5, failures=0),
        "v2": VendorOutcome(successes=0, failures=5),
    })

    result = vendor_reliability_from_reports([path])

    assert result["v1"]["mean"] > 0.8
    assert result["v2"]["mean"] < 0.2


def test_vendor_reliability_from_reports_empty_list_returns_empty_dict():
    assert vendor_reliability_from_reports([]) == {}
