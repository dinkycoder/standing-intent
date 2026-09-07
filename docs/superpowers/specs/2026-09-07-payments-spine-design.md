# Week 3 Payments Spine — Design

**Date:** 2026-09-07
**Status:** approved, pending implementation plan

## Why this exists

`PMF_AND_BUILD_PLAN.md` Deliverable E lists Week 3 as "Wallet + payments spine …
x402 client; execute a real testnet USDC payment." The Week-1 gate proved x402
settlement works on Base (`docs/archive/probe/findings.md`), but that proof was a
throwaway script (`probe_02_settle.py`) that asserted nothing and was archived.
The Week-2 eval harness (`docs/superpowers/specs/2026-09-02-eval-harness-design.md`,
merged in PR #3) grades against an in-memory synthetic vendor catalog and
explicitly deferred "real HTTP / x402 vendor environments … until the payments
spine (Week 3) exists."

This milestone builds the **permanent component the agent calls every time it
buys something**: a tested `payments/` package with a wallet abstraction, an
x402 pay flow, and independent on-chain settlement verification — plus the
harness wiring that lets evals grade a real, verified purchase instead of an
agent's self-report.

## Scope decisions made during brainstorming

1. **Payment path only.** This spec covers the `payments/` module, its verified
   on-chain constants, and its integration into the eval harness. The Flask API,
   the PostgreSQL schema, and Docker (also on the roadmap's Week-3 line) are
   separable infrastructure and get their own later specs. Vendor discovery /
   Bazaar fan-out is the agent's concern (Week 5) — the payment path takes a URL.
2. **Local EOA wallet now, CDP seam later.** The wallet abstraction ships with a
   local-key implementation (`LocalWallet`, key from an environment variable, a
   throwaway wallet — the proven Week-1 path). A `CdpWallet` seam is defined but
   not implemented; CDP Server Wallet v2 needs credentials blocked by the CDP
   business-verification wall the author hit in Week 1.
3. **Base Sepolia automated, one mainnet manual gate.** The automated suite and
   the harness's real-vendor environment run against a self-hosted Base Sepolia
   Flask seller (free, deterministic). One real settlement against a live Bazaar
   endpoint on Base mainnet (~$0.001 from the funded `0xA85F…` wallet) is a
   manual "prove it once" gate, recorded like the Week-1 probe. Read-only
   on-chain checks (constant pinning, settlement verification) run in CI.
4. **x402 SDK pinned by git URL at a commit.** `requirements.txt` depends on the
   `x402-foundation/x402` repository at commit `e398a9e` (the commit the Week-1
   reference clone used), subdirectory `python/x402`, extras `[requests,evm]`.
   CI installs it directly from GitHub. The exact requirement string is confirmed
   to resolve during implementation. The PyPI `x402` name is polluted (TRON
   forks, Solana ports) and is not used.
5. **Approach: thin SDK wrapper + explicit verification + own test seller.** The
   pay flow is a thin wrapper over the x402 SDK's `x402_requests` session (the
   Week-1 path), plus our own pre-flight 402 inspection so the caller sees the
   price before committing. Settlement verification is a standalone function the
   pay flow calls and the harness can call independently. The self-hosted seller
   is minimal Flask checked into this repo, not a dependency on the external
   reference clone.

## Architecture

New top-level `payments/` package, peer of `evals/`. One-directional dependency:

```
evals/  ->  payments/  ->  (x402 SDK, eth-account, web3)
```

`payments/` never imports `evals/`.

```
payments/
  __init__.py
  constants.py       # verified on-chain constants, each with a source-URL comment
  wallet.py          # Wallet protocol; LocalWallet (env key); CdpWallet (seam, raises)
  client.py          # inspect_offer(url) -> PaymentQuote ;  pay(url, wallet, ...) -> PaymentOutcome
  settlement.py      # verify_settlement(tx_hash, expected, network) -> VerifiedSettlement
  errors.py          # PaymentError hierarchy
  testing/
    __init__.py
    seller.py        # minimal Flask x402 seller (a few priced routes, x402[flask] middleware)
    fixtures.py      # pytest fixture: seller on a random port; testnet-wallet helpers

evals/
  executor.py        # PaymentExecutor protocol ; SyntheticExecutor ; RealX402Executor ; ExecutedPurchase
  environments.py    # resolve_executor(task, wallet) -> PaymentExecutor
  models.py          # Environment gains `kind`; Vendor gains optional `url`; EvalReport gains fields
  agent_protocol.py  # AgentFn signature grows an executor parameter
  grading.py         # grade() gains an `executed` argument; new GradeOutcome.UNVERIFIED_CLAIM
  harness.py         # run_eval() gains an `executor` parameter; collects executions; new counters
  agents/stub.py     # run_task signature updated (ignores executor)

tests/
  test_payments_constants.py      # read-on-chain pinning                       -- CI
  test_payments_wallet.py         # LocalWallet address / signer / balance      -- CI (read-only)
  test_payments_settlement.py     # verify_settlement on golden historical txs  -- CI
  test_payments_offer_parsing.py  # inspect_offer on recorded 402 payloads      -- CI (offline)
  test_payments_errors.py         # PaymentError taxonomy / pre-flight rejects   -- CI (offline)
  test_executor_reconciliation.py # synthetic executor + fabricating agent      -- CI (offline)
  test_payments_integration.py    # full pay() vs self-hosted Sepolia seller    -- @pytest.mark.integration, NOT CI
  test_harness_real_x402.py       # real_x402 task spec + RealX402Executor      -- @pytest.mark.integration, NOT CI
  test_payments_mainnet_gate.py   # one real mainnet settlement                 -- @pytest.mark.manual, NOT CI
```

### Non-custody check (CLAUDE.md rule 1)

This milestone moves only the **agent's own** throwaway USDC to vendors —
directly; the money leaves and does not return. No user funds exist yet (the
capped, revocable Spend Permission over a user's Base Account is Week 4). It
trips none of the four tripwires: no key over user funds, no pooling of multiple
users' funds, no receive-and-forward, no fee deducted inside the payment
transaction. Week 4 is where the custody-sensitive flow lands and gets its own
scrutiny.

## The `payments/` module

### `wallet.py`

```python
class Wallet(Protocol):
    @property
    def address(self) -> str: ...               # 0x-checksummed EOA address
    def x402_signer(self): ...                   # object accepted by register_exact_evm_client
    def usdc_balance(self, network: int) -> Decimal: ...   # whole USDC (atomic / 10**6)

class LocalWallet:
    def __init__(self, private_key: str): ...    # never a key literal in code
    @classmethod
    def from_env(cls, var: str = "X402_WALLET_KEY") -> "LocalWallet": ...

class CdpWallet:
    """Seam for Coinbase CDP Server Wallet v2 (MPC key, no raw key on disk).
    Not implemented — CDP API credentials are blocked by CDP business
    verification as of 2026-09. A real implementation returns a remote-signing
    shim from x402_signer() and reads balance via the CDP API or an RPC."""
    def __init__(self, *args, **kwargs): raise NotImplementedError(...)
```

`x402_signer()` returns whatever `register_exact_evm_client` needs — for
`LocalWallet`, an `EthAccountSigner` wrapping `eth_account.Account.from_key`.
Callers never see a raw key or a concrete signer type. Direct EIP-712 signing
(`sign_typed_data`) is **not** on the interface yet — it is added in Week 4 when
the Spend Permission needs it (YAGNI).

`usdc_balance` reads `balanceOf` over a read-only RPC (from `constants.DEFAULT_RPC`
or a `BASE_{SEPOLIA,MAINNET}_RPC_URL` env override), using `constants.USDC_*` for
the token address.

### `client.py`

Return types are frozen dataclasses (not serialized like the eval models):

```python
@dataclass(frozen=True)
class Offer:
    scheme: str                     # "exact"
    network: str                    # CAIP-2 string, verbatim, e.g. "eip155:84532" or bare "base"
    chain_id: int | None            # parsed from `network` ("eip155:<id>" -> id; "base" -> 8453); None if unparseable
    asset: str                      # token contract address
    amount: Decimal                 # whole USDC (atomic string / 10**6)
    pay_to: str
    max_timeout_seconds: int
    transfer_method: str            # "transferWithAuthorization" | "permit2" | other
    satisfiable: bool
    unsatisfiable_reason: str | None

@dataclass(frozen=True)
class PaymentQuote:
    url: str
    x402_version: int               # 1 or 2
    offers: tuple[Offer, ...]
    best_satisfiable: Offer | None  # cheapest satisfiable offer
    raw_terms: dict                 # the decoded payment-required object, verbatim

@dataclass(frozen=True)
class PaymentOutcome:
    url: str
    paid: bool                      # True only after on-chain verification
    offer: Offer                    # which offer was paid
    tx_hash: str
    network: str
    amount_paid: Decimal            # from the verified Transfer log, NOT the SDK's claim
    pay_to: str                     # from the verified Transfer log
    resource: bytes | dict          # the paid response body
    verified: "VerifiedSettlement"
    quote: PaymentQuote             # the pre-flight, for the record
```

**`inspect_offer(url) -> PaymentQuote`** — one unpaid GET (no SDK). Base64-decode
the `payment-required` header; if absent, fall back to a JSON body copy (some
sellers send both). Parse `accepts` into `Offer`s. Convert atomic `amount`
strings to whole USDC by dividing by `10**6` (USDC has 6 decimals — never
`10**18`).

*Satisfiability* (Week 3): `chain_id` in `{8453, 84532}` AND `scheme == "exact"`
AND `asset` equals the pinned `USDC_*` for that chain AND `transfer_method` is
plain `transferWithAuthorization` (no `extra.assetTransferMethod`, or it equals
`"transferWithAuthorization"`). A `permit2` entry is `satisfiable = False,
unsatisfiable_reason = "permit2 transfer method not supported yet"`. `x402Version`
1 and 2 are both parsed; a fat `extensions` object is ignored, not a parse error.
On a price tie between satisfiable offers, `best_satisfiable` is the first in
`accepts` order (matches the Week-2 `cheapest_in_policy_vendor` convention).

**`pay(url, wallet, *, max_amount: Decimal, network_allowlist=(84532, 8453)) -> PaymentOutcome`**:

1. `quote = inspect_offer(url)`. Let `offer = quote.best_satisfiable`.
2. `offer is None` → raise `NoSatisfiableOffer`.
3. `offer.amount > max_amount` → raise `OfferOverCap(amount, cap)`.
4. `offer.chain_id not in network_allowlist` → raise `NetworkNotAllowed`.
5. `wallet.usdc_balance(offer.chain_id) < offer.amount` → raise `InsufficientBalance`.
6. Build the SDK client: `x402ClientSync().set_spend_controls(
   {"max_amount_per_payment": f"${max_amount}"})`; `register_exact_evm_client(
   client, wallet.x402_signer())`.
7. `with x402_requests(client) as session: resp = session.get(url, timeout=…)`.
   The SDK performs 402 → sign → retry synchronously and immediately, inside the
   300-second `max_timeout_seconds` window.
8. Extract `PAYMENT-RESPONSE`. Missing or `success != true` → raise
   `SettlementRejected`. A non-402/non-200 status → raise `UnexpectedStatus`.
9. `verified = verify_settlement(tx_hash, ExpectedSettlement(
   payer=wallet.address, pay_to=offer.pay_to, asset=offer.asset,
   amount=offer.amount), network=offer.chain_id)`. `verified.matches_expected is
   False` → raise `SettlementMismatch`; receipt still absent after the retry
   budget → raise `SettlementNotConfirmed(tx_hash)`.
10. Return `PaymentOutcome(paid=True, amount_paid=verified.amount_usdc,
    pay_to=verified.transfer_to, …)`.

`pay` never returns with `paid=True` unless step 9 succeeded.

### `settlement.py`

```python
@dataclass(frozen=True)
class ExpectedSettlement:
    payer: str
    pay_to: str
    asset: str
    amount: Decimal                 # whole USDC; compared as exact atomic units

@dataclass(frozen=True)
class VerifiedSettlement:
    tx_hash: str
    network: int                    # chain id
    block_number: int
    status_ok: bool                 # receipt status == 1
    transfer_from: str
    transfer_to: str
    amount_atomic: int
    amount_usdc: Decimal
    submitted_by: str               # tx sender — the facilitator relayer, != payer
    payer_paid_gas: bool            # expected False
    matches_expected: bool
    mismatch: str | None            # human-readable, when matches_expected is False
```

`verify_settlement(tx_hash, expected, network) -> VerifiedSettlement` — pure read
over a free RPC (retry across a small public-RPC list). Steps:

- `eth_getTransactionReceipt` — `status == 0x1`.
- Find the USDC `Transfer(address,address,uint256)` log:
  `log.address == USDC_*[network]`, `topic0 ==
  keccak("Transfer(address,address,uint256)")`
  (`0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef`).
- Assert `from == expected.payer`, `to == expected.pay_to`,
  `value == expected.amount * 10**6` (exact — the `exact` scheme is exact).
- `eth_getTransactionByHash` — record tx `from` (the facilitator relayer;
  assert `!= expected.payer`) and `value == 0` (no ETH moved).
- Populate `matches_expected` / `mismatch`. The function returns a
  `VerifiedSettlement` even on mismatch (it never raises for a clean read that
  simply does not reconcile); `pay` turns a mismatch into `SettlementMismatch`.
- If the receipt is not found, retry up to 5 times with ~2 s spacing (Base block
  time ~2 s). If still absent, raise `SettlementNotConfirmed(tx_hash)` — this is
  the one raise inside `verify_settlement`, distinct from a clean non-match.

No key, no spend — CI-runnable against known historical txs.

### `constants.py`

Every value carries a primary-source-URL comment. Values already verified
on-chain in Week 1 cite `docs/archive/probe/findings.md` §6.

| Constant | Value | Source | On-chain verified |
|---|---|---|---|
| `USDC_BASE_SEPOLIA` | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` | Circle: developers.circle.com/stablecoins/usdc-contract-addresses (Testnet → Base Sepolia) | YES (findings §6): `symbol()="USDC"`, `decimals()=6` |
| `USDC_BASE_MAINNET` | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | Circle official docs (Mainnet → Base) | YES (findings §6): `symbol()="USDC"`, `decimals()=6` |
| `CHAIN_ID_BASE_SEPOLIA` | `84532` (CAIP-2 `eip155:84532`) | docs.x402.org quickstart-for-sellers + flask README | YES (findings §6): `eth_chainId` |
| `CHAIN_ID_BASE_MAINNET` | `8453` (CAIP-2 `eip155:8453`) | docs.x402.org quickstart-for-sellers | doc only in Week 1; pinning test adds `eth_chainId` |
| `FACILITATOR_TESTNET` | `https://x402.org/facilitator` | docs.x402.org/getting-started/quickstart-for-sellers — Base Sepolia + Solana devnet only | doc only (not a contract) |
| `FACILITATOR_CDP` | `https://api.cdp.coinbase.com/platform/v2/x402` | same doc | `GET /discovery/resources` → 200, no auth (findings §2) |
| `FACILITATOR_PAYAI` | `https://facilitator.payai.network` | same doc | `GET /discovery/resources` → 200, no auth (findings §2) |
| `DEFAULT_RPC` | `{84532: "https://sepolia.base.org", 8453: "https://mainnet.base.org"}` | base.org public endpoints | used read-only; env-overridable |
| x402 SDK | `x402[requests,evm]` @ `git+https://github.com/x402-foundation/x402@e398a9e#subdirectory=python/x402` | Week-1 reference clone, package version `2.21.0` | requirement string confirmed to resolve in implementation task 1 |

**Pinning tests** (`test_payments_constants.py`, CI): assert `symbol()` and
`decimals()` (never `name()` — Sepolia returns `"USDC"`, mainnet `"USD Coin"`;
Week-1 gotcha); `eth_chainId` matches; each mainnet facilitator's
`/discovery/resources` returns 200. Retry a small public-RPC list; **skip with a
clear message** if all are unreachable — never a silent pass.

## Harness integration

### `PaymentExecutor` (`evals/executor.py`)

The agent never calls `payments.client.pay` directly; it calls an injected
executor. The executor records **verified** purchase facts.

```python
class PaymentExecutor(Protocol):
    def pay(self, target: str, *, max_amount: Decimal) -> "ExecutedPurchase": ...

@dataclass(frozen=True)
class ExecutedPurchase:
    vendor_id: str
    url: str | None                 # None for synthetic
    amount_paid: Decimal            # verified: on-chain for real, catalog for synthetic
    pay_to: str | None
    tx_hash: str | None
    verified: bool
    resource: bytes | dict | None
```

The agent passes a `vendor_id` as `target` for a `synthetic` task and a URL for a
`real_x402` task, per `task.environment.kind`.

- **`SyntheticExecutor(task)`** — today's behavior, formalized. `target` is a
  `vendor_id`; looks it up in `task.environment.vendors`; if
  `price_usdc > max_amount` → raises `OfferOverCap` (behavioural parity with the
  real executor, so agent code is identical across environment kinds); otherwise
  "pays" at the catalog `price_usdc` and returns
  `ExecutedPurchase(verified=True, amount_paid=price, tx_hash=None, url=None)`. No
  chain. Unknown vendor id → raises `KeyError` (a harness bug, not a graded
  failure — matches Week-2 error rules).
- **`RealX402Executor(wallet, network_allowlist)`** — `target` is a URL. Calls
  `payments.client.pay(target, wallet, max_amount=max_amount,
  network_allowlist=…)`; maps `PaymentOutcome` → `ExecutedPurchase`
  (`verified = outcome.paid`, `amount_paid = outcome.amount_paid`,
  `tx_hash = outcome.tx_hash`, `vendor_id` from the task's vendor whose `url`
  matches). Re-raises any `PaymentError` unchanged.

### Contract change to the agent interface

`evals/agent_protocol.py`:

```python
AgentFn = Callable[[TaskSpec, int, PaymentExecutor], AgentResult]
```

`run_task(task, rng_seed, executor) -> AgentResult`. Updated call sites:
`evals/agents/stub.py` (ignores `executor`, still returns the `not_implemented`
result); every inline test agent in `tests/test_harness.py` /
`tests/test_stub_agent.py` — the ones that "buy" are rewritten to call
`executor.pay(...)` and build `AgentResult.purchases` from the returned
`ExecutedPurchase`, which is the correct pattern a real agent follows; and
`tests/test_grading.py`, whose ~10 tests call `grade(result, task)` and now pass
a third `executed` argument (built from the same `make_result` fixture data).

`evals/harness.py`:

```python
def run_eval(task, agent_fn, n_trials=8, base_seed=0, executor=None) -> EvalReport:
```

`executor=None` → `resolve_executor(task, wallet=None)` builds a
`SyntheticExecutor(task)`, so existing `run_eval` calls are unaffected. The
harness wraps the passed executor in a recording proxy that captures every
`ExecutedPurchase` per trial, for grading and the report.

### `real_x402` environment (`evals/environments.py`, `evals/models.py`)

`Environment` gains `kind: Literal["synthetic", "real_x402"] = "synthetic"`.
`Vendor` gains `url: str | None = None`. Week-2 task specs omit `kind` → default
`"synthetic"` → unchanged.

`resolve_executor(task, wallet)` returns `SyntheticExecutor(task)` for
`"synthetic"`, `RealX402Executor(wallet, …)` for `"real_x402"`. It raises
`ValueError` if `kind == "real_x402"` and `wallet is None`.

`payments/testing/seller.py` is a minimal Flask app with `x402[flask]`
middleware serving a handful of priced routes (one per synthetic task category —
e.g. `/weather-data`, `/news-data`). `payments/testing/fixtures.py` provides a
pytest fixture that starts it on a random free port (Base Sepolia facilitator
config) and yields the base URL; a helper rewrites a `real_x402` task's vendor
`url`s to `http://127.0.0.1:<port>/<route>`. Real signing, real Base Sepolia
settlement, deterministic — but it needs a testnet-funded wallet, so it is a
**marked, non-CI** integration test.

### Grading reconciliation (`evals/grading.py`)

`run_eval` collects the `ExecutedPurchase`es the recording proxy captured.
`grade` gains a third argument:

```python
def grade(result: AgentResult, task: TaskSpec, executed: list[ExecutedPurchase]) -> GradeOutcome
```

`GradeOutcome` gains `UNVERIFIED_CLAIM = "unverified_claim"`.

Rules, in order:
1. Any claimed `result.purchases` entry with no matching `executed` entry — same
   `vendor_id`, `|claimed.price_usdc - executed.amount_paid| <= Decimal("0.000001")`
   (one USDC atomic unit), and `executed.verified is True` → `UNVERIFIED_CLAIM`.
   (The lying-agent catch.)
2. Budget: `sum(e.amount_paid for e in executed) > task.mandate.budget_cap_usdc`
   (and `budget_adherence_required`) → `BUDGET_VIOLATION`. Uses **verified**
   amounts.
3. `len(executed) != 1` → `FAIL`.
4. The single verified purchase matches `grading.expected_purchase`
   (`vendor_id` and `amount_paid <= max_price_usdc`) → `PASS`.
5. Otherwise → `FAIL`.

`EvalReport` gains `unverified_claims: int` (count of `UNVERIFIED_CLAIM` trials)
and `settled_tx_hashes: list[str]` (non-null `tx_hash`es across trials, for the
record on real runs). `best_price_capture_rate` and `cost_per_completed_tx_usdc`
now compute from `executed`, not `result.purchases`.

Even for synthetic tasks this is a gain: the harness now catches a synthetic
agent that fabricates a `Purchase` without calling the executor.

## Error handling

`payments/errors.py`:

```
PaymentError
├── NoSatisfiableOffer      # no accepts entry we can pay
├── OfferOverCap            # cheapest satisfiable offer > max_amount        (pre-flight)
├── NetworkNotAllowed       # offer network not in allowlist                 (pre-flight)
├── InsufficientBalance     # wallet USDC < offer amount                     (pre-flight)
├── EndpointUnreachable     # connection failed / timeout on the unpaid GET
├── UnexpectedStatus        # not 402, not a post-payment 200 (404 / 405 / 500 …)
├── SigningError            # wallet failed to produce a signature
├── SettlementRejected      # PAYMENT-RESPONSE missing or success != true
├── SettlementNotConfirmed  # receipt missing / status 0 / unmined after retries — carries tx_hash
└── SettlementMismatch      # on-chain transfer != expected (amount / payer / pay_to)
```

- `client.pay` raises these; it never swallows. Pre-flight errors (`OfferOverCap`,
  `NetworkNotAllowed`, `InsufficientBalance`, `NoSatisfiableOffer`) fire before
  anything is signed or moved.
- `RealX402Executor` **re-raises** `PaymentError` unchanged. The agent (Week 5
  planner) owns retry / try-another-vendor / escalate.
- If an agent lets a `PaymentError` escape, it propagates out of `run_eval` —
  same rule as Week 2: a crash or infra failure is a bug, not a graded `FAIL`. An
  agent that wants a graded outcome must catch it and record an escalation.
- `SettlementNotConfirmed` is the one case where money may have moved but
  confirmation failed; it carries the tx hash. `PaymentOutcome` is never returned
  with `paid=True` in that case.

## Testing

Four tiers.

### CI — fast, deterministic, read-only or offline

| Test | What |
|---|---|
| `test_payments_constants.py` | Read-on-chain pinning: `symbol()`/`decimals()`, `eth_chainId`, facilitator `/discovery/resources` → 200. Retries a public-RPC list; skips with a message (never silent) if all unreachable. |
| `test_payments_wallet.py` | `LocalWallet` from a test-generated throwaway key: address derivation, `x402_signer()` produces a working signer, `usdc_balance()` parses a `balanceOf` result (read-only against a known address, or mocked). |
| `test_payments_settlement.py` | `verify_settlement` against the two golden historical txs (Week-1 Sepolia `0x1b1b78e2…dd309d`, mainnet `0x44cb0f1e…cd43fcc3`): exact transfer, reconciles with a correct `ExpectedSettlement`, and `matches_expected=False` + a `mismatch` string for a wrong one. |
| `test_payments_offer_parsing.py` | `inspect_offer` against **recorded** 402 payloads: verbatim Week-1 ottoai / apitoll / bitrefill `payment-required` headers, plus a synthetic Permit2-only entry and an `x402Version: 1` entry. Fully offline. Asserts satisfiability, `best_satisfiable`, `OfferOverCap` detection. |
| `test_payments_errors.py` | Pre-flight rejects raise the right `PaymentError` subclass (offline: a stub endpoint / recorded payloads). |
| `test_executor_reconciliation.py` | `SyntheticExecutor` + an agent that fabricates a `Purchase` without calling it → `UNVERIFIED_CLAIM`; an agent that calls the executor → graded `PASS` on the verified amount. Offline. |

These files are picked up automatically by the existing `evals.yml`
`harness-tests` job.

### `@pytest.mark.integration` — NOT CI (needs testnet funds / a live seller)

| Test | What |
|---|---|
| `test_payments_integration.py` | Start the `payments/testing` Flask seller (Sepolia config); `pay()` end to end with a testnet-funded wallet; assert `PaymentOutcome.paid` and an independent `verify_settlement`. Plus a 404 route → `UnexpectedStatus`, a Permit2-only route → `NoSatisfiableOffer`. |
| `test_harness_real_x402.py` | A `real_x402` task spec + the seller fixture + `RealX402Executor` → `run_eval` grades a real Base Sepolia settlement; assert `settled_tx_hashes` populated and the outcome graded on the verified amount. |

### `@pytest.mark.manual` — run once, recorded

| Test | What |
|---|---|
| `test_payments_mainnet_gate.py` | One real payment against a live Bazaar endpoint on Base **mainnet** (~$0.001 from the funded `0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0` wallet); `verify_settlement` confirms it on mainnet. The tx hash + verification recorded in a short `docs/` note (`docs/week3-mainnet-gate.md`). Exercises the permanent `payments/` module, not a throwaway script. |

### Config

`pytest.ini` (or `pyproject.toml`) default: `addopts = -m "not integration and
not manual"`, plus marker registration. `python -m pytest` locally and in CI
skips the marked tiers unless explicitly selected (`-m integration`).

New environment variables, documented in a new `.env.example`:

| Var | Purpose |
|---|---|
| `X402_WALLET_KEY` | Throwaway spender private key (0x…). Required for `pay()` and the marked tests; unset for CI. |
| `BASE_SEPOLIA_RPC_URL` | Optional override for the Sepolia read RPC. |
| `BASE_MAINNET_RPC_URL` | Optional override for the mainnet read RPC. |

`.gitignore` already covers `.env`.

## Out of scope (deferred, not forgotten)

- **Spend Permission** — EIP-712 capped/revocable authorization sign / register /
  spend / revoke over a user's Base Account → **Week 4**. Wk3's spender wallet is
  directly funded; the custody-sensitive flow is Wk4.
- **Flask API, PostgreSQL schema, Docker** — separable infrastructure; own specs.
- **CDP Server Wallet v2** — seam only (`CdpWallet` raises `NotImplementedError`).
- **Permit2 transfer method** — `inspect_offer` marks it unsatisfiable; adding it
  is a later payment-path increment. Week-1 showed the SDK picks the plain entry
  when both are offered.
- **Vendor discovery / Bazaar fan-out** — the agent's concern (Week 5).
- **ReAct baseline agent** — a separate milestone (it is an agent, not payment
  infrastructure).
- **Vendor-quality / price-anomaly model** — Week 7.
- **`sign_typed_data` on `Wallet`** — added in Week 4 with the Spend Permission.

## Open items / risks

1. **The exact git requirement string.** `git+https://github.com/x402-foundation/x402@e398a9e#subdirectory=python/x402`
   with `[requests,evm]` extras must be confirmed to `pip install` on a clean
   runner in implementation task 1. If the subdirectory/extras form does not
   resolve, fall back to vendoring `python/x402` at `e398a9e` (scope decision 4's
   rejected option) and note the change.
2. **Public RPC reliability in CI.** The constant-pinning and settlement tests
   read a live RPC. Mitigated by retrying a small list and skipping-with-message
   on total failure; a flaky CI run is possible. If it proves noisy, a recorded
   `eth_call` fixture layer is the fallback (but it weakens rule 2 — decide
   deliberately).
3. **Testnet USDC for the integration tests.** The `@pytest.mark.integration`
   tier needs a Sepolia-funded throwaway wallet. The Week-1 buyer wallet holds
   ~20 test USDC on Sepolia (findings §6) — reuse it, or fund a fresh one from
   the Circle faucet.
4. **Contract-change blast radius.** Adding the `executor` parameter to
   `run_task` and the `executed` argument to `grade` touches Week-2 code that is
   already on `main`. The implementation plan sequences this so the harness stays
   green at each step.
