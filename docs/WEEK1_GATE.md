# Week 1 Gate — Endpoint Availability

## Why this exists

The riskiest assumption in the whole plan is:

> **Enough real x402-payable endpoints exist to compose a non-trivial multi-vendor
> procurement basket on Base.**

If that is false, the agent has nothing to procure and the project is a simulation of a market
that does not exist. This gate is designed to find that out in days, not months, and to cost
almost nothing if the answer is no.

**Nothing in the main build starts until this gate returns a verdict.**

## The three probes

Run in order. Each is disposable. See `probe/README.md`.

| Probe | Question | Pass condition |
|---|---|---|
| `probe_01_observe_402.py` | What does a real 402 response actually look like? | You have read the raw payment-requirements object with your own eyes |
| `probe_02_settle.py` | Can a payment be signed and settled end to end? | One successful settlement on Base Sepolia, tx hash recorded |
| `probe_03_discover.py` | How many usable endpoints exist? | Filled-in table in `probe/findings.md` |

## Do probe 01 by hand first

Before letting Claude Code generate anything, `curl` one endpoint yourself and read the 402
body. You will be debugging that object in week 8. If your only mental model of it came from
generated code, you will be slow.

PowerShell:

```powershell
curl.exe -i https://<endpoint>
```

Use `curl.exe`, not `curl` — in PowerShell, bare `curl` is an alias for `Invoke-WebRequest`,
which will not show you the raw response the same way.

## Verdict criteria

Record the verdict in `probe/findings.md` and commit it. There are three outcomes and **all
three are acceptable** — the point is to know which one you are in.

### GREEN — proceed as planned
Five or more real, live, independently-operated x402 endpoints, priced, on Base, that a basket
could plausibly draw from. Settlement confirmed.

### AMBER — proceed with a hybrid basket
Fewer than five real endpoints, but settlement works. Compose the basket from the real
endpoints that exist plus self-hosted x402 endpoints (Flask + `x402[flask]` middleware) that
stand in for absent vendor categories.

This is still a valid artifact. Say so explicitly in the README and the capstone writeup —
a synthetic vendor environment honestly labelled is fine; one passed off as real is not.

### RED — settlement does not work
Cannot complete a signed settlement against any facilitator on Base Sepolia or Base mainnet
after a week. This is the kill condition. Stop and reconsider before writing agent code.

## Expected finding (predicted, not assumed)

The likely outcome is AMBER-leaning-GREEN with a wrinkle: the public facilitator at
`https://x402.org/facilitator` supports Base Sepolia, but most *real* endpoints in the wild are
Base **mainnet** only. So the honest result is probably:

- testnet path works against endpoints you host yourself
- real-endpoint basket needs Base mainnet and roughly $5 of USDC

That is fine, and arguably a better demo. **Decide it deliberately in week 1 rather than
discovering it in week 9.**

## Cost ceiling

This gate should cost under $10 and under five working days. If it is costing more than that,
the answer is already AMBER or RED — write it up and move on.

## Deliverable

A committed `probe/findings.md` with:

1. The filled endpoint table
2. At least one settlement transaction hash (and which network)
3. The verdict: GREEN / AMBER / RED
4. The language-boundary decision (see below)
5. Anything that contradicted the plan

## Second decision due this week: the language boundary

The official x402 docs state that TypeScript supports every network while Go and Python support
a *subset*. Confirm on day one whether the Python SDK covers Base and Base Sepolia for the
`exact` scheme.

- **If yes:** all-Python. Simplest, keeps the graded artifact in one language.
- **If no:** Python agent plus a thin TypeScript payments sidecar exposed over local HTTP. The
  agent, the models, and the eval harness stay Python, so the graded artifact is unaffected.

Record the decision and the evidence in `findings.md`. Changing this in week 5 is expensive;
changing it in week 1 is free.
