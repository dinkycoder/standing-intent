# Week 1 Gate — Findings

Fill this in as you go. This file is the only thing in `probe/` that survives week 1.
Commit it even if the verdict is RED, especially if the verdict is RED.

**Date started:** 2026-08-30
**Date concluded:** 2026-08-30

Status (2026-08-30): **verdict GREEN, pending one mainnet settlement.**
- **Settlement proven** — probe_02, tx
  `0x1b1b78e2fcba693ace023bb8af2ae19277f597d6f82b6a2adcc6bd6765dd309d`: a
  self-hosted Flask seller returned a real 402, the buyer signed, the facilitator
  settled on chain (Base Sepolia), and the paid resource came back.
- **Vendor supply proven** — probe_03: the public x402 Bazaar discovery API
  (Coinbase CDP / PayAI, no auth) lists 14k–28k live resources, mostly on Base;
  13 of 16 independent endpoints spot-checked returned a live 402, all Base
  mainnet USDC.
- **Open:** one real payment against a live mainnet endpoint (~$1 USDC) to fully
  close the GREEN "settlement confirmed" clause on mainnet.

Desk research was done against the x402-foundation reference clone
(`C:\Users\dinky\projects\x402-reference`, repo commit `e398a9e`, 2026-08-28) and
`docs.x402.org`.

---

## 1. Verdict

> **GREEN** — a real multi-vendor basket is possible on Base. One cheap
> confirmation step remains (a mainnet settlement); see the caveat below.

**Reasoning:**
1. **Settlement works and is confirmed on chain** (section 4: BaseScan block
   46175913, Success, USDC buyer → seller, gas paid by the facilitator). RED is
   ruled out.
2. **Real, independently-operated, live, priced x402 endpoints on Base exist in
   large numbers** (section 2, probe_03). The public x402 Bazaar discovery API
   (Coinbase CDP, no account or key required) lists **14,324** resources;
   PayAI's lists **27,855**. In a 600-item sample from CDP, **every** item
   advertised a Base network and there were **275 distinct operator domains**.
   Of 16 distinct-domain endpoints hit with unpaid GETs, **13 returned a live
   HTTP 402** with valid v2 payment terms — all on Base **mainnet**
   (`eip155:8453`), all priced in USDC, $0.001–$5.00. Real commercial operators
   among them: Bitrefill (gift cards), Apify (web scraping), OneSource (RPC).

`docs/WEEK1_GATE.md` GREEN = "five or more real, live, independently-operated
x402 endpoints, priced, on Base, with settlement confirmed." The endpoint bar is
cleared many times over.

**Caveat — the "settlement confirmed" clause is confirmed on _testnet_, not yet
against a real mainnet endpoint.** The live endpoints are Base mainnet only, so
closing GREEN fully means one real payment with a few dollars of real USDC via a
mainnet facilitator (`api.cdp.coinbase.com/platform/v2/x402` or
`facilitator.payai.network`). This is inside the $10 gate ceiling and is the only
open item. Until it is done, treat the verdict as **GREEN pending one mainnet
settlement**.

**Quality caveat (not a verdict change):** the 14k catalog is bimodal — a
minority are real commercial services; the majority are toy/demo endpoints
(coin flips, riddles, fortunes). A non-trivial basket is composable from the
real ones, but the number of serious vendors *per category* is far smaller than
the raw count suggests. This shapes the demo scenario, not the pass/fail.

---

## 2. Endpoint inventory

**Discovery method.** Machine-readable discovery **is** available and needs no
credentials. The x402 Bazaar discovery API is a plain public GET:

- `https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources` (Coinbase
  CDP) → `200`, `pagination.total` = **14324**
- `https://facilitator.payai.network/discovery/resources` (PayAI) → `200`,
  `pagination.total` = **27855**

No CDP account, no API key. (The CDP *business-verification* wall the author hit
is for issuing CDP API keys / running a CDP-hosted facilitator — it does **not**
gate reading the catalog.) Survey run 2026-08-30: pulled a 600-item sample from
CDP; **all 600** advertised a Base network; **275 distinct operator domains**.
Then hit 16 distinct-domain endpoints with unpaid GETs.

| # | Endpoint | What it sells | Price | Asset | Network | Live? (unpaid GET, 2026-08-30) | Source of URL |
|---|---|---|---|---|---|---|---|
| 1 | `http://localhost:4021/weather` | mock weather JSON (self-hosted) | $0.01 | USDC | `eip155:84532` Base Sepolia | **yes — settled** tx `0x1b1b78e2…dd309d` | x402-reference flask example |
| 2 | `https://api.bitrefill.com/x402/gift-cards/search` | gift-card / voucher catalogue, 10k+ brands, 180+ countries | $0.002 | USDC | `eip155:8453` Base mainnet (also Arbitrum, Polygon, Solana) | **yes — HTTP 402**, valid v2 terms | CDP Bazaar |
| 3 | `https://agi.apify.com/protocols/x402/prepaid-tokens` | Apify web-scraping / automation marketplace (prepaid credit) | $1.00 | USDC | `eip155:8453` (also Solana) | **yes — HTTP 402** | CDP Bazaar |
| 4 | `https://api.onesource.io/api/chain/erc20-balance` | Ethereum RPC-as-API — one of a family (`block-number`, `tx/:hash`, `nonce/:address`, `erc20-transfers`, …) | $0.003 | USDC | `eip155:8453` | **yes — HTTP 402** (`exact` + `batch-settlement`) | CDP Bazaar |
| 5 | `https://laso.finance/get-card` | prepaid debit card for US use | $5.00 | USDC | `eip155:8453` (also Solana) | **yes — HTTP 402** | CDP Bazaar |
| 6 | `https://x402.ottoai.services/crypto-news` | real-time crypto news + sentiment | $0.001 | USDC | `eip155:8453` (also Solana) | **yes — HTTP 402** | CDP Bazaar |
| 7 | `https://kronossignals.com/api/v1/liquidations/btc` | forward liquidation cluster maps | $0.02 | USDC | `eip155:8453` | **yes — HTTP 402** | CDP Bazaar |
| 8 | `https://crypto.apitoll.cloud/v1/crypto/price` | crypto spot prices by ticker / id / chain:addr | $0.001 | USDC | `eip155:8453` (also Solana) | **yes — HTTP 402** | CDP Bazaar |

Also returned a live 402 in the same probe (toy / demo tier, all `eip155:8453`
USDC, ~$0.001): `coinflip402.vercel.app`, `riddlex402.vercel.app`,
`memegeneratorx402.vercel.app`, `x402lifeadvice.vercel.app`,
`ladyfortunalx402.vercel.app`, `api.loyalspark.online` (loyalty platform).

Not live on an unpaid GET (still real x402 services, just not GET-probeable):
`stableenrich.dev`, `stableupload.dev` (both `405` — POST-only endpoints);
`api.exa.ai/search` (`404` — catalog path stale or requires query params).

**Count of real, live, independently-operated, priced endpoints on Base:**
**13 confirmed live in a 16-endpoint spot check**, drawn from **275 distinct Base
operator domains in a 600-item sample**, from a catalog of **14,324** (CDP) /
**27,855** (PayAI). The GREEN bar of 5 is cleared comfortably.

**Network split.** All 13 live endpoints were Base **mainnet** (`eip155:8453`).
**Zero** live third-party endpoints on Base Sepolia — testnet is for self-hosted
sellers only. The catalog also contains non-CAIP-2 `network: "base"` strings and
some `x402Version: 1` entries; a consumer must tolerate both.

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
| Verified independently on explorer? | **YES** — BaseScan, 2026-08-30 |
| Block | 46175913 (Base Sepolia) |
| Status | Success |
| From (tx sender) | `0xd407e409E34E0b9afb99EcCeb609bDbcD5e7f1bf` — the facilitator's relayer; **neither buyer nor seller wallet** |
| Interacted with | USDC contract `0x036CbD53842c5426634e7929541eC2318f3dCF7e` |
| ERC-20 transfer in the tx | `0xA85F…2CB0` → `0xa31C…4F6D`, 0.01 USDC |
| ETH value moved | 0 |
| Gas fee | 0.000000629813860576 ETH — **paid by the facilitator**, not by either of our wallets |

A 200 response is not proof of settlement — this is. BaseScan shows the USDC
`Transfer` (buyer → seller, 0.01) inside a transaction **sent and paid for by the
facilitator relayer** `0xd407…f1bf`. The buyer wallet is not the sender and paid
no gas. This is the on-chain proof behind the no-gas-needed finding in section 8.

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
| Mainnet facilitator (option A) | `https://api.cdp.coinbase.com/platform/v2/x402` | docs.x402.org/getting-started/quickstart-for-sellers | discovery sub-path `GET /discovery/resources` returned `200` (no auth) on 2026-08-30; settle/verify not yet exercised |
| Mainnet facilitator (option B) | `https://facilitator.payai.network` | docs.x402.org/getting-started/quickstart-for-sellers | discovery sub-path `GET /discovery/resources` returned `200` (no auth) on 2026-08-30; settle/verify not yet exercised |
| USDC (Base Sepolia) | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` | Circle official docs: developers.circle.com/stablecoins/usdc-contract-addresses (Testnet section, Base Sepolia) | **YES — read on chain 2026-08-30** via `https://sepolia.base.org` (chain id 84532): `symbol()` = `"USDC"`, `decimals()` = `6`; buyer `balanceOf` returned exactly the fauceted 20000000 |
| USDC (Base mainnet) | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | observed as the `asset` in the live 402 of ~13 independent Bazaar endpoints (2026-08-30); Circle docs mainnet section not re-fetched — do so before pinning | **YES — read on chain 2026-08-30** via `https://mainnet.base.org` (chain id 8453): `name()` = `"USD Coin"`, `symbol()` = `"USDC"`, `decimals()` = `6` |
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

**Gotcha for the constant-pinning test (CLAUDE.md rule 2) — now confirmed both
ways:** Base **Sepolia** USDC returns `name()` = `"USDC"`; Base **mainnet** USDC
returns `name()` = `"USD Coin"` (both read on chain 2026-08-30). `symbol()` is
`"USDC"` and `decimals()` is `6` on both. A pinning test must assert
`symbol()` / `decimals()`, never `name()`.

**Open question — now ANSWERED by probe_02:** the buyer held 0 ETH and had never
transacted, and the payment still settled. The buyer does **not** need gas. The
facilitator submits the on-chain transfer and pays its gas; the buyer only signs
an off-chain authorization. See section 8, finding 1.

---

## 7. Cost

| Item | Amount |
|---|---|
| Real money spent | **$0** — testnet only |
| Testnet funds used | 0.01 Base Sepolia USDC (of 20 fauceted) + 0 ETH; facilitator paid the ~6.3e-7 ETH gas |
| Mainnet USDC spent | $0 |
| Elapsed time | 1 day — 2026-08-30. Desk research, both wallets, seller setup, first settlement, and the probe_03 Bazaar survey all same day. |

Ceiling was $10 and five working days. Actual: $0 and 1 day. Well under both.
Remaining spend to fully close GREEN: **one mainnet settlement** against a real
Bazaar endpoint. Cheapest live candidates are ~$0.001 (e.g. `x402.ottoai.services`,
`crypto.apitoll.cloud`), so ~$1 of real USDC covers funding + a handful of
attempts. Still far inside the $10 ceiling.

---

## 8. Things that contradicted the plan

The most valuable section. What did you find that the thirteen-week plan assumes
wrongly? Write it down now, while it is still surprising.

- **No public *tutorial* endpoint, but a huge public *marketplace*.** Every
  quickstart and Python example targets `http://localhost:4021`, so the *first*
  402 had to come from a self-hosted seller (still true, and why probe_02 ran
  local). But probe_03 then found the opposite of scarcity: the x402 Bazaar
  discovery API is public and unauthenticated and lists **14k–28k** live
  resources, the overwhelming majority on Base. The earlier working assumption
  that this would land at AMBER "by construction" was wrong — see section 1,
  now GREEN.
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

- **Discovery is a solved problem, and it is not gated by the CDP wall.** The
  x402 Bazaar catalog is a plain public `GET /discovery/resources` on both the
  CDP facilitator (`api.cdp.coinbase.com/platform/v2/x402`) and PayAI
  (`facilitator.payai.network`) — `200`, no API key, no account. The author's
  CDP business-verification block affects issuing CDP keys / running a
  CDP-hosted facilitator, **not** reading the marketplace. The planned
  vendor-discovery component is mostly "call this endpoint and filter," which
  again trims what the build has to invent (cf. the spend-controls finding).

- **The catalog is enormous but bimodal, and dirty.** ~14k (CDP) / ~28k (PayAI)
  resources, but a spot check shows most are toy endpoints (coin flips, riddles,
  fortunes, meme generators). Real commercial vendors exist — Bitrefill, Apify,
  OneSource — just not many *per category*. This matches prior research flagging
  a large share of x402 transaction volume as gamed / self-dealing rather than
  organic demand. The feed also mixes CAIP-2 (`eip155:8453`) with bare `"base"`
  strings and carries live `x402Version: 1` entries. Vendor evaluation needs
  quality heuristics and must tolerate both wire versions and both network-id
  formats.

  **Consequence for the product thesis.** "Provable best-price across N vendors"
  is **not currently demonstrable**, because in most categories N ≈ 1 — there is
  no competing set to be best within. The one metric (human touchpoints per
  basket) and the 10x claim that rests on it are **unaffected**: they come from
  the durable mandate + non-custodial Spend Permission + no-gas-needed
  properties, not from price comparison. Action: **drop best-price capture from
  the pitch** until the market has real per-category depth; keep it as a latent
  capability to switch on later, and reconsider its place in the metrics table
  in `CLAUDE.md` (currently "track from week 5"). The demo basket must be
  assembled from the specific real vendors that exist (e.g. a gift card via
  Bitrefill + a data pull via OneSource + compute via Apify), not from a
  hypothetical dense marketplace.

- **The two catalogs disagree substantially — discovery is fragmented.** Same
  day, same query: CDP returned `pagination.total` = **14,324**, PayAI
  **27,855**. These are different facilitators maintaining different indexes;
  neither is authoritative or complete. An agent that wants to see the whole
  market must query **multiple** discovery services and merge/dedupe the
  results — treating any single facilitator's catalog as "the market" will miss
  a large fraction of it. Build the discovery layer as a fan-out over a
  configurable list of facilitators from the start.

- **Real third-party endpoints are Base mainnet, exclusively.** All 13 live
  endpoints in the probe were `eip155:8453`. Zero third-party endpoints on Base
  Sepolia. So the two demo tracks are genuinely different environments: the
  synthetic Base Sepolia basket (self-hosted, free) and a real Base **mainnet**
  basket (Bazaar vendors, costs real USDC). Not interchangeable — decide per
  demo which one is being shown.

---

## 9. Decision

> **Proceed to week 2. Verdict GREEN pending one mainnet settlement.** A real
> multi-vendor procurement basket on Base is viable — the vendor supply is not
> the constraint it was assumed to be.

**Both halves of the gate are now answered:**
- *Does settlement work?* Yes — proven on chain (section 4, Base Sepolia).
- *Do real endpoints exist?* Yes — 13 live-verified in a 16-endpoint spot check,
  from 275 distinct Base operator domains in a 600-item sample, from a public
  14k/28k catalog (section 2).

**One open item to fully close GREEN:** run one real payment against a live
Bazaar endpoint on Base **mainnet**, via a mainnet facilitator (CDP or PayAI).
Pick a ~$0.001 endpoint; fund the buyer wallet with ~$1–2 of real USDC on Base
mainnet; reuse `probe_02_settle.py` unchanged (it takes a URL and reads the
network from the 402). Record the tx in a short addendum to section 4. This is
the only remaining spend and is well inside the $10 ceiling.

**Then close week 1:**
1. Paste the verbatim decoded `payment-required` object from the probe_02 run
   into section 3, replacing the reconstruction.
2. Archive `probe/` to `docs/archive/probe/` per `probe/README.md` (this file
   survives).

**Carried into the main build:**
- Discovery = `GET /discovery/resources`, but **fan out over a configurable list
  of facilitators** (CDP + PayAI at minimum) and merge/dedupe — the catalogs
  disagree by ~2x, no single one is the market. Not a component to invent, but
  more than a one-liner.
- Vendor evaluation must score quality (the catalog is mostly toys), treat
  `accepts` as a menu, and tolerate both `x402Version` 1 and 2 and both
  `eip155:8453` and bare `"base"` network ids.
- **Best-price / cheapest-vendor is not a demo feature for now** — N ≈ 1 per
  category. Build the basket from named real vendors.
- Two separate demo environments: synthetic Base Sepolia (free, self-hosted)
  and real Base mainnet (Bazaar vendors, real USDC). Choose per demo.
- The agent gets its own `x402[requests,evm]` install from the local clone.
- Buyer wallet funded in USDC only, no ETH — the facilitator pays gas.
- Re-sign authorizations inside the 300s window; never queue a signed payment.
