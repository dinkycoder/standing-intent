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
        assert report.pass_1 == 0.0
        assert report.pass_k == {4: 0.0, 8: 0.0}
        assert report.budget_violations == 0
        assert report.escalation_rate == 1.0
        assert report.escalation_reasons == {"not_implemented": 8}


def test_report_filenames_carry_task_id_and_date(tmp_path):
    out = tmp_path / "results"
    reports = main(task_dir=Path("evals/tasks"), out_dir=out, n_trials=8)
    names = {p.name for p in out.glob("*.json")}
    for report in reports:
        assert any(n.startswith(f"{report.task_id}_") and n.endswith(".json") for n in names)
