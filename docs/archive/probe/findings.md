# Week 1 Gate — Findings

Fill this in as you go. This file is the only thing in `probe/` that survives week 1.
Commit it even if the verdict is RED, especially if the verdict is RED.

**Date started:** 2026-08-30
**Date concluded:** 2026-09-07

Status (2026-09-07): **verdict GREEN — all clauses closed.**
- **Settlement proven on testnet** — probe_02, tx
  `0x1b1b78e2fcba693ace023bb8af2ae19277f597d6f82b6a2adcc6bd6765dd309d`: a
  self-hosted Flask seller returned a real 402, the buyer signed, the facilitator
  settled on chain (Base Sepolia), and the paid resource came back.
- **Settlement proven on mainnet** — probe_02 against a real third-party Bazaar
  endpoint (`x402.ottoai.services/crypto-news`), tx
  `0x44cb0f1e7bd5794e1d57ff10974fa1e544a43bd90796922e14d6a7e1cd43fcc3`: live 402,
  buyer signed, facilitator settled on Base **mainnet** (block 50997392), $0.001
  USDC buyer → seller, paid content returned. On-chain verified. See section 4.
- **Vendor supply proven** — probe_03: the public x402 Bazaar discovery API
  (Coinbase CDP / PayAI, no auth) lists 14k–28k live resources, mostly on Base;
  13 of 16 independent endpoints spot-checked returned a live 402, all Base
  mainnet USDC. Re-checked 2026-09-07: ottoai, apitoll, Bitrefill all still live.
- **Open:** nothing. Both halves of the gate are answered on both networks.

Desk research was done against the x402-foundation reference clone
(`C:\Users\dinky\projects\x402-reference`, repo commit `e398a9e`, 2026-08-28) and
`docs.x402.org`.

---

## 1. Verdict

> **GREEN** — a real multi-vendor basket is possible on Base. Settlement is
> confirmed on chain on both Base Sepolia and Base mainnet. No open items.

**Reasoning:**
1. **Settlement works and is confirmed on chain, on both networks** (section 4):
   Base Sepolia block 46175913 (self-hosted seller) and Base **mainnet** block
   50997392 (real third-party endpoint `x402.ottoai.services`) — both Success,
   USDC buyer → seller, gas paid by the facilitator relayer. RED is ruled out.
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

**Caveat resolved (2026-09-07).** The "settlement confirmed" clause was originally
closed only on testnet. It is now closed on Base **mainnet** too: one real payment
of $0.001 USDC against `x402.ottoai.services/crypto-news`, settled by that
endpoint's own facilitator (relayer `0xe748…0fae`), on-chain verified in section
4. Total real spend: $0.001 (plus ~$2 of USDC funded into the throwaway buyer
wallet, of which 1.999 remains). Well inside the $10 gate ceiling.

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

The 402 status body carries a JSON copy of the terms; the authoritative copy is
the base64-encoded `payment-required` **header**. Below is the verbatim decoded
header from the **mainnet** probe_02 run against `x402.ottoai.services/crypto-news`
(2026-09-07, `keys sorted` exactly as `probe_02_settle.py` printed it). The large
`extensions` block is vendor-specific metadata (pre-signed offers, sign-in-with-x,
builder codes, Bazaar I/O schema) — its payment-bearing values are kept verbatim;
the embedded JSON-Schema `schema` sub-objects are marked `<elided>`.

```json
{
  "accepts": [
    {
      "amount": "1000",
      "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
      "extra": { "name": "USD Coin", "version": "2" },
      "maxTimeoutSeconds": 300,
      "network": "eip155:8453",
      "payTo": "0x0E84dDEdAaE6A779c462C22a59F301EC31B6b808",
      "scheme": "exact"
    },
    {
      "amount": "1000",
      "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
      "extra": { "assetTransferMethod": "permit2", "name": "USD Coin", "version": "2" },
      "maxTimeoutSeconds": 300,
      "network": "eip155:8453",
      "payTo": "0x0E84dDEdAaE6A779c462C22a59F301EC31B6b808",
      "scheme": "exact"
    },
    {
      "amount": "1000",
      "asset": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
      "extra": { "feePayer": "GVJJ7rdGiXr5xaYbRwRbjfaJL7fmwRygFi1H6aGqDveb" },
      "maxTimeoutSeconds": 300,
      "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
      "payTo": "6XcSfqJHr9vNW2vbiRaMqUYVm7shDgLepca54wUTDPN5",
      "scheme": "exact"
    }
  ],
  "error": "Payment required",
  "extensions": {
    "bazaar": {
      "info": {
        "input": { "method": "GET", "queryParams": {}, "type": "http" },
        "output": { "type": "json", "example": { "status": "success", "data": { "report": "Latest crypto news...", "headlines": [ { "rank": 1, "title": "Bitcoin ETFs notch best month of 2026 as BTC gains 25% in August", "whyItMatters": "ETF flows are the strongest near-term driver of institutional participation.", "url": "https://cointelegraph.com/markets/bitcoin-etf-best-month-2026-btc-up-25-august", "publishedAt": "2026-09-02T07:59:43.000Z", "source": "Cointelegraph", "match": "exact" } ] }, "meta": { "generatedAt": "2026-08-10T12:00:00.000Z", "stalenessSec": 1739, "degraded": false, "sourceHealth": { "crypto-news-cache": "ok" }, "dataAsOf": "2026-08-10T08:00:00.000Z", "freshness": "fresh" } } }
      },
      "schema": "<elided JSON Schema>"
    },
    "builder-code": { "info": { "a": "bc_hc2dhq09" }, "schema": "<elided JSON Schema>" },
    "offer-receipt": {
      "info": {
        "offers": [
          { "format": "eip712", "acceptIndex": 0, "payload": { "version": 1, "resourceUrl": "https://x402.ottoai.services/crypto-news", "scheme": "exact", "network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "payTo": "0x0E84dDEdAaE6A779c462C22a59F301EC31B6b808", "amount": "1000", "validUntil": 1788784425 }, "signature": "0xe652adb611a55dbeb5a9a012a912b12361df3aa7ddabecf5bf27496f68d2b27522d32153bcc00477196d096c135ea72264b3d8ba2494d3ae2add042580a4fef41c" },
          { "format": "eip712", "acceptIndex": 1, "payload": { "version": 1, "resourceUrl": "https://x402.ottoai.services/crypto-news", "scheme": "exact", "network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "payTo": "0x0E84dDEdAaE6A779c462C22a59F301EC31B6b808", "amount": "1000", "validUntil": 1788784425 }, "signature": "0xe652adb611a55dbeb5a9a012a912b12361df3aa7ddabecf5bf27496f68d2b27522d32153bcc00477196d096c135ea72264b3d8ba2494d3ae2add042580a4fef41c" },
          { "format": "eip712", "acceptIndex": 2, "payload": { "version": 1, "resourceUrl": "https://x402.ottoai.services/crypto-news", "scheme": "exact", "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "asset": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "payTo": "6XcSfqJHr9vNW2vbiRaMqUYVm7shDgLepca54wUTDPN5", "amount": "1000", "validUntil": 1788784425 }, "signature": "0x271501f67832bf65120c2f0a22dcfc30f0813557811910c662f32177c1b1fd886b257c05138885c1f62a37540eaee1b23c101f10f5895b4d3ac45f88dfa45c0c1b" }
        ]
      },
      "schema": "<elided JSON Schema>"
    },
    "otto-content-receipt": {},
    "sign-in-with-x": {
      "info": { "domain": "x402.ottoai.services", "uri": "https://x402.ottoai.services/crypto-news", "version": "1", "nonce": "6b6afb34eb592b0a0acbcb5cc9fe043f", "issuedAt": "2026-09-07T12:28:45.823Z", "statement": "Sign in to access Otto AI market intelligence", "resources": ["https://x402.ottoai.services/crypto-news"] },
      "schema": "<elided JSON Schema>",
      "supportedChains": [ { "chainId": "eip155:8453", "type": "eip191" }, { "chainId": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp", "type": "ed25519" } ]
    }
  },
  "resource": {
    "url": "https://x402.ottoai.services/crypto-news",
    "description": "Importance-ranked crypto headlines with per-article source links and publish times, plus a sentiment-scored market brief. Regenerated hourly; meta carries the snapshot's age and a fresh/stale verdict.",
    "iconUrl": "https://x402.ottoai.services/assets/otto-icon.png",
    "mimeType": "application/json",
    "serviceName": "Otto AI",
    "tags": ["crypto news", "market news", "sentiment analysis", "breaking headlines"]
  },
  "x402Version": 2
}
```

The original testnet reconstruction (self-hosted `localhost:4021/weather`, Base
Sepolia + Solana devnet, `amount "10000"` = $0.01) is superseded by this real
capture. The wire shape is identical — same `accepts` menu structure, atomic-unit
string `amount`, `maxTimeoutSeconds` 300, CAIP-2 `network`, v2 header names — which
is exactly what the reconstruction predicted.

Observations on the wire format:

- **The 402 body is not always empty.** The testnet Flask seller sent `{}` and put
  everything in the `payment-required` header. ottoai sends a full JSON copy in the
  body *and* the header, and its own `hint` says the header "remains the x402 v2
  protocol contract." So: read the header, always; treat the body as a
  convenience copy that may or may not be there. The `x402_requests` session
  wrapper reads the header; a naive client that only inspects the body will
  silently fail against sellers like the Flask one.
- **`accepts` is a LIST, not a single object.** The seller advertises a menu and
  the **buyer chooses**. ottoai's menu: plain `exact` on Base mainnet USDC, the
  *same* on Base mainnet but `extra.assetTransferMethod: "permit2"`, and `exact`
  on Solana. The SDK's EVM registration picked `accepts[0]` (plain
  `transferWithAuthorization`, no Permit2 allowance needed). Vendor evaluation in
  the main build has to treat every 402 as "one or more offers," not "the price,"
  and know which transfer methods it can satisfy.
- **`amount` is atomic units.** `"1000"` = $0.001 because USDC has 6 decimals
  (1000 / 10^6 = 0.001). It is a decimal string, not a number. Never divide by
  10^18 out of Ethereum habit — USDC is 10^6.
- **`maxTimeoutSeconds` is 300.** The signed authorization is only valid for five
  minutes. An agent that signs, then queues, then submits late will have its
  payment rejected as expired. Any planner that batches or delays payment steps
  needs to re-sign inside that window.
- **`network` is CAIP-2** (`eip155:8453` mainnet, `eip155:84532` Sepolia), not a
  friendly name like `base`.
- **Some sellers pre-sign offers.** ottoai's `extensions.offer-receipt` carries
  EIP-712 signatures over each `accepts` entry (`validUntil` ~70 min out) so a
  buyer can pay without a second round trip. The standard SDK path ignores this
  and does the normal 402 → sign → retry; it settled fine. Optional optimisation,
  not a requirement.
- v2 header names: `payment-required` (on the 402), `payment-signature` (on the
  retry), `payment-response` (on the settled 200). No `X-PAYMENT` — that is v1.

---

## 4. Settlement proof

### 4a. Base Sepolia (testnet, self-hosted seller) — 2026-08-30

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

### 4b. Base mainnet (real third-party Bazaar endpoint) — 2026-09-07

Closes the last GREEN clause. `probe_02_settle.py` run unmodified against
`https://x402.ottoai.services/crypto-news` (Otto AI — importance-ranked crypto
news, a real commercial operator with docs, contact, and a money-back guarantee).
Same buyer wallet as 4a; funded with 2.0 USDC on Base mainnet beforehand (no ETH).

| Field | Value |
|---|---|
| Transaction hash | `0x44cb0f1e7bd5794e1d57ff10974fa1e544a43bd90796922e14d6a7e1cd43fcc3` |
| Network | `eip155:8453` (Base **mainnet**) |
| Payer (buyer) | `0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0` |
| Pay-to (seller) | `0x0E84dDEdAaE6A779c462C22a59F301EC31B6b808` |
| Amount | `1000` atomic = **$0.001 USDC** (6 decimals) |
| `accepts` entry paid | `accepts[0]` — `exact` / `eip155:8453` / plain `transferWithAuthorization` (not the Permit2 variant) |
| Facilitator used | seller's config; relayer address `0xe74817f4cdc15844314812b2271276e64e890fae` (not one of ours, and different from the testnet relayer) |
| `payment-response` | `{"success": true, "errorReason": null, "payer": "0xA85F…2CB0", "transaction": "0x44cb…fcc3", "network": "eip155:8453"}` |
| Resource returned after payment | `{"status":"success","data":{"report":"...MARKET BRIEF... Bull/Bear Score: 45...","headlines":[...]}}` — real content, 8KB |
| Block explorer link | https://basescan.org/tx/0x44cb0f1e7bd5794e1d57ff10974fa1e544a43bd90796922e14d6a7e1cd43fcc3 |
| Verified independently on chain? | **YES** — `eth_getTransactionReceipt` via public Base RPC, 2026-09-07 |
| Block | 50997392 (Base mainnet), 2026-09-07 12:28:51 UTC |
| Status | `0x1` — Success |
| From (tx sender) | `0xe748…0fae` — the facilitator's relayer; **neither buyer nor seller** |
| Interacted with | USDC contract `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` (Base mainnet USDC) |
| ERC-20 transfer in the tx | `0xa85f…2cb0` → `0x0e84…b808`, exactly `1000` atomic (0.001 USDC) |
| ETH value moved | 0 |
| Gas | 86,486 gas × ~5 gwei ≈ `0.00000043` ETH — **paid by the relayer** `0xe748…0fae`, not the buyer |
| Buyer wallet after | **1.999000 USDC** (was 2.000000; delta = exactly the price), **0 wei ETH**, **nonce 0** |

The buyer wallet has still never sent a transaction (nonce 0) and still holds no
ETH — on mainnet, same as testnet. It signed an off-chain EIP-3009
authorization; relayer `0xe748…0fae` submitted `transferWithAuthorization` to the
USDC contract and paid the gas. The `Transfer(from=buyer, to=seller, 1000)` log
in that tx is the settlement.

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
| Mainnet facilitator (option A) | `https://api.cdp.coinbase.com/platform/v2/x402` | docs.x402.org/getting-started/quickstart-for-sellers | discovery sub-path `GET /discovery/resources` returned `200` (no auth) on 2026-08-30; **our** buyer has not called this facilitator's settle/verify directly |
| Mainnet facilitator (option B) | `https://facilitator.payai.network` | docs.x402.org/getting-started/quickstart-for-sellers | discovery sub-path `GET /discovery/resources` returned `200` (no auth) on 2026-08-30; **our** buyer has not called this facilitator's settle/verify directly |
| Mainnet facilitator (exercised via seller) | relayer `0xe74817f4cdc15844314812b2271276e64e890fae` — whichever facilitator `x402.ottoai.services` is configured with (not disclosed in the 402) | §4b settlement | **YES — a real mainnet settle happened through it** 2026-09-07: `transferWithAuthorization` on mainnet USDC, `success: true`, block 50997392. In x402 v2 the buyer never picks the facilitator, so this is the one path we can attest works end to end. |
| USDC (Base Sepolia) | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` | Circle official docs: developers.circle.com/stablecoins/usdc-contract-addresses (Testnet section, Base Sepolia) | **YES — read on chain 2026-08-30** via `https://sepolia.base.org` (chain id 84532): `symbol()` = `"USDC"`, `decimals()` = `6`; buyer `balanceOf` returned exactly the fauceted 20000000 |
| USDC (Base mainnet) | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | observed as the `asset` in the live 402 of ~13 independent Bazaar endpoints (2026-08-30); Circle docs mainnet section not re-fetched — do so before pinning | **YES — read on chain 2026-08-30** via `https://mainnet.base.org` (chain id 8453): `name()` = `"USD Coin"`, `symbol()` = `"USDC"`, `decimals()` = `6`. **Also confirmed by settlement 2026-09-07:** the mainnet settlement tx (§4b) `to`-address was this contract; its `Transfer` log moved exactly `1000` atomic buyer → seller. |
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
| Real money spent | **$0.001** — one mainnet settlement (§4b) |
| Real USDC funded into buyer wallet | ~$2.00 on Base mainnet (throwaway wallet); **1.999 remains** after the settlement |
| Real ETH bought | **$0** — buyer needs no gas; the facilitator relayer pays it |
| Testnet funds used | 0.01 Base Sepolia USDC (of 20 fauceted) + 0 ETH; facilitator paid the ~6.3e-7 ETH gas |
| Elapsed time | 2 days of active work — 2026-08-30 (desk research, wallets, seller setup, testnet settlement, Bazaar survey) and 2026-09-07 (endpoint re-check, mainnet funding + settlement + on-chain verification). |

Ceiling was $10 and five working days. Actual: **$0.001 spent** ($2 funded, most
of it recoverable) and 2 days. Well under both. GREEN is fully closed — no
remaining spend.

---

## 8. Things that contradicted the plan

The most valuable section. What did you find that the thirteen-week plan assumes
wrongly? Write it down now, while it is still surprising.

- **No public *tutorial* endpoint, but a huge public *marketplace*.** Every
  quickstart and Python example targets `http://localhost:4021`, so the *first*
  402 (probe_02, 2026-08-30) came from a self-hosted seller. But probe_03 then
  found the opposite of scarcity: the x402 Bazaar discovery API is public and
  unauthenticated and lists **14k–28k** live resources, the overwhelming majority
  on Base — and on 2026-09-07 probe_02 settled unmodified against one of them
  (`x402.ottoai.services`) on mainnet, first try. The earlier working assumption
  that this would land at AMBER "by construction" was wrong — see section 1,
  now GREEN with both networks proven.
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

> **Proceed to week 2. Verdict GREEN — no open items.** A real multi-vendor
> procurement basket on Base is viable, and settlement is proven end to end on
> both Base Sepolia and Base mainnet. The vendor supply is not the constraint it
> was assumed to be.

**Both halves of the gate are answered, on both networks:**
- *Does settlement work?* Yes — proven on chain twice: Base Sepolia against a
  self-hosted seller (§4a) and Base **mainnet** against a real third-party Bazaar
  endpoint (§4b, tx `0x44cb…fcc3`, $0.001 USDC, on-chain verified).
- *Do real endpoints exist?* Yes — 13 live-verified in a 16-endpoint spot check,
  from 275 distinct Base operator domains in a 600-item sample, from a public
  14k/28k catalog (section 2); three re-verified live 2026-09-07.

**Remaining close-out:**
1. ~~Paste the verbatim decoded `payment-required` object into section 3~~ — done
   (2026-09-07, the mainnet ottoai capture).
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
- **`accepts` entries can carry `extra.assetTransferMethod: "permit2"`** — a
  different signing path (Permit2 allowance) than plain EIP-3009
  `transferWithAuthorization`. ottoai advertised both; the SDK picked the plain
  one. The agent must be able to tell which entries it can actually satisfy and
  skip the rest, not just pick `accepts[0]`.
- **Some sellers send the terms in the body too, and some pre-sign offers**
  (`extensions.offer-receipt`). Neither changes the flow — read the header, do
  the normal 402 → sign → retry — but the parser must not choke on a fat
  `extensions` object full of vendor-specific sub-schemas.
- **Best-price / cheapest-vendor is not a demo feature for now** — N ≈ 1 per
  category. Build the basket from named real vendors.
- Two separate demo environments: synthetic Base Sepolia (free, self-hosted)
  and real Base mainnet (Bazaar vendors, real USDC). Choose per demo.
- The agent gets its own `x402[requests,evm]` install from the local clone.
- Buyer wallet funded in USDC only, no ETH — the facilitator pays gas. **Proven
  on mainnet 2026-09-07:** buyer nonce still 0, ETH balance still 0 after a
  successful mainnet settlement.
- Re-sign authorizations inside the 300s window; never queue a signed payment.
- The mainnet buyer wallet `0xA85F…2CB0` holds ~1.999 real USDC. It is a
  throwaway (key in `probe/.env`, git-ignored). Sweep or reuse it deliberately;
  do not let it accrete funds.
