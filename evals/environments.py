"""Resolve a task's declared environment to the executor that runs its buys.

A task's ``environment.kind`` picks the payment path: ``"synthetic"`` pays
against the in-spec vendor catalog (no chain, no wallet); ``"real_x402"`` pays a
live x402 endpoint and needs a funded wallet.
"""

from __future__ import annotations

from evals.executor import PaymentExecutor, RealX402Executor, SyntheticExecutor
from evals.models import TaskSpec


def resolve_executor(task: TaskSpec, wallet=None,
                     network_allowlist: tuple[int, ...] = (84532, 8453)) -> PaymentExecutor:
    if task.environment.kind == "real_x402":
        if wallet is None:
            raise ValueError("real_x402 environment needs a wallet")
        return RealX402Executor(wallet, network_allowlist, task)
    return SyntheticExecutor(task)
