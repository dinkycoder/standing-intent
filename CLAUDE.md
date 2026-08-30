# CLAUDE.md

Instructions for Claude Code working in this repository. Read this before writing any code.

---

## What this project is

**Standing Intent** — an autonomous procurement agent for digital goods and APIs, settling
payments in USDC on Base via the x402 protocol, under a user-signed Base Spend Permission.

The user signs **one** capped, revocable spending authorization up front. The agent then
discovers vendors, evaluates offers, and completes purchases with **zero further human
contact** until the budget is exhausted or an out-of-policy condition forces escalation.

This is not a shopping chatbot. It is a policy-bearing agent that executes a durable mandate.

---

## The one metric

**Human touchpoints per completed basket.**

Every design decision is judged against it. A feature that improves task success but adds a
confirmation prompt is a regression. If you are unsure whether to add a prompt, don't — add an
escalation *rule* to the policy layer instead, and let the harness measure how often it fires.

Secondary metrics, all tracked by the eval harness from day one:

| Metric | Definition | Target |
|---|---|---|
| Touchpoints / basket | Human interactions to complete a full mandate | 1 (the signature), then 0 |
| Budget adherence | Spend beyond the Spend Permission cap | 0 violations, always |
| pass^1 | Single-attempt task success | Report honestly |
| pass^k | k-attempt consistency (k=4, k=8) | Report honestly; this is the real number |
| Best-price capture | Cheapest in-policy vendor chosen | Track from week 5 |
| Cost / completed tx | LLM tokens + gas + fees | Track from week 3 |

`pass^1` flatters the agent. `pass^k` is what a reviewer will ask about. Report both, always.

---

## Hard rules

### 1. Never take custody of user funds

User funds live in the **user's own** Base Account. The agent spends via a capped
Spend Permission. This project never holds, pools, escrows, routes, or takes a cut inside the
payment flow.

**This is a legal boundary, not a style preference.** A non-custodial architecture is what keeps
this outside FinCEN money services business registration and Florida money transmitter
licensing. Breaking it converts a student project into a licensing problem.

If a proposed design would have the service:

- hold a private key that can move user funds unilaterally, or
- pool funds from multiple users in one wallet, or
- receive funds and forward them, or
- deduct a fee from inside the payment transaction

then **stop and flag it in your response instead of implementing it.** Say plainly which of the
four it trips. Do not "simplify" the flow through a service-owned wallet. That simplification is
the exact failure mode this rule exists to prevent.

Monetization, when it exists, is billed **outside** the payment flow (subscription per active
mandate). Never inside it.

### 2. No unverified on-chain constants

Every contract address, chain ID, token address, and facilitator URL must be:

1. Sourced from primary documentation (Coinbase/Base/x402 Foundation docs, or the deployed
   contract itself), with the source URL recorded in a comment, **and**
2. Pinned in a test that reads it on-chain and asserts something only the real contract would
   return.

**No constant enters this codebase from prose, memory, or a model's suggestion.** A plausible
but wrong address that passes every test is worse than a crash, because it fails silently and
you find out in the demo.

If you cannot verify an address, write `# UNVERIFIED — do not use` next to it and say so.

### 3. Evals before behaviour

No agent capability is implemented before a failing eval task exists for it. The harness is the
specification. This is TDD applied to a non-deterministic system, so the tests are statistical:
run n trials, assert a pass rate, and record the seed and model version.

### 4. Tests must catch wrong-but-plausible output

A test that only checks "the function returned a number" is not a test. Assert against a value
that would be wrong if the logic were subtly broken. Prefer terminal-state grading (did the
right thing actually get bought, under budget) over checking that a function was called.

---

## Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | The graded artifact must be Python |
| API | Flask | Coursework stack |
| DB | PostgreSQL | Mandates, purchases, vendor history |
| Agent | LangChain | Planner / executor split |
| Vector store | TBD (pgvector preferred) | Keeps infra to one database |
| Payments | `x402` Python SDK | See "SDK caution" below |
| Wallet | Coinbase CDP / AgentKit | Server Wallet v2 or Smart Account |
| Chain | Base Sepolia first, Base mainnet for the real-endpoint demo | |
| Tests | pytest | |
| Tracing | Langfuse (self-hosted) | Framework-neutral, OTel, data stays local |
| CI | GitHub Actions | Evals gate the build from week 2 |
| Container | Docker | |
| Deploy | AWS | Coursework specialization |

### SDK caution

The `x402` name is polluted on PyPI and GitHub. There are TRON forks, Solana-only ports, and
unrelated commercial products with near-identical names and READMEs.

- **Canonical repo:** `x402-foundation/x402` (formerly `coinbase/x402`). Python lives in
  `python/x402`.
- **Install with extras:** `x402[flask]`, `x402[requests]` or `x402[httpx]`, `x402[evm]`.
- **Pin exact versions** in `requirements.txt` and record the source URL in the README.
- **Verify before relying on it:** the docs state TypeScript supports every network while Go and
  Python support a *subset*. Confirm Base and Base Sepolia are covered for the `exact` scheme.
  If they are not, the fallback is a thin TypeScript payments sidecar behind a local HTTP call —
  the Python agent stays the graded artifact.

---

## Environment

Windows / PowerShell. When generating shell commands, use PowerShell forms, not bash:

- `Set-Item -Path Env:NAME -Value "value"`, not `export NAME=value`
- `Remove-Item -Recurse -Force path`, not `rm -rf path`
- `$env:VAR`, not `$VAR`
- Prefer `python -m pip` over bare `pip`

MCP servers launched via `npx` need the `cmd /c` wrapper in the client config:

```json
{ "command": "cmd", "args": ["/c", "npx", "-y", "<package>"] }
```

`uvx`-based servers do not need the wrapper.

---

## Secrets

- Never commit a private key, API key, or `.env` file.
- Development wallets hold only what a demo needs. Never a personal wallet.
- Keys come from environment variables. If you find a key literal in code, remove it and say so.

---

## Working style

- **Push back.** If an instruction is wrong, or a plan has a flaw, say so before implementing.
- **Say "I don't know."** Do not guess at an API signature, a contract address, or a protocol
  behaviour. Look it up or flag it.
- **Concise over comprehensive.** Do not generate twenty files because a plan lists twenty
  components. Build the smallest thing that makes the next eval pass.
- **Verify repo state against `git log`,** not against a summary of what was supposedly done.
- **Explain chain mechanics rather than assuming them.** The author's background is
  econometrics, not blockchain. Spell out what a signature, a nonce, or a settlement actually
  does when it matters.

## What not to do

- Do not write the agent planning loop before the eval harness exists.
- Do not build any UI before the agent reliably completes a basket headlessly.
- Do not add a confirmation prompt to fix a reliability problem.
- Do not route funds through a service wallet.
- Do not invent an address.

---

## Roadmap position

See `docs/PMF_AND_BUILD_PLAN.md` for the full thirteen-week plan and the reasoning behind the
vertical choice.

**Current phase: Week 1 — the endpoint-availability gate.** See `docs/WEEK1_GATE.md`.
Nothing in the main build starts until that gate reports a verdict.
