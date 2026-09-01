r"""
Probe 02 — One end-to-end x402 settlement, using the real v2 client API.

Purpose
-------
Prove the full loop works exactly once:

    unpaid GET  ->  402 + PAYMENT-REQUIRED  ->  client signs  ->
    retry + PAYMENT-SIGNATURE  ->  200 + PAYMENT-RESPONSE  ->  settlement on chain

One settlement transaction hash is the entire deliverable. Do not generalise
this script. Do not turn it into a client library.

What changed from the first draft of this file
----------------------------------------------
The previous version hand-rolled a three-step flow and sent an ``X-PAYMENT``
header. That is x402 **v1**. This project targets **v2**:

  * the 402 carries a ``PAYMENT-REQUIRED`` header (base64 JSON); the body is ``{}``
  * the retry carries a ``PAYMENT-SIGNATURE`` header
  * the settled 200 carries a ``PAYMENT-RESPONSE`` header

None of those are built by hand. The ``x402_requests(client)`` session wrapper
intercepts the 402, signs, retries, and exposes the settlement response. This is
the exact pattern in the x402-foundation reference repo,
``examples/python/clients/requests/main.py`` (SDK ``x402`` 2.21.0).

The buyer does NOT choose a facilitator or a network. The seller's 402 declares
the network (CAIP-2, e.g. ``eip155:84532`` = Base Sepolia) and the asset. The
facilitator is the seller's configuration. So this script has no facilitator URL
and no chain-selector knob — those were v1-era misconceptions.

Safety
------
Throwaway wallet only. Testnet funds, or a few dollars of mainnet USDC. Never a
personal wallet. ``EVM_PRIVATE_KEY`` comes from the environment (probe/.env,
never committed). The client spend cap below is pinned to $0.01.

Usage (PowerShell)
------------------
    # start your local seller first (the x402-reference flask example), then:
    python probe\probe_02_settle.py http://localhost:4021/weather

    # or rely on RESOURCE_SERVER_URL + ENDPOINT_PATH from probe/.env:
    python probe\probe_02_settle.py
"""

from __future__ import annotations

import base64
import json
import os
import sys

import requests
from dotenv import load_dotenv

TIMEOUT_SECONDS = 30
SPEND_CAP = "$0.01"  # client-side max_amount_per_payment for this probe

# probe/.env sits next to this file, not at the repo root.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))


def resolve_url() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    base = os.environ.get("RESOURCE_SERVER_URL", "")
    path = os.environ.get("ENDPOINT_PATH", "")
    if base and path:
        return f"{base}{path}"
    raise SystemExit(
        "No URL. Pass one on the command line, or set RESOURCE_SERVER_URL and\n"
        "ENDPOINT_PATH in probe/.env.\n"
        "  python probe\\probe_02_settle.py http://localhost:4021/weather"
    )


def load_private_key() -> str:
    key = os.environ.get("EVM_PRIVATE_KEY", "")
    if not key:
        raise SystemExit(
            "EVM_PRIVATE_KEY is not set.\n"
            "Put it in probe/.env (never committed) or the shell:\n"
            '  Set-Item -Path Env:EVM_PRIVATE_KEY -Value "0x..."\n'
            "Use a throwaway wallet."
        )
    return key


def show_raw_402(url: str) -> None:
    """One unpaid request, no SDK. Look at the wire format with your own eyes."""
    print(f"\n[1/2] unpaid GET {url}")
    print("-" * 72)
    response = requests.get(url, timeout=TIMEOUT_SECONDS)
    print(f"status: {response.status_code} {response.reason}")

    print("\nresponse headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")

    print("\nresponse body:")
    print(response.text[:2000] or "(empty)")

    header = response.headers.get("payment-required")
    if header:
        print("\nPAYMENT-REQUIRED header, base64-decoded:")
        try:
            decoded = json.loads(base64.b64decode(header))
            print(json.dumps(decoded, indent=2, sort_keys=True))
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"  could not decode: {exc}")
            print(f"  raw: {header}")

    if response.status_code != 402:
        raise SystemExit(
            f"\nExpected 402, got {response.status_code}. Is the seller running, and\n"
            "is this a paid route? Record what you saw and stop."
        )

    print("\n>>> Paste the decoded object above into probe/findings.md section 3. <<<")


def settle_once(url: str) -> int:
    """The paid flow. The session wrapper does the signing and the retry."""
    from eth_account import Account

    from x402 import x402ClientSync
    from x402.http import x402HTTPClientSync
    from x402.http.clients import x402_requests
    from x402.mechanisms.evm import EthAccountSigner
    from x402.mechanisms.evm.exact.register import register_exact_evm_client

    account = Account.from_key(load_private_key())
    client = x402ClientSync().set_spend_controls({"max_amount_per_payment": SPEND_CAP})
    register_exact_evm_client(client, EthAccountSigner(account))
    http_client = x402HTTPClientSync(client)

    print(f"\n[2/2] paid GET {url}")
    print(f"  signer:    {account.address}")
    print(f"  spend cap: {SPEND_CAP}")
    print("-" * 72)

    with x402_requests(client) as session:
        response = session.get(url, timeout=TIMEOUT_SECONDS)

    print(f"status: {response.status_code} {response.reason}")
    print("\nresponse headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    print("\nbody (first 2000 bytes):")
    print(response.text[:2000])

    try:
        settle = http_client.get_payment_settle_response(
            lambda name: response.headers.get(name)
        )
    except ValueError:
        print("\nNo PAYMENT-RESPONSE header. Payment did not settle.")
        return 1

    print("\nPAYMENT-RESPONSE (settlement):")
    print(settle.model_dump_json(indent=2))

    tx = getattr(settle, "transaction", None)
    network = getattr(settle, "network", None)
    print("\n" + "=" * 72)
    print(f"transaction: {tx}")
    print(f"network:     {network}")
    print("Record that hash and network in probe/findings.md section 4, then verify")
    print("it on a block explorer. A 200 is not proof of settlement — the chain is.")
    return 0 if response.status_code == 200 else 1


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"-h", "--help"}:
        print(__doc__)
        return 0

    url = resolve_url()
    show_raw_402(url)
    return settle_once(url)


if __name__ == "__main__":
    raise SystemExit(main())
