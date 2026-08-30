# Week 1 Gate — Findings

Fill this in as you go. This file is the only thing in `probe/` that survives week 1.
Commit it even if the verdict is RED, especially if the verdict is RED.

**Date started:** 2026-08-30
**Date concluded:**

Status: desk research done against the x402-foundation reference clone
(`C:\Users\dinky\projects\x402-reference`, repo commit `e398a9e`, 2026-08-28) and
`docs.x402.org`. **Nothing has been run on chain yet.** Every value below is marked
**doc only** until a probe run or an on-chain read confirms it.

---

## 1. Verdict

> GREEN / AMBER / RED — **PENDING.** probe_02 has not been run.

**Reasoning (two or three sentences):**
Desk research already settles the endpoint question: there is **no public x402 demo
endpoint**. Every quickstart and every Python example in the reference repo points at
`http://localhost:4021`. So the basket will be composed of self-hosted x402 sellers
(Flask + `x402` middleware) on Base Sepolia — this is the AMBER path from
`docs/WEEK1_GATE.md`, and it was always the likely outcome. The verdict stays PENDING
until one settlement lands on chain (probe_02) and rules out RED.

---

## 2. Endpoint inventory

| # | Endpoint | What it sells | Price | Asset | Network | Live? | Source of URL |
|---|---|---|---|---|---|---|---|
| 1 | `http://localhost:4021/weather` | mock weather JSON | $0.01 | USDC | `eip155:84532` (Base Sepolia) | self-hosted, not yet run | x402-reference `examples/python/servers/flask/main.py` |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |
| 5 | | | | | | | |

Count of real, live, **independently-operated** endpoints on Base: **0**
(confirmed by doc review — none are published; all examples use localhost)

Network split — Base mainnet only vs. available on Base Sepolia: **n/a yet** —
the self-hosted seller example is configured for Base Sepolia (`eip155:84532`).

---

## 3. Raw 402 response

Paste the actual payment-requirements object from `probe_01` / probe_02's first
unpaid request. Do not summarise it.

```json
(not yet captured — run the probe against a local seller)
```

**DOC ONLY — expected shape**, from the x402-reference Flask example README
(`examples/python/servers/flask/README.md`). The 402 body is `{}`; the real object
is the base64-decoded `payment-required` header:

```json
{
  "x402Version": 2,
  "error": "Payment required",
  "resource": { "url": "http://localhost:4021/weather" },
  "accepts": [
    {
      "scheme": "exact",
      "network": "eip155:84532",
      "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
      "amount": "10000",
      "payTo": "0x...",
      "maxTimeoutSeconds": 300,
      "extra": { "name": "USDC", "version": "2" }
    }
  ]
}
```

Observations on the wire format (doc only, to confirm on a real run):

- `amount` is in atomic units — `10000` = $0.01 USDC (USDC has 6 decimals).
- `network` is CAIP-2 (`eip155:84532`), not a friendly name like `base-sepolia`.
- v2 header names: `payment-required` (on the 402), `payment-signature` (on the
  retry), `payment-response` (on the settled 200). No `X-PAYMENT` — that is v1.

---

## 4. Settlement proof

| Field | Value |
|---|---|
| Transaction hash | (not yet — probe_02 not run) |
| Network | |
| Facilitator used | |
| Block explorer link | |
| Verified independently on explorer? | no |

A 200 response is not proof of settlement. Confirm the transaction on chain.

---

## 5. Language boundary decision

Does the Python x402 SDK support Base / Base Sepolia for the `exact` scheme?

> **yes**

**Evidence (link and quote):**
- Source: `docs.x402.org/getting-started/quickstart-for-sellers`, and the reference
  clone `x402-foundation/x402` @ `e398a9e`, package `x402` 2.21.0.
- The Flask seller example sets `EVM_NETWORK: Network = "eip155:84532"  # Base
  Sepolia` and registers `ExactEvmServerScheme()` directly
  (`examples/python/servers/flask/main.py`). The FastAPI example does the same.
- The requests client example
  (`examples/python/clients/requests/main.py`) uses
  `register_exact_evm_client(client, EthAccountSigner(account))` with no network
  restriction — the buyer signs against whatever network the seller's 402 names.
- The example READMEs state plainly: `eip155:84532` — Base Sepolia,
  `eip155:8453` — Base Mainnet.

**Decision:** **all-Python.** No TypeScript payments sidecar.

**Rationale:**
The `exact` EVM scheme on Base and Base Sepolia is fully present in the Python v2
SDK. Keeping one language keeps the graded artifact simple.

**Noted conflict (stale docs):** the `x402.gitbook.io` mirror still documents the
Python SDK with **v1** patterns (`X-PAYMENT` header, hand-built 3-step flow). That
contradicts the reference repo and appears stale. Trust
`docs.x402.org` + the `x402-foundation/x402` repo, not the GitBook mirror.

---

## 6. Verified constants

Every value here must have a primary source. These carry forward into the main
codebase and each one gets a test that reads it on chain.

| Constant | Value | Source URL | Verified on chain? |
|---|---|---|---|
| SDK package | `x402` 2.21.0 (`x402-foundation/x402`, `python/x402`, commit `e398a9e`) | local reference clone | n/a |
| Testnet facilitator | `https://x402.org/facilitator` — Base Sepolia + Solana devnet **only** | docs.x402.org/getting-started/quickstart-for-sellers | n/a — **doc only** |
| Mainnet facilitator (option A) | `https://api.cdp.coinbase.com/platform/v2/x402` | docs.x402.org/getting-started/quickstart-for-sellers | n/a — **doc only** |
| Mainnet facilitator (option B) | `https://facilitator.payai.network` | docs.x402.org/getting-started/quickstart-for-sellers | n/a — **doc only** |
| USDC (Base Sepolia) | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` | Circle official docs: developers.circle.com/stablecoins/usdc-contract-addresses (Testnet section, Base Sepolia) | **YES — read on chain 2026-08-30** via `https://sepolia.base.org` (chain id 84532): `symbol()` = `"USDC"`, `decimals()` = `6`; buyer `balanceOf` returned exactly the fauceted 20000000 |
| USDC (Base mainnet) | not yet sourced from primary docs | — | no |
| SpendPermissionManager | not sourced — this is a Base Account / Spend Permissions contract, not an x402 artifact; needs the Coinbase Base Account docs | — | no |
| Base mainnet chain id | `8453` → CAIP-2 `eip155:8453` | docs.x402.org/getting-started/quickstart-for-sellers + flask README | no — **doc only** |
| Base Sepolia chain id | `84532` → CAIP-2 `eip155:84532` | docs.x402.org/getting-started/quickstart-for-sellers + flask README | **YES** — RPC `eth_chainId` over `https://sepolia.base.org` returned `84532` on 2026-08-30 |

**Docs explicitly warn:** do not reuse the `x402.org/facilitator` testnet
facilitator for mainnet — use a CDP or PayAI mainnet facilitator instead.

**On-chain check, buyer wallet `0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0`
(Base Sepolia, `https://sepolia.base.org`, 2026-08-30):**

| Reading | Value |
|---|---|
| USDC `balanceOf` (raw) | `20000000` |
| USDC balance | **20.0 USDC** — Circle faucet funds confirmed arrived |
| Native ETH balance | **0** (0 wei) — as expected; only USDC was claimed |
| Tx count (nonce) | 0 — wallet has never transacted |

**Gotcha for the constant-pinning test (CLAUDE.md rule 2):** this Sepolia USDC
deployment returns `name()` = `"USDC"`, *not* `"USD Coin"` like mainnet USDC. A
pinning test must assert `symbol()` / `decimals()`, not `name()`.

**Open question now on the record:** the buyer holds 0 ETH. Whether an x402
`exact` payment on Base Sepolia needs the buyer to hold gas depends on whether
the facilitator submits (and pays gas for) the transfer. To be answered by
probe_02.

---

## 7. Cost

| Item | Amount |
|---|---|
| Testnet funds used | $0 so far |
| Mainnet USDC spent | $0 |
| Days elapsed | 1 (desk research only) |

Ceiling was $10 and five working days. Over it? No.

---

## 8. Things that contradicted the plan

The most valuable section. What did you find that the thirteen-week plan assumes
wrongly? Write it down now, while it is still surprising.

- **There is no public demo endpoint.** Both x402 quickstarts and every Python
  example in the reference repo point at `http://localhost:4021`. The first 402
  this project ever sees will come from a seller it runs itself. The week-1 gate's
  "hunt for 5 real endpoints" framing is moot — the honest answer is AMBER by
  construction, and the endpoint inventory is a self-hosted-seller inventory.
- **The v1/v2 header split is a live trap.** v1 used a single `X-PAYMENT` header
  and a hand-rolled 3-step flow; v2 uses `payment-required` / `payment-signature`
  / `payment-response` and a session wrapper that does it all. Third-party guides
  and the `x402.gitbook.io` mirror still document v1. The original
  `probe_02_settle.py` was written to the v1 pattern and has been rewritten.
- **The client SDK already ships spend controls.**
  `examples/python/clients/advanced/spend_controls.py` —
  `client.set_spend_controls({"max_amount_per_payment": "$1", "allowed_assets":
  [...]})` gives per-payment USD caps, per-asset atomic caps, and allow-listing
  out of the box. A meaningful slice of the planned **week-6 policy layer** is
  therefore table stakes, not differentiation. The "10x" framing for that layer
  needs revisiting — the project's value has to come from the *mandate* /
  multi-vendor / escalation logic, not from re-implementing per-payment caps.

---

## 9. Decision

> **Proceed with hybrid basket** (self-hosted x402 sellers on Base Sepolia),
> pending one on-chain settlement from probe_02 to rule out RED.

**Next action:**
1. Create a throwaway EVM wallet; fund it with Base Sepolia ETH (gas) and Base
   Sepolia USDC from a faucet.
2. Run the x402-reference Flask seller locally on `:4021` with that wallet's
   address as `EVM_ADDRESS`.
3. `python probe\probe_01_observe_402.py http://localhost:4021/weather` — paste the
   real decoded 402 into section 3.
4. `python probe\probe_02_settle.py http://localhost:4021/weather` — record the
   settlement tx hash + network in section 4 and verify it on the Base Sepolia
   explorer.
5. Set the verdict in section 1.
