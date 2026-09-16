"""Run claude-planner-v1 against every SYNTHETIC task spec and write EvalReports.

LIVE, COST-BEARING, NOT CI-GATED. Each run makes real, billed Claude API
calls (see docs/superpowers/specs/2026-09-15-week5-planner-v1-design.md,
"Testing"). Requires ANTHROPIC_API_KEY. Mirrors scripts/run_stub_evals.py's
structure and, like it, skips real_x402 task specs -- those need a funded
wallet and a live seller (tests/test_harness_real_x402.py), a separate
concern from "does the LLM call work."
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow `python scripts/run_claude_planner_evals.py` from the repo root:
# Python only puts this file's directory on sys.path, not the repo root, so
# `import evals` would fail. Running as
# `python -m scripts.run_claude_planner_evals` or under pytest is fine
# without this; the shim just makes direct execution work too.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.agents.claude_planner import run_task as claude_planner_run_task
from evals.harness import run_eval
from evals.models import EvalReport, TaskSpec


def main(
    task_dir: Path = Path("evals/tasks"),
    out_dir: Path = Path("evals/results"),
    n_trials: int = 8,
) -> list[EvalReport]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ANTHROPIC_API_KEY is not set -- this script makes real, billed "
            "Claude API calls. Set it (see .env.example) and re-run."
        )
        return []

    out_dir.mkdir(parents=True, exist_ok=True)
    reports: list[EvalReport] = []

    for path in sorted(Path(task_dir).glob("*.json")):
        task = TaskSpec.from_json_file(path)
        if task.environment.kind != "synthetic":
            continue
        report = run_eval(task, claude_planner_run_task, n_trials=n_trials)
        out_path = out_dir / f"{report.task_id}_{report.date_utc}.json"
        out_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        reports.append(report)

    _print_table(reports)
    return reports


def _print_table(reports: list[EvalReport]) -> None:
    header = (
        f"{'task_id':<34} {'pass^1 (95% CI)':>20} {'pass^4':>7} {'pass^8':>7} "
        f"{'tp/bskt':>8} {'budget_viol':>12} {'esc_rate':>9} {'cost/tx':>9}"
    )
    print(header)
    print("-" * len(header))
    for r in reports:
        lo, hi = r.pass_1_ci
        pass_1_col = f"{r.pass_1:.2f} [{lo:.2f}, {hi:.2f}]"
        cost_col = (
            f"{r.cost_per_completed_tx_usdc:.6f}"
            if r.cost_per_completed_tx_usdc is not None
            else "n/a"
        )
        print(
            f"{r.task_id:<34} "
            f"{pass_1_col:>20} "
            f"{r.pass_k.get(4, 0.0):>7.2f} "
            f"{r.pass_k.get(8, 0.0):>7.2f} "
            f"{r.touchpoints_per_basket:>8.2f} "
            f"{r.budget_violations:>12d} "
            f"{r.escalation_rate:>9.2f} "
            f"{cost_col:>9}"
        )
    print()
    print(
        "LIVE RUN -- real, billed Claude API calls. Not gated in CI; run by "
        "hand and record results in a docs/week5-*.md file, matching Week "
        "4's live-verification convention (docs/week4-spend-permission-live-verification.md)."
    )


if __name__ == "__main__":
    main()
