# Week 1 Gate — Findings

Fill this in as you go. This file is the only thing in `probe/` that survives week 1.
Commit it even if the verdict is RED, especially if the verdict is RED.

**Date started:** 2026-08-30
**Date concluded:** 2026-08-30

Status: **first end-to-end settlement succeeded on Base Sepolia** on 2026-08-30
(probe_02, tx `0x1b1b78e2fcba693ace023bb8af2ae19277f597d6f82b6a2adcc6bd6765dd309d`).
The self-hosted x402 Flask seller returned a real 402, the buyer signed an
authorization, the facilitator settled it on chain, and the paid resource came
back. Desk research was done against the x402-foundation reference clone
(`C:\Users\dinky\projects\x402-reference`, repo commit `e398a9e`, 2026-08-28) and
`docs.x402.org`.

---

## 1. Verdict

> **AMBER** — proceed with a hybrid basket.

**Reasoning (two or three sentences):**
There is **no public x402 demo endpoint** — every quickstart and every Python
example in the reference repo points at `http://localhost:4021` — so fewer than
five real independently-operated endpoints exist (zero, in fact). But **settlement
works**: a signed authorization against a self-hosted Flask seller settled on Base
Sepolia end to end. That is exactly the AMBER case in `docs/WEEK1_GATE.md`: compose
the basket from self-hosted `x402[flask]` endpoints, honestly labelled as a
synthetic vendor environment. RED (settlement cannot be made to work) is ruled out.

---

## 2. Endpoint inventory

| # | Endpoint | What it sells | Price | Asset | Network | Live? | Source of URL |
|---|---|---|---|---|---|---|---|
| 1 | `http://localhost:4021/weather` | mock weather JSON | $0.01 | USDC | `eip155:84532` (Base Sepolia) | **yes — settled** tx `0x1b1b78e2…dd309d` | x402-reference `examples/python/servers/flask/main.py` |
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

The 402 status body is literally `{}`. The real payment terms travel in the
base64-encoded `payment-required` **header**; decoded, they are:

> ⚠️ **RECONSTRUCTED** from the seller's route config
> (`examples/python/servers/flask/main.py`, `GET /weather`) plus the confirmed
> settlement values below. Field names/order and the SVM option's exact shape are
> not guaranteed byte-for-byte. **Replace this with the verbatim decoded object
> that `probe_02_settle.py` printed to the terminal.**

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
      "payTo": "0xa31C8f81A66C779A312b4aFA85aD38c8436B4F6D",
      "maxTimeoutSeconds": 300,
      "extra": { "name": "USDC", "version": "2" }
    },
    {
      "scheme": "exact",
      "network": "solana:EtWTRABZaYq6iMfeYKouRu166VU2xqa1",
      "amount": "10000",
      "payTo": "11111111111111111111111111111111",
      "maxTimeoutSeconds": 300
    }
  ]
}
```

Observations on the wire format:

- **The 402 body is empty (`{}`).** Anything that reads the JSON body for payment
  terms will find nothing — the terms are in the `payment-required` header,
  base64-encoded. The `x402_requests` session wrapper reads the header; a naive
  client that only inspects the body will silently fail.
- **`accepts` is a LIST, not a single object.** The seller advertises a menu of
  payment options (here: pay on Base Sepolia in USDC, *or* pay on Solana devnet)
  and the **buyer chooses** which one to satisfy. The probe's EVM registration
  picks the `eip155:84532` entry. Vendor evaluation in the main build has to treat
  every 402 as "one or more offers," not "the price."
- **`amount` is atomic units.** `"10000"` = $0.01 because USDC has 6 decimals
  (10000 / 10^6 = 0.01). It is a decimal string, not a number. Never divide by
  10^18 out of Ethereum habit — USDC is 10^6.
- **`maxTimeoutSeconds` is 300.** The signed authorization is only valid for five
  minutes. An agent that signs, then queues, then submits late will have its
  payment rejected as expired. Any planner that batches or delays payment steps
  needs to re-sign inside that window.
- **`network` is CAIP-2** (`eip155:84532`), not a friendly name like
  `base-sepolia`.
- v2 header names: `payment-required` (on the 402), `payment-signature` (on the
  retry), `payment-response` (on the settled 200). No `X-PAYMENT` — that is v1.

---

## 4. Settlement proof

| Field | Value |
|---|---|
| Transaction hash | `0x1b1b78e2fcba693ace023bb8af2ae19277f597d6f82b6a2adcc6bd6765dd309d` |
| Network | `eip155:84532` (Base Sepolia) |
| Payer (buyer) | `0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0` |
| Pay-to (seller) | `0xa31C8f81A66C779A312b4aFA85aD38c8436B4F6D` |
| Amount | `10000` atomic = **$0.01 USDC** (6 decimals) |
| Facilitator used | `https://x402.org/facilitator` (the seller's config, not the buyer's) |
| Facilitator response | `{"success": true, ...}` |
| Resource returned after payment | `{"report":{"temperature":70,"weather":"sunny"}}` |
| Block explorer link | https://sepolia.basescan.org/tx/0x1b1b78e2fcba693ace023bb8af2ae19277f597d6f82b6a2adcc6bd6765dd309d |
| Verified independently on explorer? | **NOT YET DONE** — checking basescan next |

A 200 response is not proof of settlement. The facilitator's `{"success": true}`
plus the returned resource is strong evidence; independent confirmation on
BaseScan is still pending.

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

**Open question — now ANSWERED by probe_02:** the buyer held 0 ETH and had never
transacted, and the payment still settled. The buyer does **not** need gas. The
facilitator submits the on-chain transfer and pays its gas; the buyer only signs
an off-chain authorization. See section 8, finding 1.

---

## 7. Cost

| Item | Amount |
|---|---|
| Testnet funds used | 0.01 testnet USDC (of 20 fauceted) + 0 ETH — no real value |
| Mainnet USDC spent | $0 |
| Days elapsed | 1 |

Ceiling was $10 and five working days. Over it? No — well under both.

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

- **THE BUYER NEEDS NO GAS.** The buyer wallet held 0 ETH and had 0 prior
  transactions, and the payment still settled (section 4). The facilitator
  submits and pays for the on-chain transfer; the buyer only signs an off-chain
  authorization. This matters more than it looks: an agent that never holds gas
  needs **one** funded asset instead of two, and an entire failure category —
  *agent stalls mid-basket because it ran out of gas* — simply does not exist.
  Card-rail competitors have no equivalent property. Feed this into the 10x
  argument alongside the Spend Permission point.

- **Spend-control comparison is "at most," not "less than."** A $0.01 price
  cleared a $0.01 `max_amount_per_payment` cap exactly — the boundary is
  inclusive. Worth an explicit boundary test later (price == cap passes, price
  == cap + 1 atomic unit fails).

- **The SDK must be installed into the agent's own environment.** Installing
  `x402` for the seller (the Flask example's `.venv`) does nothing for the buyer.
  The agent needs its own install, and it must come **from the local reference
  clone, not PyPI**, because the `x402` name is polluted there (TRON forks,
  Solana-only ports, unrelated commercial packages).

---

## 9. Decision

> **Proceed to week 2**, with a hybrid basket: self-hosted `x402[flask]` sellers
> on Base Sepolia, labelled in the README and writeup as a synthetic vendor
> environment. Settlement is proven; RED is ruled out.

**Remaining week-1 close-out:**
1. Confirm tx `0x1b1b78e2…dd309d` on https://sepolia.basescan.org — check the
   USDC `Transfer` log is buyer → seller for `10000`, and note who paid gas
   (expected: the facilitator's relayer, not the buyer). Update section 4's
   "verified independently" row.
2. Paste the verbatim decoded `payment-required` object from the probe run into
   section 3, replacing the reconstruction.
3. Archive `probe/` to `docs/archive/probe/` per `probe/README.md` (findings.md
   is the part that survives), or leave until end of week 1.

**Carried into the main build:**
- Vendor evaluation must treat each 402's `accepts` as a menu and pick.
- Re-sign authorizations inside the 300s window; never queue a signed payment.
- The agent gets its own `x402[requests,evm]` install from the local clone.
- Buyer wallet is funded in USDC only — no ETH, by design.
