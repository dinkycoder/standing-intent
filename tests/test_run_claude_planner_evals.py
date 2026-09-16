from pathlib import Path

from scripts.run_claude_planner_evals import main


def test_requires_api_key_and_makes_no_network_call(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "results"
    reports = main(task_dir=Path("evals/tasks"), out_dir=out, n_trials=1)
    assert reports == []
    # out_dir must never be created when the guard trips -- a later run with
    # the key set should not find a stale empty directory implying success.
    assert not out.exists()
