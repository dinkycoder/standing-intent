import json
import urllib.error
import urllib.request

import pytest

from payments import constants

_HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}


def _rpc(chain_id: int, method: str, params: list):
    last = None
    for url in constants.rpc_urls(chain_id):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        try:
            req = urllib.request.Request(url, data=body, headers=_HEADERS)
            out = json.load(urllib.request.urlopen(req, timeout=20))
            if "result" in out:
                return out["result"]
            last = out
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:  # pragma: no cover
            last = exc
    pytest.skip(f"all RPCs unreachable for chain {chain_id}: {last!r}")


def _eth_call(chain_id: int, to: str, selector: str) -> str:
    return _rpc(chain_id, "eth_call", [{"to": to, "data": selector}, "latest"])


def _decode_string(hex_result: str) -> str:
    raw = bytes.fromhex(hex_result[2:])
    # ABI: offset(32) | length(32) | data
    length = int.from_bytes(raw[32:64], "big")
    return raw[64:64 + length].decode()


SYMBOL_SEL = "0x95d89b41"   # symbol()
DECIMALS_SEL = "0x313ce567" # decimals()


@pytest.mark.parametrize("chain_id,usdc", [
    (constants.CHAIN_ID_BASE_SEPOLIA, constants.USDC_BASE_SEPOLIA),
    (constants.CHAIN_ID_BASE_MAINNET, constants.USDC_BASE_MAINNET),
])
def test_usdc_symbol_and_decimals(chain_id, usdc):
    assert _decode_string(_eth_call(chain_id, usdc, SYMBOL_SEL)) == "USDC"
    assert int(_eth_call(chain_id, usdc, DECIMALS_SEL), 16) == 6


@pytest.mark.parametrize("chain_id", [
    constants.CHAIN_ID_BASE_SEPOLIA, constants.CHAIN_ID_BASE_MAINNET,
])
def test_chain_id_matches(chain_id):
    assert int(_rpc(chain_id, "eth_chainId", []), 16) == chain_id


@pytest.mark.parametrize("facilitator", [constants.FACILITATOR_CDP, constants.FACILITATOR_PAYAI])
def test_mainnet_facilitator_discovery_is_public(facilitator):
    url = facilitator.rstrip("/") + "/discovery/resources"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            assert resp.status == 200
    except urllib.error.HTTPError as exc:
        # A 4xx (or any <500) from a documented public endpoint means the URL
        # moved or lost its no-auth discovery route -- that must FAIL the pin,
        # not skip it. Only a 5xx is treated as a transient server outage.
        if exc.code < 500:
            raise
        pytest.skip(f"facilitator {facilitator} server error: {exc!r}")
    except (TimeoutError, urllib.error.URLError) as exc:
        pytest.skip(f"facilitator unreachable: {exc!r}")


def test_testnet_facilitator_is_reachable():
    # Liveness pin for FACILITATOR_TESTNET (x402.org/facilitator). The x402
    # facilitator exposes GET /supported (the scheme/network capability list);
    # fall back to the base URL. Any <500 response proves the host serves the
    # facilitator; skip only on a true network outage.
    for path in ("/supported", ""):
        req = urllib.request.Request(
            constants.FACILITATOR_TESTNET.rstrip("/") + path,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                assert 200 <= resp.status < 500
                return
        except urllib.error.HTTPError as exc:
            if exc.code < 500:  # a documented 4xx still proves the host serves the facilitator
                return
        except (urllib.error.URLError, TimeoutError):
            continue
    pytest.skip("x402.org/facilitator unreachable")


def test_transfer_topic_is_keccak_of_transfer_event():
    from eth_utils import keccak
    assert "0x" + keccak(text="Transfer(address,address,uint256)").hex() == constants.TRANSFER_TOPIC
