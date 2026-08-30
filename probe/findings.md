# Week 1 Gate — Findings

Fill this in as you go. This file is the only thing in `probe/` that survives week 1.
Commit it even if the verdict is RED, especially if the verdict is RED.

**Date started:**
**Date concluded:**

---

## 1. Verdict

> GREEN / AMBER / RED — delete two.

**Reasoning (two or three sentences):**

---

## 2. Endpoint inventory

| # | Endpoint | What it sells | Price | Asset | Network | Live? | Source of URL |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | | |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |
| 5 | | | | | | | |

Count of real, live, independently-operated endpoints on Base: **___**

Network split — how many are Base mainnet only vs. available on Base Sepolia: **___**

---

## 3. Raw 402 response

Paste the actual payment-requirements object from `probe_01`. Do not summarise it.

```json

```

Observations on the wire format:

-
-

---

## 4. Settlement proof

| Field | Value |
|---|---|
| Transaction hash | |
| Network | |
| Facilitator used | |
| Block explorer link | |
| Verified independently on explorer? | yes / no |

A 200 response is not proof of settlement. Confirm the transaction on chain.

---

## 5. Language boundary decision

Does the Python x402 SDK support Base / Base Sepolia for the `exact` scheme?

> yes / no

**Evidence (link and quote):**

**Decision:** all-Python  /  Python agent + TypeScript payments sidecar

**Rationale:**

---

## 6. Verified constants

Every value here must have a primary source. These carry forward into the main
codebase and each one gets a test that reads it on chain.

| Constant | Value | Source URL | Verified on chain? |
|---|---|---|---|
| Facilitator URL | | | n/a |
| USDC (Base mainnet) | | | |
| USDC (Base Sepolia) | | | |
| SpendPermissionManager | | | |
| Base mainnet chain id | 8453 | | |
| Base Sepolia chain id | 84532 | | |

---

## 7. Cost

| Item | Amount |
|---|---|
| Testnet funds used | |
| Mainnet USDC spent | |
| Days elapsed | |

Ceiling was $10 and five working days. Over it? Say so.

---

## 8. Things that contradicted the plan

The most valuable section. What did you find that the thirteen-week plan assumes
wrongly? Write it down now, while it is still surprising.

-
-
-

---

## 9. Decision

> Proceed to week 2 / Proceed with hybrid basket / Stop and reconsider

**Next action:**
