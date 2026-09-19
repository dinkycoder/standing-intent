"""Run the stub agent against every shipped task spec and write EvalReports.

REPORTING ONLY. The stub is expected to score pass^1 = 0, except on
no_in_policy_vendor_escalates and price_anomaly_escalates, where its blanket
escalation happens to match each task's correct terminal state (see
grading.py's expected_purchase=None branch). This script never fails the
build and must never grow a pass-rate threshold — see CLAUDE.md and
docs/superpowers/specs/2026-09-02-eval-harness-design.md. The gate activates
when a real agent is registered (Week 5+).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `python scripts/run_stub_evals.py` from the repo root: Python only puts
# this file's directory on sys.path, not the repo root, so `import evals` would
# fail. Running as `python -m scripts.run_stub_evals` or under pytest is fine
# without this; the shim just makes direct execution work too.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.agents.stub import run_task as stub_run_task
from evals.harness import run_eval
from evals.models import EvalReport, TaskSpec


def main(
    task_dir: Path = Path("evals/tasks"),
    out_dir: Path = Path("evals/results"),
    n_trials: int = 8,
) -> list[EvalReport]:
    out_dir.mkdir(parents=True, exist_ok=True)
    reports: list[EvalReport] = []

    for path in sorted(Path(task_dir).glob("*.json")):
        task = TaskSpec.from_json_file(path)
        # REPORTING ONLY, no wallet: real_x402 specs pay a live endpoint and
        # resolve_executor(task, wallet=None) raises for them. The stub scores
        # pass^1 = 0 regardless of environment, so skipping them loses nothing.
        if task.environment.kind != "synthetic":
            continue
        report = run_eval(task, stub_run_task, n_trials=n_trials)
        # agent_id is in the filename so this script and
        # scripts/run_claude_planner_evals.py cannot overwrite each other's
        # report for the same task on the same day.
        out_path = out_dir / f"{report.task_id}_{report.agent_id}_{report.date_utc}.json"
        out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        reports.append(report)

    _print_table(reports)
    return reports


def _print_table(reports: list[EvalReport]) -> None:
    header = (
        f"{'task_id':<34} {'pass^1 (95% CI)':>20} {'pass^4':>7} {'pass^8':>7} "
        f"{'tp/bskt':>8} {'budget_viol':>12} {'esc_rate':>9}"
    )
    print(header)
    print("-" * len(header))
    for r in reports:
        lo, hi = r.pass_1_ci
        pass_1_col = f"{r.pass_1:.2f} [{lo:.2f}, {hi:.2f}]"
        print(
            f"{r.task_id:<34} "
            f"{pass_1_col:>20} "
            f"{r.pass_k.get(4, 0.0):>7.2f} "
            f"{r.pass_k.get(8, 0.0):>7.2f} "
            f"{r.touchpoints_per_basket:>8.2f} "
            f"{r.budget_violations:>12d} "
            f"{r.escalation_rate:>9.2f}"
        )
    print()
    print(
        "REPORTING ONLY - stub agent, pass^1 = 0 is expected and correct. "
        "This run does not gate the build."
    )


if __name__ == "__main__":
    main()
