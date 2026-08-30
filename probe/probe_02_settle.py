r"""
Probe 02 — Attempt one end-to-end x402 settlement.

Purpose
-------
Prove the full loop works exactly once: discover requirements -> sign a payment
authorization -> retry with payment -> resource returned -> settlement lands on chain.

One successful transaction hash is the entire deliverable. Do not generalise this
script. Do not turn it into a client library.

READ THIS BEFORE RUNNING
------------------------
The API calls below are transcribed from the published x402 Python SDK documentation
and have NOT been executed against an installed version. Treat every line marked
`TODO: VERIFY` as unconfirmed.

Confirm against the canonical source before trusting anything here:

    https://github.com/x402-foundation/x402   ->  python/x402
    https://docs.x402.org

The `x402` name is polluted on PyPI. There are TRON forks, Solana-only ports, and
unrelated commercial products with near-identical names and READMEs. Confirm the
package you installed came from the x402 Foundation repository before you sign
anything with a real key.

Two things to confirm on day one
--------------------------------
1. Does the Python SDK support Base / Base Sepolia for the `exact` scheme?
   The docs state TypeScript supports every network while Go and Python support a
   subset. If Base is not in the Python subset, stop and take the TypeScript sidecar
   path described in docs/WEEK1_GATE.md. This is a week-1 decision, not a week-5 one.

2. Which facilitator are you using, and which network does it serve?
   The public facilitator at https://x402.org/facilitator is documented as working on
   Base Sepolia. Most real endpoints in the wild are Base mainnet only. These are not
   interchangeable.

Safety
------
Use a throwaway wallet. Testnet funds, or a few dollars of mainnet USDC. Never a
personal wallet. The private key comes from the environment; if you are tempted to
paste it into this file, stop.

Usage (PowerShell)
------------------
    python probe\probe_02_settle.py https://<endpoint>
"""

from __future__ import annotations

import json
import os
import sys

import requests

TIMEOUT_SECONDS = 30

# TODO: VERIFY — read the correct value from the x402 docs and record the source URL
# in probe/findings.md. Do not guess. Do not let a model fill this in.
FACILITATOR_URL = os.environ.get("X402_FACILITATOR_URL", "")

# TODO: VERIFY — chain identifier form. The SDK examples use CAIP-2 style
# ("eip155:*"). Confirm the exact string the installed version expects for Base
# Sepolia (chain id 84532) and Base mainnet (chain id 8453).
CHAIN_SELECTOR = os.environ.get("X402_CHAIN_SELECTOR", "eip155:*")


def load_private_key() -> str:
    key = os.environ.get("PROBE_PRIVATE_KEY", "")
    if not key:
        raise SystemExit(
            "PROBE_PRIVATE_KEY is not set.\n"
            "Set it in probe/.env (never committed) or in the shell:\n"
            '  Set-Item -Path Env:PROBE_PRIVATE_KEY -Value "0x..."\n'
            "Use a throwaway wallet."
        )
    return key


def fetch_payment_requirements(url: str) -> dict:
    """Step 1: ask for the resource, expect a 402 with payment requirements."""
    response = requests.get(url, timeout=TIMEOUT_SECONDS)
    if response.status_code != 402:
        raise SystemExit(
            f"Expected 402, got {response.status_code}. "
            "Either this endpoint is free or the URL is wrong. Record it and move on."
        )
    requirements = response.json()
    print("payment requirements:")
    print(json.dumps(requirements, indent=2, sort_keys=True))
    return requirements


def build_payment_payload(requirements: dict) -> dict:
    """
    Step 2: sign an authorization for the requested amount.

    TODO: VERIFY — the entire body of this function is transcribed from published
    examples and not confirmed against an installed SDK. Check the import paths,
    the class names, and the signer construction before relying on it.
    """
    from x402 import x402ClientSync  # TODO: VERIFY import path
    from x402.mechanisms.evm.exact import ExactEvmScheme  # TODO: VERIFY import path

    # TODO: VERIFY — how the SDK expects a signer to be supplied. It may want an
    # eth_account LocalAccount, a raw key, or its own wrapper type.
    from eth_account import Account

    signer = Account.from_key(load_private_key())

    client = x402ClientSync()
    client.register(CHAIN_SELECTOR, ExactEvmScheme(signer=signer))

    payload = client.create_payment_payload(requirements)
    print("\nsigned payment payload constructed")
    return payload


def retry_with_payment(url: str, payload: dict) -> requests.Response:
    """
    Step 3: repeat the request carrying the payment.

    TODO: VERIFY — the header name and encoding. Published material references an
    X-PAYMENT header carrying a base64-encoded payload, but confirm the exact form
    the current wire version expects rather than assuming.
    """
    headers = {"X-PAYMENT": json.dumps(payload)}  # TODO: VERIFY encoding
    return requests.get(url, headers=headers, timeout=TIMEOUT_SECONDS)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    url = sys.argv[1]

    if not FACILITATOR_URL:
        print(
            "X402_FACILITATOR_URL is not set. Read the correct facilitator URL from\n"
            "the x402 docs, confirm which network it serves, and set it explicitly.\n"
            "Refusing to proceed with a guessed value."
        )
        return 2

    print(f"\n[1/3] requesting {url} without payment")
    requirements = fetch_payment_requirements(url)

    print("\n[2/3] signing payment authorization")
    payload = build_payment_payload(requirements)

    print("\n[3/3] retrying with payment")
    response = retry_with_payment(url, payload)

    print(f"\nstatus: {response.status_code} {response.reason}")
    print("response headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")

    print("\nbody (first 2000 bytes):")
    print(response.text[:2000])

    print("\n" + "=" * 72)
    print("If this succeeded, find the settlement transaction hash and record it in")
    print("probe/findings.md along with the network. That hash is the deliverable.")
    print("Verify it on a block explorer. A 200 response is not proof of settlement.")

    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
