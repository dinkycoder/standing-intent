# Standing Intent

An autonomous procurement agent for digital goods and APIs, settling in USDC on Base via
the x402 protocol, operating under a single user-signed Spend Permission.

The user signs **one** capped, revocable authorization. The agent then discovers vendors,
evaluates offers, and completes purchases with **zero further human contact** until the budget
is exhausted or an out-of-policy condition forces escalation.

**Current phase: Week 2 — environment + eval harness.** The Week 1 gate closed GREEN (`docs/archive/probe/findings.md`). The eval harness lives in `evals/`; `docs/superpowers/specs/2026-09-02-eval-harness-design.md` is the design and `docs/superpowers/plans/2026-09-07-week2-eval-harness.md` the build plan.

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
  WEEK1_GATE.md              the current gate: pass/fail criteria
probe/                       disposable week-1 scripts, deleted after the gate
  findings.md                the surviving artifact — the gate's verdict
.claude/agents/              subagent definitions (payments, planner, evals, tests)
```

## Getting started

Right now there is only one thing to do: run the week-1 gate.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r probe\requirements.txt
Copy-Item probe\.env.example probe\.env   # then fill it in
```

Read [`docs/WEEK1_GATE.md`](docs/WEEK1_GATE.md) before running anything. Do the first probe by
hand with `curl.exe` rather than generating code for it.

### Installing the payments deps on Windows

`requirements.txt` installs the `x402` SDK from a pinned git URL. Its nested Solidity
submodules blow past `MAX_PATH`, so a fresh Windows clone must enable long paths first or the
`pip install` fails partway through:

```powershell
git config --global core.longpaths true
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Linux CI is unaffected.

## Principles

- **Non-custodial, always.** User funds never touch this service. This is a legal boundary.
- **No unverified on-chain constants.** Every address has a primary source and a test that
  reads it on chain.
- **Evals before behaviour.** The harness is the specification.
- **Report `pass^k`, not just `pass^1`.** The flattering number is not the real one.

## Not legal advice

The regulatory analysis in `docs/` is research, not counsel. A formal money-transmission
opinion is required before any mainnet launch involving other people's funds.
