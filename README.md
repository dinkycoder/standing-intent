# Standing Intent

An autonomous procurement agent for digital goods and APIs, settling in USDC on Base via
the x402 protocol, operating under a single user-signed Spend Permission.

The user signs **one** capped, revocable authorization. The agent then discovers vendors,
evaluates offers, and completes purchases with **zero further human contact** until the budget
is exhausted or an out-of-policy condition forces escalation.

**Current phase: Week 4 — the Base Spend Permission.** Weeks 1–3 are complete and on `main`:

- **Week 1** — the endpoint-availability gate closed GREEN (`docs/archive/probe/findings.md`).
- **Week 2** — the eval harness lives in `evals/`: task specs, terminal-state grading, `pass^k`
  metrics, CI gating. Design in `docs/superpowers/specs/2026-09-02-eval-harness-design.md`.
- **Week 3** — the x402 payments spine lives in `payments/`: offer inspection, payment
  construction, on-chain settlement verification, a local test seller. The harness now grades
  agents against **verified on-chain settlements**, not their self-reports. One real Base
  mainnet settlement is recorded in `docs/week3-mainnet-gate.md`.

Week 4 adds the user-signed Spend Permission — one capped, revocable authorization the agent
spends against with no further human contact.

---

## Why this and not something else

Consumer agentic checkout is closed. Card networks and OpenAI/Stripe own the rails, and the
incumbents' own numbers show consumers do not yet want in-chat autonomous buying. Ticketing is
barred by the BOTS Act. Restaurant reservations are barred in New York and closing elsewhere.

Machine-to-machine is where the demand actually is: agents paying for APIs, data, and compute,
in amounts too small for card rails to serve at all.

Full reasoning, competitive analysis, legal screen, and the thirteen-week plan:
[`docs/PMF_AND_BUILD_PLAN.md`](docs/PMF_AND_BUILD_PLAN.md).

## The claim

Today's best purchasing agents sit at **Level 2 autonomy**: every payment needs a human
approval, because card rails cannot delegate spend without per-transaction authentication.

Base Spend Permissions collapse that to one signature up front and zero afterwards across an
entire budget. The target is a **≥10:1 reduction in human touchpoints per completed
transaction**, with a hard on-chain cap guaranteeing zero budget violations.

That claim is not yet proven. It gets tested in week 12 by a head-to-head experiment, and the
result goes in this README whichever way it lands.

## Repository layout

```
CLAUDE.md                    constraints governing all work here — read first
docs/
  PMF_AND_BUILD_PLAN.md      research report and 13-week plan
  WEEK1_GATE.md              the week-1 gate: pass/fail criteria (closed GREEN)
  week3-mainnet-gate.md      the first real mainnet settlement, recorded
  archive/probe/             disposable week-1 scripts + findings.md (the gate verdict)
  superpowers/               design specs and build plans, per phase
evals/                       eval harness — task specs, terminal-state grading, metrics, CI gate
payments/                    x402 offer inspection, payment, settlement verification, test seller
.claude/agents/              subagent definitions (payments, planner, evals, tests)
```

## Getting started

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
git config --global core.longpaths true        # Windows only — see note below
python -m pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env                     # then fill it in
python -m pytest                                # unit + eval suite; integration/manual deselected
```

The `integration` and `manual` test tiers hit live testnet/mainnet and need a funded
`X402_WALLET_KEY`; run them explicitly with `-m integration` / `-m manual`.

### Windows: long paths

`requirements.txt` installs the `x402` SDK from a pinned git URL. Its nested Solidity
submodules blow past `MAX_PATH`, so a fresh Windows clone must `git config --global
core.longpaths true` before `pip install` or the install fails partway through. Linux CI is
unaffected.

## Principles

- **Non-custodial, always.** User funds never touch this service. This is a legal boundary.
- **No unverified on-chain constants.** Every address has a primary source and a test that
  reads it on chain.
- **Evals before behaviour.** The harness is the specification.
- **Report `pass^k`, not just `pass^1`.** The flattering number is not the real one.

## Not legal advice

The regulatory analysis in `docs/` is research, not counsel. A formal money-transmission
opinion is required before any mainnet launch involving other people's funds.
