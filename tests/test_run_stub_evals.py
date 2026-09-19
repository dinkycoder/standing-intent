from pathlib import Path

from evals.models import EvalReport
from scripts.run_stub_evals import main


def test_writes_one_report_per_task(tmp_path):
    out = tmp_path / "results"
    reports = main(task_dir=Path("evals/tasks"), out_dir=out, n_trials=8)

    written = sorted(out.glob("*.json"))
    assert len(written) == len(reports) >= 4

    for path in written:
        report = EvalReport.model_validate_json(path.read_text(encoding="utf-8"))
        assert report.agent_id == "stub-v0"
        assert report.budget_violations == 0
        assert report.escalation_rate == 1.0
        assert report.escalation_reasons == {"not_implemented": 8}
        if report.task_id in ("no_in_policy_vendor_escalates", "price_anomaly_escalates"):
            # The stub always escalates with zero purchases -- which happens
            # to be the correct terminal state for both of these tasks (no
            # valid purchase exists), so it passes here for the right STATE
            # but the wrong REASON: it never distinguishes a real vendor set
            # from an empty one, nor a genuine anomaly from a normal offer.
            # See the Week-5 design spec's "Known limitations".
            assert report.pass_1 == 1.0
        else:
            assert report.pass_1 == 0.0
            assert report.pass_k == {4: 0.0, 8: 0.0}


def test_report_filenames_carry_task_id_agent_id_and_date(tmp_path):
    # agent_id is part of the name: without it this script and
    # scripts/run_claude_planner_evals.py write the same path for the same
    # task on the same day, and the second run silently destroys the first.
    out = tmp_path / "results"
    reports = main(task_dir=Path("evals/tasks"), out_dir=out, n_trials=8)
    names = {p.name for p in out.glob("*.json")}
    for report in reports:
        assert f"{report.task_id}_{report.agent_id}_{report.date_utc}.json" in names
