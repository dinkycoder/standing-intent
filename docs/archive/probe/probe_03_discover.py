r"""
Probe 03 — Inventory the available x402 endpoints.

Purpose
-------
Answer the gate question: how many real, live, independently-operated, priced
endpoints exist on Base that a procurement basket could draw from?

The output is a table for probe/findings.md. Five or more is GREEN. Fewer is AMBER,
which means a hybrid basket with self-hosted stand-in endpoints. Neither is failure.

IMPORTANT
---------
This script deliberately does NOT contain a hardcoded discovery URL.

There are at least two distinct things called an "x402 Bazaar": the official Coinbase
Developer Platform discovery service, and a separate community project. They are not
the same and do not necessarily share an API. Confirm which one you mean and read its
endpoint from its own documentation, then pass it in.

Refusing to guess here is the point. A fabricated URL that returns a plausible-looking
404 will waste a day.

Usage (PowerShell)
------------------
    python probe\probe_03_discover.py https://<verified-discovery-url>

If no machine-readable discovery service is usable, do this by hand instead: collect
candidate endpoints from documentation and announcements, run probe_01 against each,
and fill in the table manually. A hand-built table of ten verified endpoints is worth
more than an automated list of a hundred unverified ones.
"""

from __future__ import annotations

import json
import sys
from typing import Any

import requests

TIMEOUT_SECONDS = 30


def fetch_catalog(discovery_url: str) -> Any:
    response = requests.get(discovery_url, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def summarise(catalog: Any) -> None:
    """
    Print whatever came back without assuming a schema.

    The response shape is not documented here on purpose. Look at it, then decide how
    to extract the fields you need. Do not let a model invent a parser for a schema
    neither of you has seen.
    """
    print(json.dumps(catalog, indent=2, sort_keys=True)[:8000])
    print("\n" + "-" * 72)
    print("Read the shape above, then extract into probe/findings.md:")
    print("  endpoint URL | what it sells | price | asset | network | live?")
    print("\nMark network carefully. base-sepolia and base are different answers.")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        print("ERROR: supply a discovery URL you have verified from primary docs.")
        return 2

    discovery_url = sys.argv[1]

    print(f"GET {discovery_url}\n")
    try:
        catalog = fetch_catalog(discovery_url)
    except requests.RequestException as exc:
        print(f"REQUEST FAILED: {exc}")
        print(
            "\nThis is a finding, not a bug. Either the URL is wrong, the service does\n"
            "not exist in the form you expected, or discovery is not machine-readable\n"
            "yet. Record which, and fall back to building the table by hand."
        )
        return 1

    summarise(catalog)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
