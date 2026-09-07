# evals/

The evaluation harness. It is the specification for the whole project: no agent
capability is built before a failing eval task exists for it (`CLAUDE.md` rule 3).

## Layout

| Path | What |
|---|---|
| `models.py` | Typed task-spec / result / report structures. All money is `Decimal`; a `float` in a money field raises. |
| `agent_protocol.py` | The `run_task(task, rng_seed) -> AgentResult` contract and the `@agent("id")` decorator. |
| `grading.py` | Pure terminal-state grading -> `PASS` / `FAIL` / `BUDGET_VIOLATION`. |
| `harness.py` | `run_eval(task, agent_fn, n_trials)` -> `EvalReport`. Computes `pass^1`, `pass^k` (k=4,8), and the day-one counters. |
| `agents/stub.py` | The Week-2 agent under test. Always fails. |
| `tasks/*.json` | Synthetic procurement tasks: a mandate + an in-memory vendor catalog + grading criteria. No network, no chain. |
| `results/` | Run artifacts (git-ignored). |

## Run the stub eval

```powershell
python scripts/run_stub_evals.py
```

Writes `evals/results/<task_id>_<date>.json` and prints a summary table. The stub
scores `pass^1 = 0` by design.

## Add a task spec

Create `evals/tasks/<task_id>.json` matching `TaskSpec` in `models.py`. All USDC
amounts are decimal strings (`"0.05"`, never `0.05`). `tests/test_task_specs.py`
checks every shipped spec loads and that its `grading.expected_purchase` really
is the cheapest in-policy, in-category vendor within budget.

## Test

```powershell
python -m pytest -v
```

`tests/test_grading.py` and `tests/test_harness.py` are the gate: they prove the
harness does not lie to itself.
