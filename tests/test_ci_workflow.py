from pathlib import Path

import yaml

WF = Path(".github/workflows/evals.yml")


def _load():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))


def test_workflow_parses_and_has_both_jobs():
    jobs = _load()["jobs"]
    assert "harness-tests" in jobs
    assert "stub-eval-report" in jobs


def test_gating_job_runs_pytest():
    steps = _load()["jobs"]["harness-tests"]["steps"]
    assert any("pytest" in str(step.get("run", "")) for step in steps)


def test_gating_job_actually_gates():
    # continue-on-error: true on harness-tests would silently disarm the whole
    # gate while the suite stayed green.
    job = _load()["jobs"]["harness-tests"]
    assert job.get("continue-on-error") in (None, False)


def test_report_job_is_non_gating():
    job = _load()["jobs"]["stub-eval-report"]
    assert job.get("continue-on-error") is True
    assert job.get("needs") == "harness-tests"


def test_report_job_has_no_pass_rate_threshold():
    job = _load()["jobs"]["stub-eval-report"]
    blob = yaml.safe_dump(job).lower()
    for banned in ("--min-pass", "threshold", "fail-under", "pass_rate", "assert report.pass"):
        assert banned not in blob, f"report job must not gate on a pass rate; found {banned!r}"
