from decimal import Decimal

from evals.models import EvalReport, VendorOutcome
from scripts.report_vendor_reliability import main


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


def test_main_aggregates_reports_in_the_given_directory(tmp_path):
    _write_report(tmp_path / "r1.json", {"v1": VendorOutcome(successes=4, failures=0)})

    scores = main(results_dir=tmp_path)

    assert scores["v1"]["successes"] == 4
    assert scores["v1"]["failures"] == 0
    assert scores["v1"]["mean"] > 0.8


def test_main_returns_empty_dict_for_a_directory_with_no_reports(tmp_path):
    assert main(results_dir=tmp_path) == {}
