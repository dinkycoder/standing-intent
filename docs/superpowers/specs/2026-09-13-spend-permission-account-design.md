# Week 4 — Spend Permission `account` Provisioning: Design

**Date:** 2026-09-13
**Status:** approved, pending implementation plan

## Why this exists

PR #8 (`tests/test_payments_spend_permission.py`, draft, intentionally red) assumes a
`spend_permission_account` fixture that does not exist yet, and flags the real gap
behind it: the `account` side of a Base Spend Permission must be a Coinbase Smart
Wallet (ERC-4337) that `SpendPermissionManager` has been added as an owner of — not a
plain EOA like the `LocalWallet` this repo already uses for x402 payments
(`payments/wallet.py`). This spec designs how that account gets provisioned, how a
permission over it gets signed and registered, and — the part that took two rounds
of correction to get right — how a purchase actually reaches a vendor without this
project's own wallet taking custody of user funds in the general case.

## The mechanism, explained

A Coinbase Smart Wallet is an ERC-4337 smart-contract account with one or more
"owners" (an address or a WebAuthn passkey), deployed via
`CoinbaseSmartWalletFactory`. `SpendPermissionManager` (verified in PR #7,
`SPEND_PERMISSION_MANAGER`) works by being added as an **owner** of that account.
Its own contract code only ever executes a narrowly scoped `spend()` within an
approved, capped, time-boxed permission — so admitting it as an owner doesn't hand
away the wallet; it admits a second owner whose entire code path is public,
immutable, and already the exact contract this project verified on-chain.

Two ways to make it an owner: bake it into the account's *initial* owner set at
creation, or call `addOwnerAddress()` afterward. The latter is `onlyOwner`
(`src/MultiOwnable.sol`) — it must be invoked as a call *from the account itself*,
which needs a signed ERC-4337 UserOperation and a bundler. The former needs nothing
but one plain transaction. **Design choice: bake it in at creation.**

## Sources (same rigor as PR #7 — CLAUDE.md rule 2)

- `coinbase/smart-wallet`, `src/CoinbaseSmartWalletFactory.sol`,
  `src/MultiOwnable.sol`, `src/CoinbaseSmartWallet.sol`, `src/ERC1271.sol` — fetched
  directly via the GitHub contents API (not a summarizer), `main` branch, 2026-09-13.
- `coinbase/spend-permissions`, `src/SpendRouter.sol` — same method, same date.
- Factory address (from the smart-wallet README's "Deployments" table, **not yet
  on-chain verified — flagged below**): v1.1 `0xBA5ED110eFDBa3D005bfC882d75358ACBbB85842`,
  deployed via the Safe Singleton Factory ("same address across 248 chains" per the
  README's own claim — this needs the same on-chain pin test discipline as
  `SPEND_PERMISSION_MANAGER` before it's trusted, not just quoted).

## Provisioning the account

```
owners = [abi.encode(test_owner.address), abi.encode(SPEND_PERMISSION_MANAGER)]
address = CoinbaseSmartWalletFactory.getAddress(owners, nonce)   # counterfactual, computable off-chain
CoinbaseSmartWalletFactory.createAccount(owners, nonce)          # plain tx, any funded EOA can call it
```

`createAccount` is `external payable`, no modifier — permissionless, no bundler, no
passkey, no CDP API. That last point matters: **CDP API access is still blocked by
business verification** (the same reason `CdpWallet` in `payments/wallet.py` is a
stub, per the Week-3 design). Coinbase's own higher-level path
(`cdp.evm.getOrCreateSmartAccount(..., enableSpendPermissions=True)`) depends on that
same blocked API. This design deliberately routes around it with raw `web3.py` +
`eth_account` calls against the verified public contracts, the same workaround
already applied to `LocalWallet` vs `CdpWallet`.

**Test-only owner key.** `test_owner` above is a throwaway EOA
(`SPEND_PERMISSION_ACCOUNT_KEY`, already referenced in PR #8's draft), mirroring the
existing `X402_WALLET_KEY` throwaway-spender precedent. **This is never a real
user's key.** In the real product flow, index-0 owner is the actual end user's own
Smart Wallet — created and owned through their own Base Account, signed with their
own key or passkey. Standing Intent never generates, stores, or has access to it.
This fixture exists only to prove the mechanism end-to-end on Base Sepolia.

## Signing — the trap that needs its own test

`SpendPermissionManager.approveWithSignature` validates through the account's
ERC-1271 `isValidSignature`, which does **not** check a signature over the
permission's own EIP-712 hash directly — it wraps that hash again, through the
*Smart Wallet's own* domain, inside a `CoinbaseSmartWalletMessage(bytes32 hash)`
struct (`src/ERC1271.sol`, confirmed by direct source read, not inferred):

```
inner = SpendPermissionManager.getHash(permission)      # its own EIP-712 hash, domain = ("Spend Permission Manager", "1")
outer = keccak256("\x19\x01" || account.domainSeparator() ||
                   keccak256(abi.encode(keccak256("CoinbaseSmartWalletMessage(bytes32 hash)"), inner)))
        # account.domainSeparator() uses domain = ("Coinbase Smart Wallet", "1"), chainId, verifyingContract = account address
(r, s, v) = ecdsa_sign(outer, owner_key)
signature = abi.encode(SignatureWrapper{ ownerIndex: 0, signatureData: abi.encodePacked(r, s, v) })
```

Signing `inner` directly produces a signature that **silently fails** — the contract
reverts `InvalidSignature`, not a helpful "you forgot the wrapper." This gets an
isolated, offline-testable unit test (hand-derive one test vector, compare against
our Python implementation) before it's ever exercised against a live account —
catching the mistake in seconds instead of in a live-chain integration test.

## Where the money actually goes — two paths, chosen by `Mandate.vendor_allowlist`

`SpendPermissionManager.spend(permission, value)` has **no recipient argument** — it
always transfers to `permission.spender`, fixed at signing time. A naive design has
our own agent wallet receive the user's USDC first, then make a second, separate
x402 payment forwarding it to the vendor. That is CLAUDE.md's third tripwire —
"receive funds and forward them" — even when each hop is fast and exactly scoped.

**First correction made while writing this:** `coinbase/spend-permissions/src/SpendRouter.sol`
solves this — `spendAndRoute()` pulls via `spend()` and forwards to a `recipient`
(decoded from the permission's `extraData`) **in one atomic transaction**, so our
wallet never sits in the token path.

**Second correction, made next:** `extraData` (and therefore `recipient`) is part of
the struct `SPEND_PERMISSION_TYPEHASH` signs over. A signed permission is locked to
**one fixed recipient** — fine for a subscription, wrong for an agent whose entire
premise is buying from vendors discovered *after* the one signature is made. A
different vendor is a different hash is a different signature is back to the user.

The resolution, using something already in this repo (`Mandate.vendor_allowlist`,
`evals/models.py`):

| Mandate shape | Path | Custody |
|---|---|---|
| **Has `vendor_allowlist`** (bounded, known set at signing time) | `SpendPermissionManager.approveBatchWithSignature` — one signature batch-approves one `SpendRouter`-routed, fixed-recipient permission **per allowlisted vendor** (`spender` = our deployed `SpendRouter`, `extraData` = `encodeExtraData(executor=our wallet, recipient=vendor's x402 pay_to)`). | Clean — funds move account → vendor atomically; our wallet only ever appears as the authorized `executor`. |
| **No `vendor_allowlist`** (open-ended, vendors discovered dynamically) | Bare `spend(permission, value)`, `spender` = our own wallet directly, no router, no `extraData` routing. Vendor payment is a **second**, separate x402 payment (`payments.client.pay`, already built) executed immediately after, no batching. | **The custodial hop.** Explicitly logged. This is exactly the money-transmission question `docs/PMF_AND_BUILD_PLAN.md`'s Caveats section already says needs a formal opinion before mainnet — this makes that opinion's stakes concrete, not abstract. **Gate: this path does not go to mainnet before that opinion exists.** |

Both were put to the user explicitly rather than picked unilaterally, given rule 1 is
the single most legally load-bearing rule in the project. Decisions: deploy our own
`SpendRouter` instance (below), and accept the custodial hop for the open-ended case
rather than require an allowlist on every mandate or add a per-new-vendor escalation
(which would tax the one metric this whole project is judged on).

## Deploying our own `SpendRouter`

`SpendRouter` is not deployed to any chain yet (`coinbase/spend-permissions`
README lists it `TBD`). It's a generic, MIT-licensed, parameterless-beyond-its-
constructor contract (`constructor(SpendPermissionManager spendPermissionManager)`)
— anyone can deploy their own instance bound to the canonical
`SpendPermissionManager`, and it behaves identically for any executor/recipient
pair. **This is new scope**: this repo has no Solidity build step today. Plan:
install Foundry (works on native Windows or WSL; confirm which at implementation
time), clone `coinbase/spend-permissions` at the commit already pinned in PR #7
(`e0004e6`), `forge build`, deploy to Base Sepolia (later mainnet) from a funded
throwaway key. `SpendRouter.sol` pulls in `solady` (`Multicallable`,
`SafeTransferLib`) and a `magicspend` library as external imports — both resolved by
the upstream repo's own `foundry.toml`/`lib/` submodules, not something we vendor
ourselves.

**On-chain pin, once deployed:** unlike `SPEND_PERMISSION_MANAGER`, this address is
*our own* deployment, not a canonical Coinbase one — verifying it means confirming
*our* deployment actually is what we meant to deploy. Pin test: call
`SpendRouter.PERMISSION_MANAGER()` on the deployed instance and assert it equals the
already-verified `SPEND_PERMISSION_MANAGER` constant. Recorded like the Week-3
mainnet gate (`docs/week3-mainnet-gate.md`) — one real deployment, the address and
tx hash written down, not re-derived from memory.

## Architecture

```
payments/
  spend_permission.py   # SpendPermission dataclass; sign/register/spend/revoke
                         # (the open-ended, bare-spend path)
  spend_router.py        # encode_extra_data(); spend_and_route() / batch approve
                         # (the allowlisted, atomic-routing path); deploy helper
  constants.py            # + SMART_WALLET_FACTORY, SPEND_ROUTER (ours, once deployed)

tests/
  test_smart_wallet_constants.py     # on-chain pin: factory + our SpendRouter      -- CI (once deployed)
  test_spend_permission_signing.py   # nested EIP-712 hash math, offline            -- CI
  test_payments_spend_permission.py  # PR #8, fills in once the above exists        -- integration
```

### `payments/spend_permission.py`

```python
@dataclass(frozen=True)
class SpendPermission:
    account: str
    spender: str            # our wallet (open-ended path) or our SpendRouter (allowlisted path)
    token: str               # resolved via constants.USDC_BY_CHAIN[network], or NATIVE_TOKEN
    allowance: Decimal
    period_seconds: int
    start: int = 0
    end: int = 281474976710655   # 2**48 - 1: the contract's uint48 "no expiry" sentinel
    salt: int = 0
    extra_data: bytes = b""

class SmartWalletAccount:
    address: str
    owner_wallet: Wallet     # signs on the account's behalf, ownerIndex=0

def provision_smart_wallet_account(owner: Wallet, network: int, nonce: int = 0) -> SmartWalletAccount: ...
def sign_spend_permission(permission, account: SmartWalletAccount, network: int) -> bytes: ...
def register_spend_permission(permission, signature, spender: Wallet, network: int) -> str: ...   # tx_hash
def register_spend_permission_batch(permissions, signature, spender: Wallet, network: int) -> str: ...
def spend(permission, value: Decimal, spender: Wallet, network: int) -> str: ...       # open-ended path
def revoke_spend_permission(permission, account_or_spender: Wallet, network: int) -> str: ...
```

### `payments/spend_router.py`

```python
def encode_extra_data(executor: str, recipient: str) -> bytes: ...   # abi.encode(executor, recipient)
def spend_and_route(permission, value: Decimal, spender: Wallet, network: int) -> str: ...    # tx_hash
def spend_and_route_with_signature(permission, value, signature, spender: Wallet, network: int) -> str: ...
def deploy_spend_router(deployer: Wallet, network: int) -> str: ...   # one-time; records to docs/
```

## Non-custody check (CLAUDE.md rule 1)

- **Allowlisted-mandate path:** trips none of the four tripwires. No key of ours can
  move funds unilaterally (our wallet is only the authorized `executor`, checked by
  the router's own `_validateAndDecodeExtraData`); no pooling (one Smart Wallet per
  user, always); no receive-and-forward (the router, not us, holds funds for the
  span of one atomic transaction, then forwards — we never do); no fee inside the
  flow.
- **Open-ended-mandate path:** **does** trip tripwire 3 (receive and forward),
  narrowly and by necessity — it is the only mechanism able to honor "one signature,
  any future vendor" at all. Mitigated by: exactly-scoped amounts (never more than
  one purchase's `spend()` at a time), no batching, immediate forward with no
  intervening logic. Not mitigated away: **this is a real open legal question**, not
  a solved one. `docs/PMF_AND_BUILD_PLAN.md`'s Caveats section already calls for a
  formal money-transmission opinion before mainnet; this design makes that
  concrete rather than deferring it further. **Gate: the open-ended path is
  Sepolia-only until that opinion exists.** This is stated here so it isn't lost
  between a design doc and an implementation PR.

## Out of scope (deferred, not forgotten)

- Foundry/solc toolchain setup itself — a prerequisite task, not part of this design.
- The real product's account-creation UX (how an actual user ends up with a Smart
  Wallet at all) — Week 4 proves the mechanism; onboarding UX is later.
- `SpendPermissionBatch` beyond what the allowlisted path needs.
- Mainnet deployment of our `SpendRouter` and any open-ended-path mainnet use — both
  gated as above.

## Open items / risks

1. **Factory address not yet on-chain verified.** Quoted from the README only; needs
   the same on-chain pin test discipline as `SPEND_PERMISSION_MANAGER` (PR #7)
   before `payments/constants.py` trusts it. First implementation task.
2. **v1 vs v1.1.** The interface this design was traced against (`main` branch HEAD)
   is presumed to be v1.1 (the current one); needs confirming which version's
   `implementation` the factory actually proxies to, and that `MultiOwnable`/
   `SignatureWrapper` are unchanged between versions, before relying on the exact
   call shapes above.
3. **Foundry on Windows.** CLAUDE.md's environment is Windows/PowerShell first;
   confirm whether `forge` runs natively or needs WSL before scripting the deploy.
4. **The legal opinion gate is a real dependency,** not a formality — the
   open-ended path's design is sound *given* that gap is accepted as temporary and
   Sepolia-scoped, not because the gap is closed.
