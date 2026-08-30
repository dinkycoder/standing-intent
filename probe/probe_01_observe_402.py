r"""
Probe 01 — Observe a real HTTP 402 response.

Purpose
-------
Look at the raw wire format with your own eyes, using nothing but `requests`.
No SDK, no abstraction, no generated wrapper. When the agent misbehaves in week 8
you will be reading this object, and you want to already know its shape.

This script asserts nothing and proves nothing about payment. It only shows you
what the server sends back when you ask for a paid resource without paying.

Usage (PowerShell)
------------------
    python probe\probe_01_observe_402.py https://<endpoint>

What to look for
----------------
  * The HTTP status. Is it actually 402?
  * The response body. It should describe payment requirements: an amount, an asset
    (usually a USDC contract address), a network / chain identifier, a pay-to address,
    a scheme name (`exact` is the common one), and a nonce or validity window.
  * Which network it names. `base-sepolia` and `base` are different answers with
    different consequences for the week-1 verdict.
  * Any `X-PAYMENT`-style headers, in either direction.

Record what you find in probe/findings.md. Paste the actual body, not a summary.
"""

from __future__ import annotations

import json
import sys

import requests

TIMEOUT_SECONDS = 20


def observe(url: str) -> None:
    print(f"\nGET {url}")
    print("-" * 72)

    try:
        response = requests.get(url, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        print(f"REQUEST FAILED: {exc}")
        print("\nThis is itself a finding. Record it: the endpoint may be dead,")
        print("geo-restricted, or behind a bot defence.")
        return

    print(f"status: {response.status_code} {response.reason}")

    if response.status_code != 402:
        print(
            "\nNOTE: not a 402. Either this endpoint is free, or it signals payment\n"
            "some other way, or the URL is wrong. Record which."
        )

    print("\nresponse headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")

    print("\nresponse body:")
    try:
        parsed = response.json()
        print(json.dumps(parsed, indent=2, sort_keys=True))
    except ValueError:
        # Not JSON. Some endpoints return an HTML paywall page instead.
        body = response.text
        print(body[:4000])
        if len(body) > 4000:
            print(f"\n... truncated, {len(body)} bytes total")

    print("\n" + "-" * 72)
    print("Now copy the payment-requirements object into probe/findings.md.")
    print("Do not summarise it. Paste it.")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        print("ERROR: supply an endpoint URL.")
        return 2

    for url in sys.argv[1:]:
        observe(url)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
