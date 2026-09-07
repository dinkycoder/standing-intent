# Week 3 Payments Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the permanent `payments/` module the agent calls to buy — wallet abstraction, x402 pay flow with pre-flight offer inspection, standalone on-chain settlement verification — and wire it into the eval harness so evals grade a verified purchase instead of an agent's self-report.

**Architecture:** New top-level `payments/` package, peer of `evals/`, one-directional dependency `evals/ → payments/ → (x402 SDK, eth-account, web3)`. The pay flow is a thin wrapper over the x402 SDK's `x402_requests` session plus our own unpaid-GET inspection. Settlement verification is a standalone read-only function `pay` calls and the harness calls independently. Harness gains a `PaymentExecutor` the agent invokes, a `real_x402` environment backed by a checked-in Flask test seller, and grading that reconciles claimed purchases against verified settlements.

**Tech Stack:** Python 3.12, pydantic v2 (eval models), `decimal.Decimal` for all money, `x402[requests,evm,flask]` pinned by git URL, `web3` + `eth-account` (read RPC + signing), Flask (test seller), pytest with `integration` / `manual` markers, GitHub Actions (existing `evals.yml`).

**Spec:** `docs/superpowers/specs/2026-09-07-payments-spine-design.md` — read it alongside this plan. This plan argues from that spec.

## Global Constraints

Every task's requirements implicitly include this section. Values copied verbatim from the spec, `CLAUDE.md`, and `.claude/agents/payments.md` / `.claude/agents/tests.md`.

- **Non-custody (CLAUDE.md rule 1).** This milestone moves only the agent's own throwaway USDC to vendors, directly. No user funds. If any step would have the codebase hold a key over *user* funds, pool multiple users' funds, receive-and-forward, or take a fee inside the payment tx — STOP, say which tripwire, do not implement.
- **No unverified on-chain constants (CLAUDE.md rule 2).** Every contract address / chain id / token address / facilitator URL carries a primary-source-URL comment AND a test that reads it on chain and asserts something only the real value would return. If a value can't be verified, write `# UNVERIFIED — do not use` and say so. No constant from prose or memory.
- **Money is never a float.** All USDC amounts are `decimal.Decimal`. Atomic ↔ whole conversion is `/ 10**6` (USDC has 6 decimals — never `10**18`). Amount comparisons for the `exact` scheme are exact.
- **A 200 is not proof of settlement.** `PaymentOutcome.paid` is `True` only after `verify_settlement` reconciles the on-chain USDC `Transfer`. `amount_paid` / `pay_to` on the outcome come from the verified Transfer log, not the SDK's `PAYMENT-RESPONSE` claim.
- **A crash / infra failure is a bug, not a graded FAIL.** `payments` functions raise `PaymentError` subclasses; they never swallow. `RealX402Executor` re-raises. An agent that lets a `PaymentError` escape propagates it out of `run_eval` — never recorded as `FAIL`.
- **x402 SDK provenance.** The canonical source is `x402-foundation/x402`, Python in `python/x402`. The PyPI `x402` name is polluted — do not `pip install x402` from PyPI. Pin the git URL at commit `e398a9e`.
- **Secrets.** Keys come from environment variables (`X402_WALLET_KEY`). Never a key literal in code. If you find one, remove it and say so.
- **Backward compatibility.** Week-2 code is on `main`. Changing `run_task` / `grade` / `run_eval` / the eval models must keep the existing suite green at every task boundary. Week-2 task specs omit `Environment.kind` → must default to `"synthetic"` → unchanged behavior.
- **Test tiers.** CI tests are fast, deterministic, read-only or offline. Tests needing testnet funds or a live seller are `@pytest.mark.integration`. The one real mainnet payment is `@pytest.mark.manual`. `pytest.ini`/`pyproject.toml` default `addopts` excludes both markers, so `python -m pytest` (local + CI) skips them.
- **Environment:** Windows / PowerShell. `python -m pytest` from the repo root, never bare `pytest`. Directories: `New-Item -ItemType Directory -Force <dir>` (safe on a dir; the CLAUDE.md ban is `-Force` on a *file*).
- **Commits:** one per task, imperative subject matching repo history. End every commit message with:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: <this session's URL>
  ```
- **Deliberate spec deviations** (none pre-approved; if the plan and spec conflict during execution, the spec wins and the controller rules).

---

## File Structure

```
requirements.txt                    # + x402[requests,evm,flask] @ git+... ; web3 ; eth-account
requirements-dev.txt                # unchanged (pytest, PyYAML)
pyproject.toml                      # addopts gains -m filter; markers registered
.env.example                        # NEW — X402_WALLET_KEY, BASE_{SEPOLIA,MAINNET}_RPC_URL

payments/
  __init__.py                       # empty marker
  constants.py                      # USDC_*, CHAIN_ID_*, FACILITATOR_*, DEFAULT_RPC, TRANSFER_TOPIC, X402_SDK_REF
  errors.py                         # PaymentError + 10 subclasses
  settlement.py                     # ExpectedSettlement, VerifiedSettlement, verify_settlement(), _get_web3()
  wallet.py                         # Wallet (Protocol), LocalWallet, CdpWallet (seam)
  client.py                         # Offer, PaymentQuote, PaymentOutcome, inspect_offer(), pay()
  testing/
    __init__.py                     # empty marker
    seller.py                       # minimal Flask x402 seller
    fixtures.py                     # pytest fixture: seller on a random port; wire_real_x402_task() helper

evals/
  executor.py                       # NEW — PaymentExecutor, ExecutedPurchase, SyntheticExecutor, RealX402Executor
  environments.py                   # NEW — resolve_executor(task, wallet)
  models.py                         # Environment.kind, Vendor.url, EvalReport +2 fields
  agent_protocol.py                 # AgentFn 3-arg
  agents/stub.py                    # run_task(task, rng_seed, executor)
  grading.py                        # grade(result, task, executed); GradeOutcome.UNVERIFIED_CLAIM
  harness.py                        # run_eval(..., executor=None); recording proxy; +2 report fields

tests/
  data/                             # NEW — recorded 402 payload fixtures (offer_*.json)
  test_payments_constants.py        # CI — read-on-chain pinning
  test_payments_settlement.py       # CI — verify_settlement on 2 golden txs
  test_payments_wallet.py           # CI — LocalWallet
  test_payments_offer_parsing.py    # CI — inspect_offer on recorded payloads (offline)
  test_payments_errors.py           # CI — pay() pre-flight rejects (offline, mocked inspect_offer)
  test_executor.py                  # CI — SyntheticExecutor / RealX402Executor (offline)
  test_executor_reconciliation.py   # CI — synthetic end-to-end: fabricating agent -> UNVERIFIED_CLAIM
  test_payments_integration.py      # @pytest.mark.integration — full pay() vs seller
  test_harness_real_x402.py         # @pytest.mark.integration — real_x402 task + RealX402Executor
  test_payments_mainnet_gate.py     # @pytest.mark.manual — one real mainnet settlement
  test_models.py test_grading.py test_harness.py test_agent_protocol.py test_stub_agent.py   # UPDATED

docs/week3-mainnet-gate.md          # NEW — template for the recorded mainnet-gate result
```

---

## Task 1: Package scaffold, verified constants, errors, pinning tests

**Files:**
- Modify: `requirements.txt`, `pyproject.toml`
- Create: `.env.example`, `payments/__init__.py`, `payments/testing/__init__.py`, `payments/constants.py`, `payments/errors.py`
- Create: `tests/test_payments_constants.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `payments.constants`: `USDC_BASE_SEPOLIA: str`, `USDC_BASE_MAINNET: str`, `CHAIN_ID_BASE_SEPOLIA = 84532`, `CHAIN_ID_BASE_MAINNET = 8453`, `FACILITATOR_TESTNET: str`, `FACILITATOR_CDP: str`, `FACILITATOR_PAYAI: str`, `DEFAULT_RPC: dict[int, tuple[str, ...]]`, `TRANSFER_TOPIC: str`, `USDC_BY_CHAIN: dict[int, str]`, `X402_SDK_REF: str` (the git requirement string, for the record).
  - `payments.errors`: `PaymentError(Exception)` and subclasses `NoSatisfiableOffer`, `OfferOverCap`, `NetworkNotAllowed`, `InsufficientBalance`, `EndpointUnreachable`, `UnexpectedStatus`, `SigningError`, `SettlementRejected`, `SettlementNotConfirmed`, `SettlementMismatch`. `OfferOverCap` and `SettlementNotConfirmed` carry data (see code).

- [ ] **Step 1: Confirm the x402 git requirement resolves**

Run:
```powershell
python -m pip install "x402[requests,evm,flask] @ git+https://github.com/x402-foundation/x402@e398a9e#subdirectory=python/x402"
```
Expected: installs cleanly, `python -c "import x402; print(x402.__version__)"` prints `2.21.0`.

**If it fails** (bad subdirectory/extras form, or the repo moved): try `git+https://github.com/coinbase/x402@e398a9e#subdirectory=python/x402` (the pre-rename URL). If neither resolves, STOP and report — the fallback is vendoring `python/x402` at `e398a9e` into `third_party/x402/`, which is a spec deviation the controller must approve. Do not guess a different commit.

- [ ] **Step 2: Update `requirements.txt`**

Replace the file contents with (keep `pydantic` pinned to its current value — check `python -m pip show pydantic`):
```
pydantic==2.13.5
web3==7.16.0
eth-account==0.14.0
x402[requests,evm,flask] @ git+https://github.com/x402-foundation/x402@e398a9e#subdirectory=python/x402
```
Use the exact `web3` / `eth-account` versions `python -m pip show web3 eth-account` reports (they are already in the venv from Week 2). If Step 1 needed the `coinbase/x402` URL, use that here instead and note it in the report.

- [ ] **Step 3: Update `pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-ra -m 'not integration and not manual'"
markers = [
    "integration: needs testnet funds or a live seller; not run in CI",
    "manual: run once by hand; records a result",
]
```

- [ ] **Step 4: Create `.env.example`**

```
# Copy to .env (git-ignored). Throwaway wallet only.

# Spender private key (0x-prefixed). Required for payments.client.pay and the
# @pytest.mark.integration / @pytest.mark.manual tests. Leave unset for CI.
X402_WALLET_KEY=

# Optional read-only RPC overrides. Defaults live in payments/constants.py.
BASE_SEPOLIA_RPC_URL=
BASE_MAINNET_RPC_URL=
```

- [ ] **Step 5: Create the package markers**

```powershell
New-Item -ItemType Directory -Force payments, payments\testing, tests\data
New-Item -ItemType File payments\__init__.py
New-Item -ItemType File payments\testing\__init__.py
```

- [ ] **Step 6: Write `payments/constants.py`**

```python
"""Verified on-chain constants for the payment path.

Every value carries a primary-source URL. Values already read on chain during the
Week-1 gate cite docs/archive/probe/findings.md section 6. Each is re-pinned by
tests/test_payments_constants.py (CLAUDE.md rule 2).
"""

from __future__ import annotations

import os

# USDC, Base Sepolia -- Circle official docs:
# https://developers.circle.com/stablecoins/usdc-contract-addresses  (Testnet -> Base Sepolia)
# On-chain (findings section 6): symbol()="USDC", decimals()=6
USDC_BASE_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"

# USDC, Base mainnet -- Circle official docs (Mainnet -> Base)
# On-chain (findings section 6): name()="USD Coin", symbol()="USDC", decimals()=6
USDC_BASE_MAINNET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# Chain ids -- docs.x402.org/getting-started/quickstart-for-sellers + flask README
CHAIN_ID_BASE_SEPOLIA = 84532   # CAIP-2 eip155:84532  (findings section 6: eth_chainId)
CHAIN_ID_BASE_MAINNET = 8453    # CAIP-2 eip155:8453

USDC_BY_CHAIN = {
    CHAIN_ID_BASE_SEPOLIA: USDC_BASE_SEPOLIA,
    CHAIN_ID_BASE_MAINNET: USDC_BASE_MAINNET,
}

# Facilitators -- docs.x402.org/getting-started/quickstart-for-sellers
FACILITATOR_TESTNET = "https://x402.org/facilitator"          # Base Sepolia + Solana devnet only
FACILITATOR_CDP = "https://api.cdp.coinbase.com/platform/v2/x402"   # GET /discovery/resources -> 200 no auth
FACILITATOR_PAYAI = "https://facilitator.payai.network"            # GET /discovery/resources -> 200 no auth

# keccak256("Transfer(address,address,uint256)")  (ERC-20 Transfer event topic0)
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Read-only RPC endpoints, tried in order. publicnode first for mainnet: the
# Week-1 probe found sepolia.base.org / mainnet.base.org return 403 to a bare
# client while publicnode works. Env overrides prepend to the list.
DEFAULT_RPC: dict[int, tuple[str, ...]] = {
    CHAIN_ID_BASE_SEPOLIA: ("https://base-sepolia-rpc.publicnode.com", "https://sepolia.base.org"),
    CHAIN_ID_BASE_MAINNET: ("https://base-rpc.publicnode.com", "https://mainnet.base.org", "https://base.drpc.org"),
}

X402_SDK_REF = "git+https://github.com/x402-foundation/x402@e398a9e#subdirectory=python/x402"


def rpc_urls(chain_id: int) -> tuple[str, ...]:
    """RPC endpoints for a chain, env override first."""
    env = {
        CHAIN_ID_BASE_SEPOLIA: os.environ.get("BASE_SEPOLIA_RPC_URL"),
        CHAIN_ID_BASE_MAINNET: os.environ.get("BASE_MAINNET_RPC_URL"),
    }.get(chain_id)
    base = DEFAULT_RPC.get(chain_id, ())
    return (env, *base) if env else base
```

(If Step 1 used the `coinbase/x402` URL, set `X402_SDK_REF` to match.)

- [ ] **Step 7: Write `payments/errors.py`**

```python
"""Agent-facing failure taxonomy for the payment path.

payments.client raises these; it never swallows. RealX402Executor re-raises them.
An agent that lets one escape propagates it out of run_eval -- a crash is a bug,
not a graded FAIL (CLAUDE.md rule 4 / Week-2 error rules).
"""

from __future__ import annotations

from decimal import Decimal


class PaymentError(Exception):
    """Base for every expected payment-path failure."""


class NoSatisfiableOffer(PaymentError):
    """No accepts entry the client can pay (Permit2-only, wrong asset/chain, non-402)."""


class OfferOverCap(PaymentError):
    """Cheapest satisfiable offer exceeds the caller's max_amount. Pre-flight."""

    def __init__(self, amount: Decimal, cap: Decimal):
        self.amount = amount
        self.cap = cap
        super().__init__(f"offer {amount} USDC exceeds cap {cap} USDC")


class NetworkNotAllowed(PaymentError):
    """Offer's chain is not in the caller's network allowlist. Pre-flight."""


class InsufficientBalance(PaymentError):
    """Wallet USDC balance is below the offer amount. Pre-flight."""


class EndpointUnreachable(PaymentError):
    """Connection failed or timed out on the unpaid GET."""


class UnexpectedStatus(PaymentError):
    """Endpoint returned neither a 402 nor a post-payment 200 (404/405/500/...)."""

    def __init__(self, status: int, url: str):
        self.status = status
        super().__init__(f"{url} returned HTTP {status}")


class SigningError(PaymentError):
    """The wallet failed to produce a signature."""


class SettlementRejected(PaymentError):
    """PAYMENT-RESPONSE missing or success != true after the paid retry."""


class SettlementNotConfirmed(PaymentError):
    """Receipt missing / status 0 / unmined after the retry budget. Carries the tx hash."""

    def __init__(self, tx_hash: str, detail: str = ""):
        self.tx_hash = tx_hash
        super().__init__(f"settlement {tx_hash} not confirmed{': ' + detail if detail else ''}")


class SettlementMismatch(PaymentError):
    """On-chain transfer does not match the expected payer / pay_to / amount."""

    def __init__(self, mismatch: str):
        self.mismatch = mismatch
        super().__init__(f"settlement mismatch: {mismatch}")
```

- [ ] **Step 8: Write the failing pinning tests**

Create `tests/test_payments_constants.py`:
```python
import json
import urllib.error
import urllib.request

import pytest

from payments import constants

_HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def _rpc(chain_id: int, method: str, params: list):
    last = None
    for url in constants.rpc_urls(chain_id):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        try:
            req = urllib.request.Request(url, data=body, headers=_HEADERS)
            out = json.load(urllib.request.urlopen(req, timeout=20))
            if "result" in out:
                return out["result"]
            last = out
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:  # pragma: no cover
            last = exc
    pytest.skip(f"all RPCs unreachable for chain {chain_id}: {last!r}")


def _eth_call(chain_id: int, to: str, selector: str) -> str:
    return _rpc(chain_id, "eth_call", [{"to": to, "data": selector}, "latest"])


def _decode_string(hex_result: str) -> str:
    raw = bytes.fromhex(hex_result[2:])
    # ABI: offset(32) | length(32) | data
    length = int.from_bytes(raw[32:64], "big")
    return raw[64:64 + length].decode()


SYMBOL_SEL = "0x95d89b41"   # symbol()
DECIMALS_SEL = "0x313ce567" # decimals()


@pytest.mark.parametrize("chain_id,usdc", [
    (constants.CHAIN_ID_BASE_SEPOLIA, constants.USDC_BASE_SEPOLIA),
    (constants.CHAIN_ID_BASE_MAINNET, constants.USDC_BASE_MAINNET),
])
def test_usdc_symbol_and_decimals(chain_id, usdc):
    assert _decode_string(_eth_call(chain_id, usdc, SYMBOL_SEL)) == "USDC"
    assert int(_eth_call(chain_id, usdc, DECIMALS_SEL), 16) == 6


@pytest.mark.parametrize("chain_id", [
    constants.CHAIN_ID_BASE_SEPOLIA, constants.CHAIN_ID_BASE_MAINNET,
])
def test_chain_id_matches(chain_id):
    assert int(_rpc(chain_id, "eth_chainId", []), 16) == chain_id


@pytest.mark.parametrize("facilitator", [constants.FACILITATOR_CDP, constants.FACILITATOR_PAYAI])
def test_mainnet_facilitator_discovery_is_public(facilitator):
    url = facilitator.rstrip("/") + "/discovery/resources"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            assert resp.status == 200
    except (urllib.error.URLError, TimeoutError) as exc:
        pytest.skip(f"facilitator unreachable: {exc!r}")


def test_transfer_topic_is_keccak_of_transfer_event():
    from eth_utils import keccak
    assert "0x" + keccak(text="Transfer(address,address,uint256)").hex() == constants.TRANSFER_TOPIC
```

- [ ] **Step 9: Run to verify failure**

Run:
```powershell
python -m pytest tests/test_payments_constants.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'payments'` (before Step 6) or import errors. After Steps 6-7, the constants tests run and pass (or skip on RPC unreachability).

- [ ] **Step 10: Run the full suite**

Run:
```powershell
python -m pytest -v
```
Expected: PASS — Week-2's 67 tests unchanged, plus the new constants tests pass or skip. No test fails.

- [ ] **Step 11: Commit**

```powershell
git add requirements.txt pyproject.toml .env.example payments tests/test_payments_constants.py
git commit
```
Message: `Add payments/ scaffold, verified constants, error taxonomy` + standard trailer.

---

## Task 2: `payments/settlement.py` — on-chain settlement verification

**Files:**
- Create: `payments/settlement.py`
- Create: `tests/test_payments_settlement.py`

**Interfaces:**
- Consumes: `payments.constants` (`USDC_BY_CHAIN`, `TRANSFER_TOPIC`, `rpc_urls`), `payments.errors` (`SettlementNotConfirmed`).
- Produces:
  - `ExpectedSettlement(payer: str, pay_to: str, asset: str, amount: Decimal)` — frozen dataclass.
  - `VerifiedSettlement(tx_hash, network: int, block_number, status_ok, transfer_from, transfer_to, amount_atomic: int, amount_usdc: Decimal, submitted_by, payer_paid_gas: bool, matches_expected: bool, mismatch: str | None)` — frozen dataclass.
  - `verify_settlement(tx_hash: str, expected: ExpectedSettlement, network: int) -> VerifiedSettlement`. Raises `SettlementNotConfirmed(tx_hash)` if the receipt is still absent after 5 retries (~2 s apart). Otherwise always returns a `VerifiedSettlement`; a clean read that does not reconcile has `matches_expected=False` and a `mismatch` string.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_payments_settlement.py`:
```python
from decimal import Decimal

import pytest

from payments.constants import CHAIN_ID_BASE_MAINNET, CHAIN_ID_BASE_SEPOLIA
from payments.settlement import ExpectedSettlement, verify_settlement

# Golden historical settlements from the Week-1 gate (docs/archive/probe/findings.md section 4).
SEPOLIA_TX = "0x1b1b78e2fcba693ace023bb8af2ae19277f597d6f82b6a2adcc6bd6765dd309d"
SEPOLIA_PAYER = "0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0"
SEPOLIA_PAYTO = "0xa31C8f81A66C779A312b4aFA85aD38c8436B4F6D"
SEPOLIA_AMOUNT = Decimal("0.01")

MAINNET_TX = "0x44cb0f1e7bd5794e1d57ff10974fa1e544a43bd90796922e14d6a7e1cd43fcc3"
MAINNET_PAYER = "0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0"
MAINNET_PAYTO = "0x0E84dDEdAaE6A779c462C22a59F301EC31B6b808"
MAINNET_AMOUNT = Decimal("0.001")
MAINNET_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def _expected(payer, pay_to, amount, asset):
    return ExpectedSettlement(payer=payer, pay_to=pay_to, asset=asset, amount=amount)


def test_verifies_known_mainnet_settlement():
    v = verify_settlement(
        MAINNET_TX,
        _expected(MAINNET_PAYER, MAINNET_PAYTO, MAINNET_AMOUNT, MAINNET_USDC),
        CHAIN_ID_BASE_MAINNET,
    )
    assert v.status_ok is True
    assert v.matches_expected is True and v.mismatch is None
    assert v.transfer_from.lower() == MAINNET_PAYER.lower()
    assert v.transfer_to.lower() == MAINNET_PAYTO.lower()
    assert v.amount_atomic == 1000 and v.amount_usdc == MAINNET_AMOUNT
    assert v.submitted_by.lower() != MAINNET_PAYER.lower()   # facilitator relayer
    assert v.payer_paid_gas is False
    assert v.block_number == 50997392


def test_verifies_known_sepolia_settlement():
    v = verify_settlement(
        SEPOLIA_TX,
        _expected(SEPOLIA_PAYER, SEPOLIA_PAYTO, SEPOLIA_AMOUNT,
                  "0x036CbD53842c5426634e7929541eC2318f3dCF7e"),
        CHAIN_ID_BASE_SEPOLIA,
    )
    assert v.matches_expected is True
    assert v.amount_atomic == 10000


def test_wrong_expected_amount_does_not_match():
    v = verify_settlement(
        MAINNET_TX,
        _expected(MAINNET_PAYER, MAINNET_PAYTO, Decimal("0.999"), MAINNET_USDC),
        CHAIN_ID_BASE_MAINNET,
    )
    assert v.matches_expected is False
    assert "amount" in v.mismatch


def test_wrong_expected_payto_does_not_match():
    v = verify_settlement(
        MAINNET_TX,
        _expected(MAINNET_PAYER, "0x000000000000000000000000000000000000dEaD",
                  MAINNET_AMOUNT, MAINNET_USDC),
        CHAIN_ID_BASE_MAINNET,
    )
    assert v.matches_expected is False
    assert "pay_to" in v.mismatch or "to" in v.mismatch


def test_missing_tx_raises_not_confirmed():
    from payments.errors import SettlementNotConfirmed
    with pytest.raises(SettlementNotConfirmed):
        verify_settlement(
            "0x" + "00" * 32,
            _expected(MAINNET_PAYER, MAINNET_PAYTO, MAINNET_AMOUNT, MAINNET_USDC),
            CHAIN_ID_BASE_MAINNET,
        )
```

Add a module-level skip guard so a total-RPC-outage does not red the suite: wrap the RPC-touching tests with a `pytest.skip` on `URLError` — reuse the `_rpc` helper pattern from `test_payments_constants.py` if the implementation exposes one, or catch in each test.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_payments_settlement.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'payments.settlement'`.

- [ ] **Step 3: Implement `payments/settlement.py`**

```python
"""Independent on-chain verification of an x402 settlement. Read-only: no key,
no spend. 'A 200 response is not proof of settlement -- the chain is.'"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

from web3 import Web3

from payments.constants import TRANSFER_TOPIC, USDC_BY_CHAIN, rpc_urls
from payments.errors import SettlementNotConfirmed

_RETRIES = 5
_RETRY_SLEEP = 2.0


@dataclass(frozen=True)
class ExpectedSettlement:
    payer: str
    pay_to: str
    asset: str
    amount: Decimal            # whole USDC


@dataclass(frozen=True)
class VerifiedSettlement:
    tx_hash: str
    network: int
    block_number: int
    status_ok: bool
    transfer_from: str
    transfer_to: str
    amount_atomic: int
    amount_usdc: Decimal
    submitted_by: str
    payer_paid_gas: bool
    matches_expected: bool
    mismatch: str | None


def _web3(chain_id: int) -> Web3:
    last = None
    for url in rpc_urls(chain_id):
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={
                "timeout": 20, "headers": {"User-Agent": "Mozilla/5.0"}}))
            if w3.is_connected():
                return w3
        except Exception as exc:  # pragma: no cover - network
            last = exc
    raise SettlementNotConfirmed("", f"no RPC reachable for chain {chain_id}: {last!r}")


def _get_receipt(w3: Web3, tx_hash: str):
    for _ in range(_RETRIES):
        try:
            return w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            time.sleep(_RETRY_SLEEP)
    return None


def verify_settlement(tx_hash: str, expected: ExpectedSettlement, network: int) -> VerifiedSettlement:
    w3 = _web3(network)
    receipt = _get_receipt(w3, tx_hash)
    if receipt is None:
        raise SettlementNotConfirmed(tx_hash, "receipt not found after retries")

    tx = w3.eth.get_transaction(tx_hash)
    usdc = Web3.to_checksum_address(USDC_BY_CHAIN[network])
    expected_atomic = int(expected.amount * Decimal(10) ** 6)

    transfer = None
    for log in receipt["logs"]:
        if (Web3.to_checksum_address(log["address"]) == usdc
                and log["topics"][0].hex().lower().removeprefix("0x")
                == TRANSFER_TOPIC.removeprefix("0x")):
            frm = Web3.to_checksum_address("0x" + log["topics"][1].hex()[-40:])
            to = Web3.to_checksum_address("0x" + log["topics"][2].hex()[-40:])
            value = int(log["data"].hex(), 16) if hasattr(log["data"], "hex") else int(log["data"], 16)
            transfer = (frm, to, value)
            break

    status_ok = int(receipt["status"]) == 1
    submitted_by = Web3.to_checksum_address(tx["from"])
    payer_paid_gas = submitted_by.lower() == expected.payer.lower()

    mismatches = []
    if not status_ok:
        mismatches.append("receipt status != 1")
    if transfer is None:
        mismatches.append("no USDC Transfer log for the pinned token")
        frm = to = ""
        value = 0
    else:
        frm, to, value = transfer
        if frm.lower() != expected.payer.lower():
            mismatches.append(f"transfer from {frm} != expected payer {expected.payer}")
        if to.lower() != expected.pay_to.lower():
            mismatches.append(f"transfer to {to} != expected pay_to {expected.pay_to}")
        if value != expected_atomic:
            mismatches.append(f"amount {value} atomic != expected {expected_atomic}")
    if Web3.to_checksum_address(expected.asset) != usdc:
        mismatches.append("expected.asset != pinned USDC for this chain")

    return VerifiedSettlement(
        tx_hash=tx_hash,
        network=network,
        block_number=int(receipt["blockNumber"]),
        status_ok=status_ok,
        transfer_from=frm,
        transfer_to=to,
        amount_atomic=value,
        amount_usdc=Decimal(value) / Decimal(10) ** 6,
        submitted_by=submitted_by,
        payer_paid_gas=payer_paid_gas,
        matches_expected=not mismatches,
        mismatch="; ".join(mismatches) or None,
    )
```

Note: `web3` log field access varies by version — the implementer verifies `log["topics"][n]` / `log["data"]` shapes against `web3==7.16.0` and adjusts the `.hex()` handling if needed (the golden-tx tests will catch it).

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_payments_settlement.py -v`
Expected: PASS (or skip on total RPC outage). The two golden-tx tests confirm exact transfer facts; the wrong-expected tests confirm `matches_expected=False`.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -v` — Expected: all green (67 Week-2 + constants + settlement).

- [ ] **Step 6: Commit**

```powershell
git add payments/settlement.py tests/test_payments_settlement.py
git commit
```
Message: `Add on-chain settlement verification (payments/settlement.py)` + standard trailer.

---

## Task 3: `payments/wallet.py` — wallet abstraction

**Files:**
- Create: `payments/wallet.py`
- Create: `tests/test_payments_wallet.py`

**Interfaces:**
- Consumes: `payments.constants` (`USDC_BY_CHAIN`, `rpc_urls`), `eth_account`, `x402.mechanisms.evm.EthAccountSigner`.
- Produces:
  - `Wallet` — `typing.Protocol`: `address -> str` (property), `x402_signer() -> object`, `usdc_balance(network: int) -> Decimal`.
  - `LocalWallet(private_key: str)` + `LocalWallet.from_env(var: str = "X402_WALLET_KEY") -> LocalWallet` (raises `RuntimeError` if the var is unset/empty).
  - `CdpWallet` — `__init__` raises `NotImplementedError` with the seam docstring.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_payments_wallet.py`:
```python
from decimal import Decimal

import pytest
from eth_account import Account

from payments.constants import CHAIN_ID_BASE_MAINNET
from payments.wallet import CdpWallet, LocalWallet, Wallet


@pytest.fixture
def throwaway_key():
    return Account.create().key.hex()   # generated per test; never a real funded key


def test_local_wallet_address_matches_key(throwaway_key):
    w = LocalWallet(throwaway_key)
    assert w.address == Account.from_key(throwaway_key).address
    assert w.address.startswith("0x") and len(w.address) == 42


def test_local_wallet_is_a_wallet(throwaway_key):
    assert isinstance(LocalWallet(throwaway_key), Wallet)   # runtime_checkable Protocol


def test_x402_signer_is_usable(throwaway_key):
    from x402.mechanisms.evm import EthAccountSigner
    signer = LocalWallet(throwaway_key).x402_signer()
    assert isinstance(signer, EthAccountSigner)


def test_from_env_reads_the_var(monkeypatch, throwaway_key):
    monkeypatch.setenv("X402_WALLET_KEY", throwaway_key)
    assert LocalWallet.from_env().address == Account.from_key(throwaway_key).address


def test_from_env_missing_var_raises(monkeypatch):
    monkeypatch.delenv("X402_WALLET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        LocalWallet.from_env()


def test_usdc_balance_reads_known_address(throwaway_key):
    # The Week-1 buyer wallet holds ~1.999 USDC on Base mainnet (findings section 7 / memory).
    w = LocalWallet(throwaway_key)
    bal = w.usdc_balance.__self__ and None  # placeholder to keep lints quiet
    try:
        bal = LocalWallet("0x" + "1" * 64).usdc_balance  # not used
    except Exception:
        pass
    known = _KnownAddressWallet()  # see helper below
    b = known.usdc_balance(CHAIN_ID_BASE_MAINNET)
    assert isinstance(b, Decimal)
    assert b >= 0


class _KnownAddressWallet:
    """A Wallet whose address is the Week-1 buyer wallet, for a read-only balance check."""
    address = "0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0"

    def x402_signer(self):  # pragma: no cover
        raise NotImplementedError

    def usdc_balance(self, network: int) -> Decimal:
        from payments.wallet import _usdc_balance_of
        return _usdc_balance_of(self.address, network)


def test_cdp_wallet_is_a_seam():
    with pytest.raises(NotImplementedError):
        CdpWallet()
```

Simplify `test_usdc_balance_reads_known_address` in implementation if the helper feels awkward — the essential assertions are: `usdc_balance` returns a non-negative `Decimal`, and it can be called for a real address without a key. If the RPC is unreachable, `pytest.skip`. The implementer may expose `_usdc_balance_of(address, network) -> Decimal` as the shared helper `LocalWallet.usdc_balance` delegates to.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_payments_wallet.py -v` — Expected: FAIL, `ModuleNotFoundError: No module named 'payments.wallet'`.

- [ ] **Step 3: Implement `payments/wallet.py`**

```python
"""Wallet abstraction. LocalWallet (env key, throwaway) now; CdpWallet is a
documented seam. Callers never see a raw key or a concrete signer type."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Protocol, runtime_checkable

from eth_account import Account
from web3 import Web3

from payments.constants import USDC_BY_CHAIN, rpc_urls

_BALANCE_OF_SELECTOR = "0x70a08231"


@runtime_checkable
class Wallet(Protocol):
    @property
    def address(self) -> str: ...
    def x402_signer(self) -> object: ...
    def usdc_balance(self, network: int) -> Decimal: ...


def _usdc_balance_of(address: str, network: int) -> Decimal:
    data = _BALANCE_OF_SELECTOR + "0" * 24 + address.lower().removeprefix("0x")
    last = None
    for url in rpc_urls(network):
        try:
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={
                "timeout": 20, "headers": {"User-Agent": "Mozilla/5.0"}}))
            raw = w3.eth.call({"to": Web3.to_checksum_address(USDC_BY_CHAIN[network]), "data": data})
            return Decimal(int(raw.hex(), 16)) / Decimal(10) ** 6
        except Exception as exc:  # pragma: no cover - network
            last = exc
    raise ConnectionError(f"no RPC reachable for chain {network}: {last!r}")


class LocalWallet:
    def __init__(self, private_key: str):
        self._account = Account.from_key(private_key)

    @classmethod
    def from_env(cls, var: str = "X402_WALLET_KEY") -> "LocalWallet":
        key = os.environ.get(var)
        if not key:
            raise RuntimeError(f"{var} is not set")
        return cls(key)

    @property
    def address(self) -> str:
        return self._account.address

    def x402_signer(self) -> object:
        from x402.mechanisms.evm import EthAccountSigner
        return EthAccountSigner(self._account)

    def usdc_balance(self, network: int) -> Decimal:
        return _usdc_balance_of(self.address, network)


class CdpWallet:
    """Seam for Coinbase CDP Server Wallet v2 (MPC key in AWS Nitro; no raw key
    on disk). NOT implemented -- CDP API credentials are blocked by CDP business
    verification as of 2026-09. A real implementation returns a remote-signing
    shim from x402_signer() (satisfying register_exact_evm_client) and reads
    balance via the CDP API or an RPC. See docs/superpowers/specs/2026-09-07-
    payments-spine-design.md."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "CdpWallet is a seam; use LocalWallet. See the payments-spine design spec.")
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_payments_wallet.py -v` — Expected: PASS (balance test may skip on RPC outage).

- [ ] **Step 5: Full suite** — `python -m pytest -v` — all green.

- [ ] **Step 6: Commit**

```powershell
git add payments/wallet.py tests/test_payments_wallet.py
git commit
```
Message: `Add wallet abstraction (LocalWallet + CDP seam)` + standard trailer.

---

## Task 4: `payments/client.py` — `inspect_offer`

**Files:**
- Create: `payments/client.py` (the inspection half only; `pay` is Task 5)
- Create: `tests/data/offer_ottoai.json`, `tests/data/offer_permit2_only.json`, `tests/data/offer_v1.json`
- Create: `tests/test_payments_offer_parsing.py`

**Interfaces:**
- Consumes: `payments.constants` (`USDC_BY_CHAIN`), `requests`, `base64`, `json`.
- Produces:
  - `Offer(scheme, network: str, chain_id: int | None, asset, amount: Decimal, pay_to, max_timeout_seconds: int, transfer_method: str, satisfiable: bool, unsatisfiable_reason: str | None)` — frozen dataclass.
  - `PaymentQuote(url, x402_version: int, offers: tuple[Offer, ...], best_satisfiable: Offer | None, raw_terms: dict)` — frozen dataclass.
  - `inspect_offer(url: str, *, timeout: float = 20) -> PaymentQuote`. One unpaid GET. Decodes the `payment-required` header (base64 JSON); falls back to a JSON body `accepts`. Non-402 non-JSON → `UnexpectedStatus`. Connection failure → `EndpointUnreachable`.
  - `parse_terms(raw_terms: dict, url: str) -> PaymentQuote` — the pure parser, so tests need no network.
  - `_chain_id_of(network: str) -> int | None` — `"eip155:<n>"` → `n`; `"base"` → 8453; `"base-sepolia"` → 84532; else `None`.

- [ ] **Step 1: Create the recorded payload fixtures**

`tests/data/offer_ottoai.json` — the verbatim decoded `payment-required` object from `docs/archive/probe/findings.md` §3 (the mainnet ottoai capture). Copy it exactly, including the `extensions` block. Its `accepts[0]` is the plain `exact` / `eip155:8453` / USDC `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` / `payTo 0x0E84dDEdAaE6A779c462C22a59F301EC31B6b808` / `amount "1000"` / `extra {name:"USD Coin", version:"2"}`; `accepts[1]` is the same with `extra.assetTransferMethod: "permit2"`; `accepts[2]` is Solana.

`tests/data/offer_permit2_only.json` — hand-authored: `x402Version: 2`, one `accepts` entry, `scheme "exact"`, `network "eip155:84532"`, `asset "0x036CbD53842c5426634e7929541eC2318f3dCF7e"`, `amount "50000"`, `payTo "0x000000000000000000000000000000000000dEaD"`, `maxTimeoutSeconds 300`, `extra {name:"USDC", version:"2", assetTransferMethod:"permit2"}`.

`tests/data/offer_v1.json` — hand-authored `x402Version: 1` shape with a single `accepts`-equivalent entry on `eip155:84532` USDC, `amount "10000"`, plain transfer method. (Parser must tolerate v1; satisfiability still applies.)

- [ ] **Step 2: Write the failing tests**

Create `tests/test_payments_offer_parsing.py`:
```python
import json
from decimal import Decimal
from pathlib import Path

import pytest

from payments.client import Offer, PaymentQuote, parse_terms

DATA = Path("tests/data")


def _terms(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def test_ottoai_first_offer_is_satisfiable_and_priced():
    q = parse_terms(_terms("offer_ottoai.json"), "https://x402.ottoai.services/crypto-news")
    assert isinstance(q, PaymentQuote) and q.x402_version == 2
    o = q.best_satisfiable
    assert o is not None
    assert o.scheme == "exact" and o.chain_id == 8453
    assert o.asset.lower() == "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    assert o.amount == Decimal("0.001")            # "1000" atomic / 1e6
    assert o.pay_to == "0x0E84dDEdAaE6A779c462C22a59F301EC31B6b808"
    assert o.transfer_method == "transferWithAuthorization"


def test_ottoai_permit2_entry_is_unsatisfiable():
    q = parse_terms(_terms("offer_ottoai.json"), "u")
    permit2 = [o for o in q.offers if o.transfer_method == "permit2"]
    assert permit2 and all(o.satisfiable is False for o in permit2)
    assert "permit2" in permit2[0].unsatisfiable_reason


def test_ottoai_solana_entry_is_unsatisfiable():
    q = parse_terms(_terms("offer_ottoai.json"), "u")
    sol = [o for o in q.offers if o.chain_id is None]
    assert sol and all(o.satisfiable is False for o in sol)


def test_permit2_only_has_no_satisfiable_offer():
    q = parse_terms(_terms("offer_permit2_only.json"), "u")
    assert q.best_satisfiable is None
    assert all(o.satisfiable is False for o in q.offers)


def test_v1_terms_parse_and_price():
    q = parse_terms(_terms("offer_v1.json"), "u")
    assert q.x402_version == 1
    assert q.best_satisfiable is not None
    assert q.best_satisfiable.amount == Decimal("0.01")


def test_raw_terms_kept_verbatim():
    raw = _terms("offer_ottoai.json")
    q = parse_terms(raw, "u")
    assert q.raw_terms == raw
```

- [ ] **Step 3: Run to verify failure** — `python -m pytest tests/test_payments_offer_parsing.py -v` → `ModuleNotFoundError: No module named 'payments.client'`.

- [ ] **Step 4: Implement `payments/client.py` (inspection half)**

```python
"""x402 pay flow. inspect_offer/parse_terms here; pay() is added in the next task."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from decimal import Decimal

import requests

from payments.constants import USDC_BY_CHAIN
from payments.errors import EndpointUnreachable, UnexpectedStatus

_KNOWN_BASE = {"base": 8453, "base-sepolia": 84532}


@dataclass(frozen=True)
class Offer:
    scheme: str
    network: str
    chain_id: int | None
    asset: str
    amount: Decimal
    pay_to: str
    max_timeout_seconds: int
    transfer_method: str
    satisfiable: bool
    unsatisfiable_reason: str | None


@dataclass(frozen=True)
class PaymentQuote:
    url: str
    x402_version: int
    offers: tuple[Offer, ...]
    best_satisfiable: Offer | None
    raw_terms: dict


def _chain_id_of(network: str) -> int | None:
    if not network:
        return None
    if network.startswith("eip155:"):
        try:
            return int(network.split(":", 1)[1])
        except ValueError:
            return None
    return _KNOWN_BASE.get(network)


def _offer_from_entry(entry: dict) -> Offer:
    network = str(entry.get("network", ""))
    chain_id = _chain_id_of(network)
    asset = str(entry.get("asset", ""))
    amount = Decimal(str(entry.get("amount", "0"))) / Decimal(10) ** 6
    extra = entry.get("extra") or {}
    transfer_method = extra.get("assetTransferMethod") or "transferWithAuthorization"

    reason = None
    if entry.get("scheme") != "exact":
        reason = f"scheme {entry.get('scheme')!r} not supported"
    elif chain_id not in USDC_BY_CHAIN:
        reason = f"network {network!r} is not a supported Base chain"
    elif asset.lower() != USDC_BY_CHAIN[chain_id].lower():
        reason = "asset is not the pinned USDC for this chain"
    elif transfer_method != "transferWithAuthorization":
        reason = f"{transfer_method} transfer method not supported yet"

    return Offer(
        scheme=str(entry.get("scheme", "")),
        network=network,
        chain_id=chain_id,
        asset=asset,
        amount=amount,
        pay_to=str(entry.get("payTo", "")),
        max_timeout_seconds=int(entry.get("maxTimeoutSeconds", 0)),
        transfer_method=transfer_method,
        satisfiable=reason is None,
        unsatisfiable_reason=reason,
    )


def parse_terms(raw_terms: dict, url: str) -> PaymentQuote:
    version = int(raw_terms.get("x402Version", 1))
    entries = raw_terms.get("accepts") or []
    offers = tuple(_offer_from_entry(e) for e in entries)
    satisfiable = [o for o in offers if o.satisfiable]
    best = min(satisfiable, key=lambda o: o.amount) if satisfiable else None
    return PaymentQuote(url=url, x402_version=version, offers=offers,
                        best_satisfiable=best, raw_terms=raw_terms)


def _decode_header(value: str) -> dict:
    return json.loads(base64.b64decode(value))


def inspect_offer(url: str, *, timeout: float = 20) -> PaymentQuote:
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise EndpointUnreachable(str(exc)) from exc

    header = resp.headers.get("payment-required")
    if header:
        return parse_terms(_decode_header(header), url)
    try:
        body = resp.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and "accepts" in body:
        return parse_terms(body, url)

    if resp.status_code == 402:
        # 402 but no parseable terms anywhere
        return PaymentQuote(url=url, x402_version=1, offers=(), best_satisfiable=None, raw_terms={})
    raise UnexpectedStatus(resp.status_code, url)
```

Note: `min(satisfiable, key=amount)` returns the first on a price tie (list built in `accepts` order) — matches the spec.

- [ ] **Step 5: Run to verify pass** — `python -m pytest tests/test_payments_offer_parsing.py -v` → PASS (fully offline).

- [ ] **Step 6: Full suite** — `python -m pytest -v` → all green.

- [ ] **Step 7: Commit**

```powershell
git add payments/client.py tests/data tests/test_payments_offer_parsing.py
git commit
```
Message: `Add x402 offer inspection (inspect_offer / parse_terms)` + standard trailer.

---

## Task 5: `payments/client.py` — `pay`

**Files:**
- Modify: `payments/client.py` (append `PaymentOutcome` + `pay`)
- Create: `tests/test_payments_errors.py`

**Interfaces:**
- Consumes: everything from Task 4, plus `payments.wallet.Wallet`, `payments.settlement` (`ExpectedSettlement`, `verify_settlement`), `payments.errors`, and the x402 SDK.
- Produces:
  - `PaymentOutcome(url, paid: bool, offer: Offer, tx_hash: str, network: int, amount_paid: Decimal, pay_to: str, resource, verified: VerifiedSettlement, quote: PaymentQuote)` — frozen dataclass.
  - `pay(url: str, wallet: Wallet, *, max_amount: Decimal, network_allowlist: tuple[int, ...] = (84532, 8453), timeout: float = 30) -> PaymentOutcome`. Pre-flight rejects (`NoSatisfiableOffer`, `OfferOverCap`, `NetworkNotAllowed`, `InsufficientBalance`) fire before any signing. Post-pay: `SettlementRejected` / `UnexpectedStatus` / `SettlementMismatch` / `SettlementNotConfirmed`. `paid=True` only after `verify_settlement().matches_expected`.

- [ ] **Step 1: Write the failing tests** (`tests/test_payments_errors.py`, offline — `pay` is exercised only up to the pre-flight rejects by monkeypatching `inspect_offer`)

```python
from decimal import Decimal
from unittest.mock import patch

import pytest

from payments import client
from payments.client import Offer, PaymentQuote
from payments.errors import (
    InsufficientBalance, NetworkNotAllowed, NoSatisfiableOffer, OfferOverCap,
)


class _FakeWallet:
    address = "0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0"

    def __init__(self, balance):
        self._balance = Decimal(balance)

    def x402_signer(self):
        raise AssertionError("pre-flight must reject before signing")

    def usdc_balance(self, network):
        return self._balance


def _quote(*, satisfiable=True, amount="0.01", chain_id=84532):
    o = Offer(scheme="exact", network=f"eip155:{chain_id}", chain_id=chain_id,
              asset="0x036CbD53842c5426634e7929541eC2318f3dCF7e", amount=Decimal(amount),
              pay_to="0xdead", max_timeout_seconds=300,
              transfer_method="transferWithAuthorization",
              satisfiable=satisfiable, unsatisfiable_reason=None if satisfiable else "nope")
    return PaymentQuote(url="u", x402_version=2, offers=(o,),
                        best_satisfiable=o if satisfiable else None, raw_terms={})


def test_no_satisfiable_offer_raises():
    with patch.object(client, "inspect_offer", return_value=_quote(satisfiable=False)):
        with pytest.raises(NoSatisfiableOffer):
            client.pay("u", _FakeWallet("100"), max_amount=Decimal("1"))


def test_over_cap_raises_with_data():
    with patch.object(client, "inspect_offer", return_value=_quote(amount="5")):
        with pytest.raises(OfferOverCap) as ei:
            client.pay("u", _FakeWallet("100"), max_amount=Decimal("1"))
    assert ei.value.amount == Decimal("5") and ei.value.cap == Decimal("1")


def test_network_not_allowed_raises():
    with patch.object(client, "inspect_offer", return_value=_quote(chain_id=8453)):
        with pytest.raises(NetworkNotAllowed):
            client.pay("u", _FakeWallet("100"), max_amount=Decimal("1"),
                       network_allowlist=(84532,))


def test_insufficient_balance_raises():
    with patch.object(client, "inspect_offer", return_value=_quote(amount="0.5")):
        with pytest.raises(InsufficientBalance):
            client.pay("u", _FakeWallet("0.1"), max_amount=Decimal("1"))
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_payments_errors.py -v` → fails (`pay` not defined / `AttributeError`).

- [ ] **Step 3: Append `pay` to `payments/client.py`**

```python
from payments.errors import (
    InsufficientBalance, NetworkNotAllowed, NoSatisfiableOffer, OfferOverCap,
    SettlementMismatch, SettlementNotConfirmed, SettlementRejected, UnexpectedStatus,
)
from payments.settlement import ExpectedSettlement, VerifiedSettlement, verify_settlement
from payments.wallet import Wallet


@dataclass(frozen=True)
class PaymentOutcome:
    url: str
    paid: bool
    offer: Offer
    tx_hash: str
    network: int
    amount_paid: Decimal
    pay_to: str
    resource: object
    verified: VerifiedSettlement
    quote: PaymentQuote


def pay(url: str, wallet: Wallet, *, max_amount: Decimal,
        network_allowlist: tuple[int, ...] = (84532, 8453),
        timeout: float = 30) -> PaymentOutcome:
    quote = inspect_offer(url, timeout=timeout)
    offer = quote.best_satisfiable
    if offer is None:
        raise NoSatisfiableOffer(f"{url}: no satisfiable accepts entry")
    if offer.amount > max_amount:
        raise OfferOverCap(offer.amount, max_amount)
    if offer.chain_id not in network_allowlist:
        raise NetworkNotAllowed(f"{offer.network} not in {network_allowlist}")
    if wallet.usdc_balance(offer.chain_id) < offer.amount:
        raise InsufficientBalance(f"balance < {offer.amount} USDC on chain {offer.chain_id}")

    from x402 import x402ClientSync
    from x402.http import x402HTTPClientSync
    from x402.http.clients import x402_requests
    from x402.mechanisms.evm.exact.register import register_exact_evm_client

    x_client = x402ClientSync().set_spend_controls({"max_amount_per_payment": f"${max_amount}"})
    register_exact_evm_client(x_client, wallet.x402_signer())
    http_client = x402HTTPClientSync(x_client)

    with x402_requests(x_client) as session:
        resp = session.get(url, timeout=timeout)

    if resp.status_code != 200:
        raise UnexpectedStatus(resp.status_code, url)

    try:
        settle = http_client.get_payment_settle_response(lambda name: resp.headers.get(name))
    except ValueError as exc:
        raise SettlementRejected(f"no PAYMENT-RESPONSE from {url}") from exc

    if not getattr(settle, "success", False):
        raise SettlementRejected(f"facilitator reported success != true for {url}")
    tx_hash = getattr(settle, "transaction", None)
    if not tx_hash:
        raise SettlementRejected(f"PAYMENT-RESPONSE for {url} carried no transaction hash")

    verified = verify_settlement(
        tx_hash,
        ExpectedSettlement(payer=wallet.address, pay_to=offer.pay_to,
                           asset=offer.asset, amount=offer.amount),
        network=offer.chain_id,
    )
    if not verified.matches_expected:
        raise SettlementMismatch(verified.mismatch or "unknown")

    try:
        resource = resp.json()
    except ValueError:
        resource = resp.content

    return PaymentOutcome(
        url=url, paid=True, offer=offer, tx_hash=tx_hash, network=offer.chain_id,
        amount_paid=verified.amount_usdc, pay_to=verified.transfer_to,
        resource=resource, verified=verified, quote=quote,
    )
```

Note: the exact x402 SDK symbol names (`get_payment_settle_response`, `.success`, `.transaction`) are transcribed from `docs/archive/probe/probe_02_settle.py`. The implementer confirms them against the installed SDK; if a name differs, fix it and note it in the report (the marked integration test in Task 7 is where a wrong name surfaces).

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_payments_errors.py -v` → PASS (pre-flight rejects, offline).

- [ ] **Step 5: Full suite** — `python -m pytest -v` → all green.

- [ ] **Step 6: Commit**

```powershell
git add payments/client.py tests/test_payments_errors.py
git commit
```
Message: `Add x402 pay flow with verification (payments.client.pay)` + standard trailer.

---

## Task 6: `payments/testing/` — Flask test seller + fixtures

**Files:**
- Create: `payments/testing/seller.py`, `payments/testing/fixtures.py`

**Interfaces:**
- Consumes: `flask`, `x402` flask middleware, `payments.constants`.
- Produces:
  - `build_seller_app(pay_to: str, *, network: str = "eip155:84532") -> flask.Flask` — routes: `GET /weather-data` ($0.01), `GET /news-data` ($0.02), `GET /permit2-only` (advertises a Permit2-only 402), `GET /free` (200, no payment — for the 404/unexpected-status test use a nonexistent path).
  - `run_seller(pay_to, port) -> threading.Thread` — starts the app on `127.0.0.1:port`.
  - pytest fixture `x402_seller` (in `fixtures.py`, re-exported so tests can `from payments.testing.fixtures import x402_seller`) — picks a free port, starts the seller in a thread with `pay_to` from `X402_WALLET_KEY`'s address (or a fixed test address if unset), yields `base_url`, stops on teardown. Marked so it is only used by `@pytest.mark.integration` tests.
  - `wire_real_x402_task(task, base_url) -> TaskSpec` — returns a copy of `task` with each `real_x402` vendor's `url` rewritten to `f"{base_url}/{vendor.category}"`.

- [ ] **Step 1: Implement `payments/testing/seller.py`**

Follow `docs/archive/probe/` references and the x402 flask example. The route handlers return a small JSON body once paid. Use the x402 `[flask]` middleware to gate `/weather-data` and `/news-data` with `price="$0.01"` / `"$0.02"`, `pay_to_address=pay_to`, `network=network`, facilitator `payments.constants.FACILITATOR_TESTNET`. `/permit2-only` returns a hand-built 402 whose single `accepts` entry has `extra.assetTransferMethod = "permit2"` (so `inspect_offer` finds nothing satisfiable). Keep it under ~120 lines.

The implementer confirms the exact `x402[flask]` middleware API against the installed SDK (`docs/archive/probe/` used the seller side too; check `x402.mechanisms` / a `flask` integration module). If the middleware API is unclear, a hand-rolled 402 (return status 402 + a base64 `payment-required` header built from a dict, accept any `payment-signature` on retry by delegating to the facilitator's verify endpoint) is an acceptable fallback — note it in the report.

- [ ] **Step 2: Implement `payments/testing/fixtures.py`**

```python
import contextlib
import socket
import threading
import time

import pytest

from payments.testing.seller import build_seller_app

_TEST_PAY_TO = "0x000000000000000000000000000000000000bEEF"  # overridden when X402_WALLET_KEY is set


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def x402_seller():
    import os
    from eth_account import Account
    pay_to = _TEST_PAY_TO
    key = os.environ.get("X402_WALLET_KEY")
    if key:
        pay_to = Account.from_key(key).address
    port = _free_port()
    app = build_seller_app(pay_to)
    server = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, use_reloader=False),
        daemon=True)
    server.start()
    time.sleep(0.5)
    yield f"http://127.0.0.1:{port}"
    # daemon thread dies with the process; no explicit stop needed


def wire_real_x402_task(task, base_url):
    data = task.model_dump()
    for v in data["environment"]["vendors"]:
        v["url"] = f"{base_url}/{v['category']}"
    return type(task).model_validate(data)
```

- [ ] **Step 3: Smoke test (CI-safe — no signing, no settlement)**

Add to a new `tests/test_payments_seller.py`:
```python
import requests

from payments.testing.fixtures import x402_seller  # noqa: F401


def test_seller_serves_a_402(x402_seller):
    r = requests.get(f"{x402_seller}/weather-data", timeout=5)
    assert r.status_code == 402
    assert r.headers.get("payment-required") or "accepts" in r.json()
```
This test starts the Flask seller but never signs or settles, so it is CI-safe. Do NOT mark it `integration`.

- [ ] **Step 4: Run** — `python -m pytest tests/test_payments_seller.py -v` → PASS.

- [ ] **Step 5: Full suite** — `python -m pytest -v` → all green.

- [ ] **Step 6: Commit**

```powershell
git add payments/testing tests/test_payments_seller.py
git commit
```
Message: `Add self-hosted x402 test seller and fixtures` + standard trailer.

---

## Task 7: `tests/test_payments_integration.py` — full pay() vs the seller (marked)

**Files:**
- Create: `tests/test_payments_integration.py`

**Interfaces:**
- Consumes: `payments.client.pay`, `payments.wallet.LocalWallet`, `payments.settlement.verify_settlement`, the `x402_seller` fixture.
- Produces: nothing importable — an `@pytest.mark.integration` test module.

- [ ] **Step 1: Write the test**

```python
import os
from decimal import Decimal

import pytest
import requests

from payments.client import pay
from payments.errors import NoSatisfiableOffer, UnexpectedStatus
from payments.settlement import ExpectedSettlement, verify_settlement
from payments.wallet import LocalWallet
from payments.testing.fixtures import x402_seller  # noqa: F401

pytestmark = pytest.mark.integration

_KEY = os.environ.get("X402_WALLET_KEY")
skip_no_key = pytest.mark.skipif(not _KEY, reason="X402_WALLET_KEY unset")


@skip_no_key
def test_pay_end_to_end_on_sepolia(x402_seller):
    wallet = LocalWallet.from_env()
    outcome = pay(f"{x402_seller}/weather-data", wallet,
                  max_amount=Decimal("0.05"), network_allowlist=(84532,))
    assert outcome.paid is True
    assert outcome.amount_paid == Decimal("0.01")
    assert outcome.tx_hash.startswith("0x")
    # independent re-verification
    v = verify_settlement(outcome.tx_hash,
                          ExpectedSettlement(wallet.address, outcome.pay_to,
                                             outcome.offer.asset, Decimal("0.01")),
                          84532)
    assert v.matches_expected is True


@skip_no_key
def test_permit2_route_has_no_satisfiable_offer(x402_seller):
    with pytest.raises(NoSatisfiableOffer):
        pay(f"{x402_seller}/permit2-only", LocalWallet.from_env(),
            max_amount=Decimal("1"), network_allowlist=(84532,))


@skip_no_key
def test_missing_route_raises_unexpected_status(x402_seller):
    with pytest.raises(UnexpectedStatus):
        pay(f"{x402_seller}/does-not-exist", LocalWallet.from_env(),
            max_amount=Decimal("1"), network_allowlist=(84532,))
```

- [ ] **Step 2: Confirm collection is skipped by default**

Run: `python -m pytest tests/test_payments_integration.py -v`
Expected: `3 deselected` (the `-m 'not integration and not manual'` default filter). No error.

- [ ] **Step 3: Optionally run it for real** (only if `X402_WALLET_KEY` points at a Sepolia-funded throwaway wallet — the Week-1 buyer wallet holds ~20 test USDC):

Run: `python -m pytest tests/test_payments_integration.py -v -m integration`
Expected: PASS, or `skipped` if no key. Record the outcome (and any x402 SDK symbol fixes discovered) in the task report.

- [ ] **Step 4: Full suite** — `python -m pytest -v` → all green, integration deselected.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_payments_integration.py
git commit
```
Message: `Add payments integration test (pay vs self-hosted seller, marked)` + standard trailer.

---

## Task 8: `evals/models.py` — environment kind, vendor url, report fields

**Files:**
- Modify: `evals/models.py`, `tests/test_models.py`

**Interfaces:**
- Consumes: existing `evals.models`.
- Produces:
  - `Environment` gains `kind: Literal["synthetic", "real_x402"] = "synthetic"`.
  - `Vendor` gains `url: str | None = None`.
  - `EvalReport` gains `unverified_claims: int = 0` and `settled_tx_hashes: list[str] = Field(default_factory=list)`. **Both get defaults** so Week-2's `run_eval` still constructs a valid `EvalReport` and the whole suite stays green at this task boundary; Task 11 makes `run_eval` set them explicitly.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_models.py`)

```python
def test_environment_kind_defaults_to_synthetic(sample_task_dict):
    from evals.models import TaskSpec
    task = TaskSpec.model_validate(sample_task_dict)
    assert task.environment.kind == "synthetic"


def test_environment_real_x402_and_vendor_url(sample_task_dict):
    from evals.models import TaskSpec
    sample_task_dict["environment"]["kind"] = "real_x402"
    sample_task_dict["environment"]["vendors"][0]["url"] = "http://127.0.0.1:9/weather-data"
    task = TaskSpec.model_validate(sample_task_dict)
    assert task.environment.kind == "real_x402"
    assert task.environment.vendors[0].url == "http://127.0.0.1:9/weather-data"
    assert task.environment.vendors[1].url is None


def test_environment_rejects_unknown_kind(sample_task_dict):
    from pydantic import ValidationError
    from evals.models import TaskSpec
    sample_task_dict["environment"]["kind"] = "bogus"
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(sample_task_dict)


def test_eval_report_has_reconciliation_fields():
    from evals.models import EvalReport
    fields = EvalReport.model_fields
    assert "unverified_claims" in fields and "settled_tx_hashes" in fields
```

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_models.py -v` → the 4 new tests fail.

- [ ] **Step 3: Edit `evals/models.py`**

- `from typing import Literal` (add if absent).
- `Vendor`: add `url: Optional[str] = None`.
- `Environment`: add `kind: Literal["synthetic", "real_x402"] = "synthetic"` (keep `vendors: list[Vendor]`; `extra="forbid"` already rejects unknown keys, and `Literal` rejects a bad `kind`).
- `EvalReport`: add `unverified_claims: int = 0` and `settled_tx_hashes: list[str] = Field(default_factory=list)` (defaults, per the interface note above).

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_models.py -v` → all pass.

- [ ] **Step 5: Full suite** — `python -m pytest -v` → **all green**. Because the new `EvalReport` fields have defaults, Week-2's `run_eval` still builds a valid report and every Week-2 harness test passes unchanged. `test_run_eval_report_json_roundtrip` round-trips the defaulted fields fine.

- [ ] **Step 6: Commit**

```powershell
git add evals/models.py tests/test_models.py
git commit
```
Message: `Add real_x402 environment kind and reconciliation report fields` + standard trailer.

---

## Task 9: `evals/executor.py` — PaymentExecutor and the two implementations

**Files:**
- Create: `evals/executor.py`, `tests/test_executor.py`

**Interfaces:**
- Consumes: `evals.models` (`TaskSpec`), `payments.client` (`pay`, `PaymentOutcome`), `payments.errors.PaymentError`, `payments.errors.OfferOverCap`.
- Produces:
  - `ExecutedPurchase(vendor_id: str, url: str | None, amount_paid: Decimal, pay_to: str | None, tx_hash: str | None, verified: bool, resource: object | None)` — frozen dataclass.
  - `PaymentExecutor` — `Protocol`: `pay(target: str, *, max_amount: Decimal) -> ExecutedPurchase`.
  - `SyntheticExecutor(task: TaskSpec)` — `target` is a `vendor_id`. Unknown id → `KeyError`. `price_usdc > max_amount` → `OfferOverCap`. Else `ExecutedPurchase(verified=True, amount_paid=price, tx_hash=None, url=None, pay_to=None, resource=None)`.
  - `RealX402Executor(wallet, network_allowlist=(84532, 8453))` — `target` is a URL. Calls `payments.client.pay(target, self._wallet, max_amount=max_amount, network_allowlist=self._allow)`; re-raises any `PaymentError`. Maps `PaymentOutcome` → `ExecutedPurchase(verified=outcome.paid, amount_paid=outcome.amount_paid, pay_to=outcome.pay_to, tx_hash=outcome.tx_hash, url=target, resource=outcome.resource, vendor_id=<from the task vendor whose url == target, or "" if unknown>)`. Takes an optional `task` so it can resolve `vendor_id`; if no task, `vendor_id = target`.

- [ ] **Step 1: Write the failing tests** (`tests/test_executor.py`)

```python
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from evals.executor import (ExecutedPurchase, PaymentExecutor, RealX402Executor,
                            SyntheticExecutor)
from payments.errors import NoSatisfiableOffer, OfferOverCap


def test_synthetic_pays_at_catalog_price(sample_task):
    ex = SyntheticExecutor(sample_task)
    p = ex.pay("v1", max_amount=Decimal("0.05"))
    assert isinstance(p, ExecutedPurchase)
    assert p.vendor_id == "v1" and p.amount_paid == Decimal("0.01")
    assert p.verified is True and p.tx_hash is None and p.url is None


def test_synthetic_over_cap_raises(sample_task):
    with pytest.raises(OfferOverCap):
        SyntheticExecutor(sample_task).pay("v2", max_amount=Decimal("0.05"))  # v2 = 0.08


def test_synthetic_unknown_vendor_raises_keyerror(sample_task):
    with pytest.raises(KeyError):
        SyntheticExecutor(sample_task).pay("nope", max_amount=Decimal("1"))


def test_synthetic_is_a_payment_executor(sample_task):
    assert isinstance(SyntheticExecutor(sample_task), PaymentExecutor)


def test_real_executor_maps_outcome():
    outcome = Mock(paid=True, amount_paid=Decimal("0.01"), pay_to="0xabc",
                   tx_hash="0xdead", resource={"ok": 1})
    with patch("evals.executor.pay", return_value=outcome) as pay_mock:
        ex = RealX402Executor(wallet=Mock(), network_allowlist=(84532,))
        p = ex.pay("http://seller/weather-data", max_amount=Decimal("0.05"))
    pay_mock.assert_called_once()
    assert p.verified is True and p.amount_paid == Decimal("0.01")
    assert p.tx_hash == "0xdead" and p.url == "http://seller/weather-data"


def test_real_executor_reraises_payment_error():
    with patch("evals.executor.pay", side_effect=NoSatisfiableOffer("x")):
        ex = RealX402Executor(wallet=Mock())
        with pytest.raises(NoSatisfiableOffer):
            ex.pay("http://seller/permit2-only", max_amount=Decimal("1"))
```

- [ ] **Step 2: Run to verify failure** — `ModuleNotFoundError: No module named 'evals.executor'`.

- [ ] **Step 3: Implement `evals/executor.py`**

```python
"""The interface the agent calls to buy. The executor records verified purchase
facts -- grading reconciles against these, not the agent's self-report."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from evals.models import TaskSpec
from payments.client import pay
from payments.errors import OfferOverCap


@dataclass(frozen=True)
class ExecutedPurchase:
    vendor_id: str
    url: str | None
    amount_paid: Decimal
    pay_to: str | None
    tx_hash: str | None
    verified: bool
    resource: object | None


@runtime_checkable
class PaymentExecutor(Protocol):
    def pay(self, target: str, *, max_amount: Decimal) -> ExecutedPurchase: ...


class SyntheticExecutor:
    def __init__(self, task: TaskSpec):
        self._by_id = {v.vendor_id: v for v in task.environment.vendors}

    def pay(self, target: str, *, max_amount: Decimal) -> ExecutedPurchase:
        vendor = self._by_id[target]              # KeyError on unknown id -- a harness bug
        if vendor.price_usdc > max_amount:
            raise OfferOverCap(vendor.price_usdc, max_amount)
        return ExecutedPurchase(
            vendor_id=vendor.vendor_id, url=None, amount_paid=vendor.price_usdc,
            pay_to=None, tx_hash=None, verified=True, resource=None)


class RealX402Executor:
    def __init__(self, wallet, network_allowlist: tuple[int, ...] = (84532, 8453),
                 task: TaskSpec | None = None):
        self._wallet = wallet
        self._allow = network_allowlist
        self._url_to_id = (
            {v.url: v.vendor_id for v in task.environment.vendors if v.url}
            if task else {})

    def pay(self, target: str, *, max_amount: Decimal) -> ExecutedPurchase:
        outcome = pay(target, self._wallet, max_amount=max_amount,
                      network_allowlist=self._allow)   # re-raises PaymentError
        return ExecutedPurchase(
            vendor_id=self._url_to_id.get(target, target),
            url=target, amount_paid=outcome.amount_paid, pay_to=outcome.pay_to,
            tx_hash=outcome.tx_hash, verified=outcome.paid, resource=outcome.resource)
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_executor.py -v` → PASS.

- [ ] **Step 5: Full suite** — `python -m pytest -v` → **all green**. Task 8's `EvalReport` defaults keep Week-2's `run_eval` valid, and this task only adds `evals/executor.py` + `tests/test_executor.py`.

- [ ] **Step 6: Commit**

```powershell
git add evals/executor.py tests/test_executor.py
git commit
```
Message: `Add PaymentExecutor: synthetic and real x402 implementations` + standard trailer.

---

## Task 10: Agent contract + executor threaded through the harness

**Files:**
- Modify: `evals/agent_protocol.py`, `evals/agents/stub.py`, `evals/harness.py`
- Create: `evals/environments.py`, `tests/test_environments.py`
- Modify: `tests/test_agent_protocol.py`, `tests/test_stub_agent.py`, `tests/test_harness.py`

This task changes the agent-call contract to 3-arg AND threads a `PaymentExecutor` through `run_eval` in one move, so the suite is green at this boundary. Grading is untouched here — `run_eval` still calls `grade(result, task)` with two args and the recording proxy's captured calls go unused until Task 11.

**Interfaces:**
- Produces:
  - `AgentFn = Callable[[TaskSpec, int, PaymentExecutor], AgentResult]`.
  - `evals.agents.stub.run_task(task, rng_seed, executor) -> AgentResult` — ignores `executor`, same `not_implemented` result.
  - `evals.environments.resolve_executor(task: TaskSpec, wallet=None, network_allowlist=(84532, 8453)) -> PaymentExecutor` — `"synthetic"` → `SyntheticExecutor(task)`; `"real_x402"` → `RealX402Executor(wallet, network_allowlist, task)`, raising `ValueError` if `wallet is None`.
  - `evals.harness._RecordingExecutor(inner)` — wraps a `PaymentExecutor`, delegates `pay`, appends each `ExecutedPurchase` to `.calls`.
  - `run_eval(task, agent_fn, n_trials=8, base_seed=0, executor=None) -> EvalReport` — `executor=None` → `resolve_executor(task, wallet=None)`; per trial, wraps it in a fresh `_RecordingExecutor` and calls `agent_fn(task, base_seed + i, proxy)`. Report fields unchanged from Week 2 (the new `EvalReport` fields keep their Task-8 defaults).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_protocol.py`:
```python
def test_agent_run_task_is_three_arg():
    import inspect
    from evals.agents.stub import run_task
    assert list(inspect.signature(run_task).parameters)[:3] == ["task", "rng_seed", "executor"]
```

Create `tests/test_environments.py`:
```python
import pytest

from evals.environments import resolve_executor
from evals.executor import RealX402Executor, SyntheticExecutor


def test_synthetic_env_resolves_synthetic_executor(sample_task):
    assert isinstance(resolve_executor(sample_task), SyntheticExecutor)


def test_real_x402_env_needs_a_wallet(sample_task_dict):
    from evals.models import TaskSpec
    sample_task_dict["environment"]["kind"] = "real_x402"
    task = TaskSpec.model_validate(sample_task_dict)
    with pytest.raises(ValueError):
        resolve_executor(task, wallet=None)
    assert isinstance(resolve_executor(task, wallet=object()), RealX402Executor)
```

`tests/test_stub_agent.py`: every `run_task(sample_task, 0)` becomes `run_task(sample_task, 0, SyntheticExecutor(sample_task))` (import `SyntheticExecutor` from `evals.executor`). Result assertions unchanged.

`tests/test_harness.py`: rewrite the inline agents to 3-arg + executor-driven. Add a helper:
```python
def _buying_agent(vendor_id, agent_id="fake"):
    @agent(agent_id)
    def run_task(task, rng_seed, executor):
        p = executor.pay(vendor_id, max_amount=Decimal("999"))
        return AgentResult(
            purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
            touchpoints=1)
    return run_task
```
- `test_run_eval_all_pass` → `_buying_agent("v1")`; still `pass_1 == 1.0`.
- `test_run_eval_wrong_vendor_is_fail_not_violation` → `_buying_agent("v2")`; still `pass_1 == 0.0`, `budget_violations == 0`. (Under the still-2-arg `grade`, buying v2 at its catalog 0.08 over a 0.05 cap is a `BUDGET_VIOLATION` — adjust the `sample_task` variant so v2 is priced ≤ cap but ≠ expected, e.g. a fixture with v2 at 0.04, to keep this a `FAIL` assertion. Note the fixture choice.)
- `test_run_eval_overspend_reports_budget_violations_and_zero_pass` → an agent buying a synthetic vendor priced 0.09 against a 0.05 cap → `BUDGET_VIOLATION` (still works under 2-arg `grade` — it sums `result.purchases`, which the agent set from `p.amount_paid == 0.09`).
- `test_run_eval_flaky_agent_pass_k_collapses` → even seeds `_buying_agent("v1")`, odd seeds `_buying_agent("v2")` behaviour via one closure that branches on `rng_seed`.
- Exception-propagation / non-`AgentResult` / `require_decorated` tests → bodies unchanged, signatures grow the third param.
- `test_best_price_capture_*` and the JSON round-trip test → agents become executor-driven; assertions unchanged.

- [ ] **Step 2: Run to verify failure** — new tests fail; `test_stub_agent.py` / `test_harness.py` fail on arity.

- [ ] **Step 3: Implement**

- `evals/agent_protocol.py`: `from evals.executor import PaymentExecutor`; `AgentFn = Callable[[TaskSpec, int, PaymentExecutor], AgentResult]`. `agent` / `require_agent_id` unchanged.
- `evals/agents/stub.py`: `def run_task(task, rng_seed, executor) -> AgentResult:` — body unchanged.
- `evals/environments.py`:
```python
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
```
- `evals/harness.py`: add the proxy and thread the executor:
```python
from evals.environments import resolve_executor
from evals.executor import ExecutedPurchase


class _RecordingExecutor:
    def __init__(self, inner):
        self._inner = inner
        self.calls: list[ExecutedPurchase] = []

    def pay(self, target, *, max_amount):
        p = self._inner.pay(target, max_amount=max_amount)
        self.calls.append(p)
        return p


def run_eval(task, agent_fn, n_trials=8, base_seed=0, executor=None) -> EvalReport:
    agent_id = require_agent_id(agent_fn)
    base_executor = executor if executor is not None else resolve_executor(task, wallet=None)

    results, outcomes = [], []
    for i in range(n_trials):
        proxy = _RecordingExecutor(base_executor)
        result = agent_fn(task, base_seed + i, proxy)
        if not isinstance(result, AgentResult):
            raise TypeError(f"agent {agent_id!r} returned {type(result)!r}")
        results.append(result)
        outcomes.append(grade(result, task))     # still 2-arg; Task 11 changes this
    # ... rest of run_eval unchanged (pass_k, counters, EvalReport(...) with the
    #     Task-8 defaults for unverified_claims / settled_tx_hashes)
```

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_agent_protocol.py tests/test_environments.py tests/test_stub_agent.py tests/test_harness.py -v` → PASS.

- [ ] **Step 5: Full suite** — `python -m pytest -v` → **all green**.

- [ ] **Step 6: Commit**

```powershell
git add evals/agent_protocol.py evals/agents/stub.py evals/environments.py evals/harness.py tests/test_agent_protocol.py tests/test_environments.py tests/test_stub_agent.py tests/test_harness.py
git commit
```
Message: `Thread a PaymentExecutor through the agent contract and run_eval` + standard trailer.

---

## Task 11: Grading reconciliation

**Files:**
- Modify: `evals/grading.py`, `evals/harness.py`, `tests/test_grading.py`, `tests/conftest.py`, `tests/test_harness.py`

**Interfaces:**
- Produces:
  - `GradeOutcome` gains `UNVERIFIED_CLAIM = "unverified_claim"`.
  - `grade(result: AgentResult, task: TaskSpec, executed: list[ExecutedPurchase]) -> GradeOutcome` — rules in spec order:
    1. A claimed `result.purchases` entry with no `executed` match (`vendor_id` equal, `abs(claimed.price_usdc - e.amount_paid) <= Decimal("0.000001")`, `e.verified is True`) → `UNVERIFIED_CLAIM`.
    2. `sum(e.amount_paid for e in executed) > task.mandate.budget_cap_usdc` (and `budget_adherence_required`) → `BUDGET_VIOLATION`.
    3. `len(executed) != 1` → `FAIL`.
    4. The one `executed` matches `grading.expected_purchase` (`vendor_id` and `amount_paid <= max_price_usdc`) → `PASS`.
    5. else → `FAIL`.
  - `run_eval` now passes `proxy.calls` to `grade`, populates `unverified_claims` (count of `UNVERIFIED_CLAIM` trials) and `settled_tx_hashes` (all non-null `tx_hash`es), and computes `best_price_capture_rate` / `cost_per_completed_tx_usdc` from the per-trial `executed` lists.

- [ ] **Step 1: Rewrite `tests/test_grading.py`** and add the `make_executed` conftest fixture

```python
@pytest.fixture
def make_executed():
    from decimal import Decimal
    from evals.executor import ExecutedPurchase

    def _make(items=None):
        return [
            ExecutedPurchase(vendor_id=vid, url=None, amount_paid=Decimal(str(amt)),
                             pay_to=None, tx_hash=None, verified=True, resource=None)
            for vid, amt in (items or [])
        ]
    return _make
```
Rewrites (same names + intent, now passing `executed`):
- `test_correct_vendor_under_budget_passes`: `grade(make_result([("v1","0.01")]), sample_task, make_executed([("v1","0.01")]))` → `PASS`.
- `test_wrong_vendor_fails`: claim v2, executed `[("v2","0.02")]` → `FAIL`.
- `test_no_purchase_fails`: claim [], executed [] → `FAIL`.
- `test_two_purchases_fail_even_if_one_is_right`: executed 2 entries → `FAIL`.
- `test_overspend_is_budget_violation_not_fail`: executed `[("v1","0.09")]` → `BUDGET_VIOLATION`.
- `test_budget_violation_overrides_wrong_count`: executed `[("v1","0.04"),("v2","0.04")]` → `BUDGET_VIOLATION`.
- `test_right_vendor_above_max_price_but_under_cap_fails`: `max_price` 0.03, executed `[("v1","0.04")]` → `FAIL`.
- `test_price_just_over_cap_is_violation`: executed `[("v1","0.051")]` → `BUDGET_VIOLATION`.
- `test_price_equal_to_cap_is_allowed`: executed `[("v1","0.05")]` → `PASS`.
- `test_budget_adherence_not_required_lets_overspend_through_to_fail`: flag off, executed `[("v1","0.09")]` → `FAIL`.
- **NEW** `test_fabricated_claim_is_unverified`: `grade(make_result([("v1","0.01")]), sample_task, [])` → `UNVERIFIED_CLAIM`.
- **NEW** `test_claim_amount_mismatch_is_unverified`: claim `("v1","0.01")`, executed `[("v1","0.02")]` → `UNVERIFIED_CLAIM`.

Also add to `tests/test_harness.py`:
- **NEW** `test_run_eval_counts_unverified_claims`: an agent returning `AgentResult(purchases=[Purchase("v1", Decimal("0.01"))])` **without** calling `executor` → every trial `UNVERIFIED_CLAIM`, `report.unverified_claims == n_trials`, `pass_1 == 0.0`.
- `test_run_eval_all_pass`: add `assert report.unverified_claims == 0` and `assert report.settled_tx_hashes == []`.

- [ ] **Step 2: Run to verify failure** — `python -m pytest tests/test_grading.py -v` → arity errors.

- [ ] **Step 3: Implement**

`evals/grading.py`:
```python
from __future__ import annotations

from decimal import Decimal
from enum import Enum

from evals.executor import ExecutedPurchase
from evals.models import AgentResult, TaskSpec

_TOL = Decimal("0.000001")   # one USDC atomic unit


class GradeOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    BUDGET_VIOLATION = "budget_violation"
    UNVERIFIED_CLAIM = "unverified_claim"


def _has_match(claim, executed: list[ExecutedPurchase]) -> bool:
    return any(
        e.verified and e.vendor_id == claim.vendor_id
        and abs(e.amount_paid - claim.price_usdc) <= _TOL
        for e in executed
    )


def grade(result: AgentResult, task: TaskSpec, executed: list[ExecutedPurchase]) -> GradeOutcome:
    if any(not _has_match(c, executed) for c in result.purchases):
        return GradeOutcome.UNVERIFIED_CLAIM

    total = sum((e.amount_paid for e in executed), Decimal("0"))
    if task.grading.budget_adherence_required and total > task.mandate.budget_cap_usdc:
        return GradeOutcome.BUDGET_VIOLATION

    if len(executed) != 1:
        return GradeOutcome.FAIL

    e = executed[0]
    exp = task.grading.expected_purchase
    if e.vendor_id == exp.vendor_id and e.amount_paid <= exp.max_price_usdc:
        return GradeOutcome.PASS
    return GradeOutcome.FAIL
```

`evals/harness.py` — in `run_eval`, collect per-trial executions and use them:
```python
    results, outcomes, executed_per_trial = [], [], []
    for i in range(n_trials):
        proxy = _RecordingExecutor(base_executor)
        result = agent_fn(task, base_seed + i, proxy)
        if not isinstance(result, AgentResult):
            raise TypeError(f"agent {agent_id!r} returned {type(result)!r}")
        results.append(result)
        executed_per_trial.append(proxy.calls)
        outcomes.append(grade(result, task, proxy.calls))
    ...
    unverified_claims = outcomes.count(GradeOutcome.UNVERIFIED_CLAIM)
    settled = [e.tx_hash for ex in executed_per_trial for e in ex if e.tx_hash]
```
Change the capture rule to `executed_per_trial[i]` (a trial captures iff exactly one execution, `target is not None`, `ex[0].vendor_id == target.vendor_id`, and `outcomes[i] is not GradeOutcome.BUDGET_VIOLATION` — keeps the Week-2 fix). Change `cost_per_completed_tx_usdc` to sum `result.cost_usdc` over trials graded `PASS` (denominator logic unchanged). Add `unverified_claims=unverified_claims, settled_tx_hashes=settled` to the `EvalReport(...)` call.

- [ ] **Step 4: Run to verify pass** — `python -m pytest tests/test_grading.py tests/test_harness.py -v` → PASS.

- [ ] **Step 5: Full suite** — `python -m pytest -v` → **all green**. This closes the contract-change blast radius.

- [ ] **Step 6: Commit**

```powershell
git add evals/grading.py evals/harness.py tests/test_grading.py tests/conftest.py tests/test_harness.py
git commit
```
Message: `Grade against verified executions; report unverified claims` + standard trailer.

---

## Task 12: `tests/test_executor_reconciliation.py` — synthetic end-to-end

**Files:**
- Create: `tests/test_executor_reconciliation.py`

**Interfaces:** consumes `run_eval`, `resolve_executor`, `agent`, `AgentResult`, `Purchase`. CI, offline.

- [ ] **Step 1: Write the test**

```python
from decimal import Decimal

from evals.agent_protocol import agent
from evals.harness import run_eval
from evals.models import AgentResult, Purchase


@agent("honest")
def honest(task, rng_seed, executor):
    p = executor.pay("v1", max_amount=Decimal("0.05"))
    return AgentResult(purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
                       touchpoints=1)


@agent("liar")
def liar(task, rng_seed, executor):
    # claims a purchase it never executed
    return AgentResult(purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.01"))],
                       touchpoints=1)


@agent("overpay-liar")
def overpay_liar(task, rng_seed, executor):
    executor.pay("v1", max_amount=Decimal("0.05"))          # really buys at 0.01
    return AgentResult(purchases=[Purchase(vendor_id="v1", price_usdc=Decimal("0.005"))],
                       touchpoints=1)                        # but claims a different price


def test_honest_agent_passes_on_verified_amount(sample_task):
    report = run_eval(sample_task, honest, n_trials=8)
    assert report.pass_1 == 1.0
    assert report.unverified_claims == 0
    assert report.best_price_capture_rate == 1.0


def test_fabricated_claim_is_flagged(sample_task):
    report = run_eval(sample_task, liar, n_trials=8)
    assert report.pass_1 == 0.0
    assert report.unverified_claims == 8


def test_price_misreport_is_flagged(sample_task):
    report = run_eval(sample_task, overpay_liar, n_trials=8)
    assert report.unverified_claims == 8
```

- [ ] **Step 2: Run** — `python -m pytest tests/test_executor_reconciliation.py -v` → PASS.

- [ ] **Step 3: Full suite** — `python -m pytest -v` → green.

- [ ] **Step 4: Commit**

```powershell
git add tests/test_executor_reconciliation.py
git commit
```
Message: `Add reconciliation eval: fabricated and misreported claims are flagged` + standard trailer.

---

## Task 13: `tests/test_harness_real_x402.py` — real settlement through the harness (marked)

**Files:**
- Create: `tests/test_harness_real_x402.py`
- Create: `evals/tasks/real_weather_sepolia.json` (a `real_x402` task spec)

**Interfaces:** `@pytest.mark.integration`. Consumes the `x402_seller` fixture, `wire_real_x402_task`, `resolve_executor`, `run_eval`, `LocalWallet`.

- [ ] **Step 1: Create `evals/tasks/real_weather_sepolia.json`**

```json
{
  "task_id": "real_weather_sepolia",
  "description": "Buy the weather-data feed from the self-hosted Sepolia x402 seller, under a $0.05 cap.",
  "mandate": {
    "goal_category": "weather-data",
    "budget_cap_usdc": "0.05",
    "vendor_allowlist": null,
    "quality_threshold": null
  },
  "environment": {
    "kind": "real_x402",
    "vendors": [
      {"vendor_id": "seller_weather", "category": "weather-data", "price_usdc": "0.01", "in_allowlist": true, "url": null}
    ]
  },
  "grading": {
    "expected_purchase": {"vendor_id": "seller_weather", "max_price_usdc": "0.05"},
    "budget_adherence_required": true
  }
}
```
Note `test_task_specs.py` will load this too — its self-consistency check (`cheapest_in_policy_vendor` == expected) still holds (one in-policy vendor at 0.01 ≤ 0.05). The `url: null` is rewritten by the fixture at runtime. If `test_task_specs.py` chokes on `kind`/`url`, that is a Task-8 regression — fix there.

- [ ] **Step 2: Write the test**

```python
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from evals.agent_protocol import agent
from evals.environments import resolve_executor
from evals.harness import run_eval
from evals.models import AgentResult, Purchase, TaskSpec
from payments.testing.fixtures import wire_real_x402_task, x402_seller  # noqa: F401
from payments.wallet import LocalWallet

pytestmark = pytest.mark.integration
skip_no_key = pytest.mark.skipif(not os.environ.get("X402_WALLET_KEY"), reason="X402_WALLET_KEY unset")


@agent("real-buyer")
def real_buyer(task, rng_seed, executor):
    vendor = task.environment.vendors[0]
    p = executor.pay(vendor.url, max_amount=Decimal("0.05"))
    return AgentResult(purchases=[Purchase(vendor_id=p.vendor_id, price_usdc=p.amount_paid)],
                       touchpoints=1)


@skip_no_key
def test_real_x402_task_grades_a_real_settlement(x402_seller):
    task = TaskSpec.from_json_file(Path("evals/tasks/real_weather_sepolia.json"))
    task = wire_real_x402_task(task, x402_seller)
    wallet = LocalWallet.from_env()
    report = run_eval(task, real_buyer, n_trials=1,
                      executor=resolve_executor(task, wallet=wallet, network_allowlist=(84532,)))
    assert report.pass_1 == 1.0
    assert report.unverified_claims == 0
    assert len(report.settled_tx_hashes) == 1 and report.settled_tx_hashes[0].startswith("0x")
```

- [ ] **Step 3: Confirm deselected by default** — `python -m pytest tests/test_harness_real_x402.py -v` → `deselected`.

- [ ] **Step 4: Full suite** — `python -m pytest -v` → green, this module deselected. Confirm `tests/test_task_specs.py` still passes with the new `real_x402` spec present.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_harness_real_x402.py evals/tasks/real_weather_sepolia.json
git commit
```
Message: `Add real_x402 harness integration test (marked)` + standard trailer.

---

## Task 14: `tests/test_payments_mainnet_gate.py` + the recorded-result doc

**Files:**
- Create: `tests/test_payments_mainnet_gate.py`
- Create: `docs/week3-mainnet-gate.md`

**Interfaces:** `@pytest.mark.manual`. The deliverable is a runnable-by-hand test plus the doc template; the plan cannot execute it (real mainnet money).

- [ ] **Step 1: Write `tests/test_payments_mainnet_gate.py`**

```python
"""One real payment against a live Bazaar endpoint on Base MAINNET, exercising the
permanent payments/ module. Run by hand:

    python -m pytest tests/test_payments_mainnet_gate.py -m manual -s

Requires X402_WALLET_KEY pointing at a mainnet-funded throwaway wallet
(0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0 holds ~1.999 USDC). Record the
result in docs/week3-mainnet-gate.md.
"""
import os
from decimal import Decimal

import pytest

from payments.client import pay
from payments.wallet import LocalWallet

pytestmark = pytest.mark.manual

ENDPOINT = os.environ.get("W3_GATE_ENDPOINT", "https://x402.ottoai.services/crypto-news")


@pytest.mark.skipif(not os.environ.get("X402_WALLET_KEY"), reason="X402_WALLET_KEY unset")
def test_one_real_mainnet_settlement():
    wallet = LocalWallet.from_env()
    outcome = pay(ENDPOINT, wallet, max_amount=Decimal("0.01"), network_allowlist=(8453,))
    assert outcome.paid is True
    assert outcome.network == 8453
    assert outcome.verified.matches_expected is True
    assert outcome.verified.payer_paid_gas is False
    print(f"\nMAINNET GATE: tx={outcome.tx_hash} amount={outcome.amount_paid} "
          f"pay_to={outcome.pay_to} block={outcome.verified.block_number}")
```

- [ ] **Step 2: Write `docs/week3-mainnet-gate.md`**

```markdown
# Week 3 — mainnet gate

One real payment against a live Bazaar endpoint on Base mainnet, exercising the
permanent `payments/` module (not a throwaway script). Run once:

    Set-Item -Path Env:X402_WALLET_KEY -Value "0x..."   # mainnet-funded throwaway
    python -m pytest tests/test_payments_mainnet_gate.py -m manual -s

## Result

- **Date:** _pending_
- **Endpoint:** _pending_
- **Tx hash:** _pending_
- **Network:** eip155:8453
- **Amount:** _pending_ USDC
- **payer_paid_gas:** _pending_ (expected: false)
- **BaseScan:** _pending_
- **verify_settlement matches_expected:** _pending_

Once filled in, this file is the durable record; the test stays in the repo,
marked `manual`, for re-running.
```

- [ ] **Step 3: Confirm deselected** — `python -m pytest tests/test_payments_mainnet_gate.py -v` → `deselected`.

- [ ] **Step 4: Full suite** — `python -m pytest -v` → green; this module deselected.

- [ ] **Step 5: Commit**

```powershell
git add tests/test_payments_mainnet_gate.py docs/week3-mainnet-gate.md
git commit
```
Message: `Add mainnet-gate manual test and its recorded-result doc` + standard trailer.

---

## Self-Review

**1. Spec coverage**

| Spec element | Task |
|---|---|
| `payments/` package, peer of `evals/`, one-way dependency | Tasks 1–7 |
| `constants.py` — verified values + source URLs + on-chain pinning | Task 1 (values), Task 1 Step 8 (pinning tests) |
| `errors.py` — `PaymentError` + 10 subclasses | Task 1 Step 7 |
| `wallet.py` — `Wallet` protocol, `LocalWallet`, `CdpWallet` seam | Task 3 |
| `client.py` — `inspect_offer` / `PaymentQuote` / `Offer` (incl. `chain_id`) | Task 4 |
| `client.py` — `pay` / `PaymentOutcome`; pre-flight rejects; verify before success | Task 5 |
| `settlement.py` — `verify_settlement`, golden-tx tests, retry→`SettlementNotConfirmed` | Task 2 |
| `payments/testing/` — Flask seller + fixtures + `wire_real_x402_task` | Task 6 |
| x402 SDK pinned by git URL at `e398a9e`, extras `[requests,evm,flask]` | Task 1 Steps 1–2 |
| `PaymentExecutor`, `ExecutedPurchase`, `SyntheticExecutor`, `RealX402Executor` | Task 9 |
| `Environment.kind`, `Vendor.url`, `EvalReport.{unverified_claims,settled_tx_hashes}` | Task 8 |
| `run_task(task, rng_seed, executor)` contract change; stub updated | Task 10 |
| `resolve_executor(task, wallet)` | Task 10 |
| `_RecordingExecutor`; `run_eval(..., executor=None)` threads the executor | Task 10 |
| `grade(result, task, executed)`; `GradeOutcome.UNVERIFIED_CLAIM`; 5 rules | Task 11 |
| `run_eval` populates `unverified_claims` / `settled_tx_hashes`; capture/cost from `executed` | Task 11 |
| CI reconciliation test (fabricating + misreporting agent) | Task 12 |
| `@pytest.mark.integration` — full `pay()` vs seller; 404→`UnexpectedStatus`; Permit2→`NoSatisfiableOffer` | Task 7 |
| `@pytest.mark.integration` — `real_x402` task + `RealX402Executor` → `run_eval` grades a real Sepolia settlement | Task 13 |
| `@pytest.mark.manual` — one real mainnet settlement + `docs/week3-mainnet-gate.md` | Task 14 |
| `pytest` marker config; `.env.example`; `X402_WALLET_KEY` / RPC env vars | Task 1 Steps 3–4 |
| Non-custody statement | Global Constraints; no task moves user funds |
| Deferred: Spend Permission (Wk4), Flask API / Postgres / Docker, CDP wallet impl, Permit2, discovery, ReAct baseline, `sign_typed_data` | Not implemented; `CdpWallet` raises; Permit2 marked unsatisfiable (Task 4) |
| Open risk: git requirement string | Task 1 Step 1 has the exact command + the `coinbase/x402` fallback + STOP-and-report on total failure |
| Open risk: public-RPC reliability in CI | Tasks 1/2/3 tests `pytest.skip` with a message on total RPC outage |
| Open risk: contract-change blast radius | Task 8 stays green via `EvalReport` field defaults; Task 10 merges the 3-arg contract + the `run_eval` executor threading + the `test_harness.py` rewrite in one move; Task 11 turns on reconciliation. Every task boundary is green. |

No gaps.

**2. Placeholder scan**

No "TBD"/"TODO". Each code step carries full code or an exact edit list. Task 6's seller and Task 4's fixtures name a fallback where an SDK API needs confirming, with "note it in the report" — that is a directed action, not a placeholder. Task 14's "the plan cannot execute it" is a stated fact about a real-money manual gate, and the task still ships a concrete test file + doc. No task leaves the suite red at its boundary (the contract-change tasks were sequenced to avoid it — see the blast-radius row above).

**3. Type consistency**

- `Offer.chain_id: int | None` is set by `_chain_id_of` (Task 4) and consumed by `pay` (`offer.chain_id not in network_allowlist`, `wallet.usdc_balance(offer.chain_id)`, `verify_settlement(network=offer.chain_id)`) — all int. `network_allowlist: tuple[int, ...]` throughout (Task 5, Task 9, Task 10).
- `verify_settlement(tx_hash, expected: ExpectedSettlement, network: int)` — same signature in Task 2 impl, Task 5 caller, Task 7 test.
- `ExpectedSettlement(payer, pay_to, asset, amount: Decimal)` — same field names in Task 2, Task 5, Task 7.
- `PaymentOutcome` fields (Task 5) — exactly the set `RealX402Executor` reads in Task 9 (`paid`, `amount_paid`, `pay_to`, `tx_hash`, `resource`).
- `ExecutedPurchase` fields (Task 9) — exactly what `grade` reads (Task 11: `vendor_id`, `amount_paid`, `verified`), what `_RecordingExecutor` collects (Task 10), and what `make_executed` builds (Task 11).
- `PaymentExecutor.pay(target: str, *, max_amount: Decimal) -> ExecutedPurchase` — identical across `SyntheticExecutor`, `RealX402Executor` (Task 9), `_RecordingExecutor` (Task 10), and every test agent (Tasks 10–13).
- `grade(result, task, executed)` (Task 11) — same 3-arg call in `run_eval` (Task 11) and every `test_grading.py` case (Task 11). Note: `run_eval` calls the 2-arg `grade` in Task 10 and switches to 3-arg in Task 11, the same task that changes `grade`'s signature.
- `run_task(task, rng_seed, executor)` (Task 10) — same shape in the stub, `test_stub_agent.py`, and every inline agent (Tasks 10–13).
- `GradeOutcome.UNVERIFIED_CLAIM = "unverified_claim"` (Task 11) — counted in `run_eval` as `unverified_claims` (Task 11), asserted in Tasks 11/12.
- `resolve_executor(task, wallet=None, network_allowlist=(84532, 8453))` (Task 10) — called by `run_eval` with `wallet=None` (Task 10) and by Task 13 with a real wallet.
- Constants: `CHAIN_ID_BASE_SEPOLIA = 84532`, `CHAIN_ID_BASE_MAINNET = 8453` (Task 1) — used as the `network_allowlist` defaults `(84532, 8453)` everywhere.

No inconsistencies found.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-07-week3-payments-spine.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, task review (spec + quality) after each, broad whole-branch review at the end. Fits: 14 sequenced tasks, each ending with a `python -m pytest` a reviewer can check; the money-movement code and the contract-change surgery both benefit from per-task gates.

**2. Inline Execution** — execute in this session via executing-plans, batch with checkpoints.

**Which approach?**
