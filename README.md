# Standing Intent

An autonomous procurement agent for digital goods and APIs, settling in USDC on Base via
the x402 protocol, operating under a single user-signed Spend Permission.

The user signs **one** capped, revocable authorization. The agent then discovers vendors,
evaluates offers, and completes purchases with **zero further human contact** until the budget
is exhausted or an out-of-policy condition forces escalation.

**Current phase: Week 8 — failure, recovery, and retries.** Weeks 1–7 of the thirteen-week
plan are complete, merged to `main`, and live-verified:

- **Week 1** — the endpoint-availability gate closed GREEN (`docs/archive/probe/findings.md`).
- **Week 2** — the eval harness lives in `evals/`: task specs, terminal-state grading, `pass^k`
  metrics, CI gating. Design in `docs/superpowers/specs/2026-09-02-eval-harness-design.md`.
- **Week 3** — the x402 payments spine lives in `payments/`: offer inspection, payment
  construction, on-chain settlement verification, a local test seller. The harness now grades
  agents against **verified on-chain settlements**, not their self-reports. Integration tests
  run on Base Sepolia; one real **Base mainnet** payment (0.001 USDC, facilitator-relayed, buyer
  holding no ETH) is recorded in `docs/week3-mainnet-gate.md`.
- **Week 4** — the Base Spend Permission: sign, register, spend, and revoke, against a
  `SpendRouter` deployed to Base Sepolia (`docs/week4-spend-router-deploy.md`). Spend-within-cap,
  spend-above-cap revert, and revoked-permission rejection all passed as **real on-chain
  transactions**, not dry-run reverts (`docs/week4-spend-permission-live-verification.md`).
- **Week 5** — `claude-planner-v1` (`evals/agents/claude_planner.py`) replaced the always-fails
  stub. First billed live run: `pass^1 = pass^4 = pass^8 = 1.00` on every shipped synthetic spec,
  zero budget violations (`docs/week5-claude-planner-live-run.md`).
- **Week 6** — the policy layer in `evals/guardrail.py`: `check_purchase` (vendor membership +
  price sanity, agent-side and opt-in) and `check_not_duplicate` (idempotency, a hard gate every
  payment passes through). Live-verified with the new `price_anomaly_escalates` spec
  (`docs/week6-guardrail-live-run.md`). The Week 6 design spec also records why paying a real
  x402 vendor out of Spend-Permission-capped funds has **no clean non-custodial path** with
  currently accessible tooling; that route is parked pending a formal legal opinion.
- **Week 7** — trained model v1 in `evals/ml/`: a Beta-Binomial vendor-reliability tracker and a
  LogisticRegression accept/reject/escalate price classifier (65.4% test accuracy against a 57.1%
  majority-class baseline, calibrated to within 7 points across deciles). Both run end to end on
  real numbers (`docs/week7-trained-model-live-run.md`).

**Neither Week 7 model is wired into a live agent decision yet.** That is deliberate and matches
the pattern every prior week has used: build the artifact, prove it on real numbers, and only
then let it change behaviour. `evals/ml/` is imported by `scripts/`, not by the agent.

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
  week4-spend-router-deploy.md             SpendRouter deployment record (Base Sepolia)
  week4-spend-permission-live-verification.md   sign/spend/revoke, verified on chain
  week5-claude-planner-live-run.md         first billed live planner run
  week6-guardrail-live-run.md              guardrail layer against a live model
  week7-trained-model-live-run.md          classifier + reliability tracker, real numbers
  math/                      derivations behind the metrics (binomial intervals, calibration)
  FOUNDRY_SETUP.md           Solidity toolchain setup for the router work
  archive/probe/             disposable week-1 scripts + findings.md (the gate verdict)
  superpowers/               design specs and build plans, per phase
evals/                       eval harness — task specs, terminal-state grading, metrics, CI gate
  agents/                    claude-planner-v1 and the superseded stub
  guardrail.py               vendor membership, price sanity, duplicate-purchase gate
  ml/                        trained artifacts — not yet wired into live decisions
  tasks/                     task specs (synthetic + one real x402 spec)
payments/                    x402 offer inspection, payment, settlement verification, test seller
  spend_permission.py        sign, register, spend, revoke
  spend_router.py            the deployed router the permission spends through
scripts/                     live-run entry points (planner evals, training, reliability report)
tests/                       unit, integration, and manual tiers
.claude/agents/              subagent definitions (payments, planner, evals, tests)
.github/workflows/evals.yml  CI — unit + eval suite, live tiers deselected
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
`X402_WALLET_KEY`; run them explicitly with `-m integration` / `-m manual`. The planner scripts
in `scripts/` make billed Claude API calls and need `ANTHROPIC_API_KEY`.

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
- **Build, prove, then wire.** A model earns a live decision by its measured numbers, not by
  existing.

## Not legal advice

The regulatory analysis in `docs/` is research, not counsel. A formal money-transmission
opinion is required before any mainnet launch involving other people's funds.
