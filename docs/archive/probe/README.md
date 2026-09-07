# probe/ — disposable week-1 scripts

These scripts exist to answer one question and then die. They are **not** the beginning of the
codebase. Do not import from them, do not refactor them into the agent, do not add features to
them.

At the end of week 1, either delete this directory or move it to `docs/archive/probe/` as
evidence of what the gate found. `findings.md` is the part that survives.

## Setup (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r probe\requirements.txt
```

## Environment variables

Copy `.env.example` to `.env` and fill in. Never commit `.env`.

```powershell
Copy-Item probe\.env.example probe\.env
```

Use a throwaway wallet with only testnet funds, or a few dollars of mainnet USDC. Never a
personal wallet.

## Run order

```powershell
python probe\probe_01_observe_402.py https://<some-endpoint>
python probe\probe_02_settle.py https://<some-endpoint>
python probe\probe_03_discover.py <discovery-url-you-have-verified>
```

## The rule for these scripts

Every URL and address used here must have been read from primary documentation, not from a
model's suggestion. If a script has a `TODO: VERIFY` marker, it means the value was not
confirmed at the time of writing and **must not be run until you have confirmed it yourself.**
