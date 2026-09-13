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


def test_testnet_facilitator_advertises_exact_base_sepolia():
    # Capability pin for FACILITATOR_TESTNET (constants.py:33). CLAUDE.md rule 2
    # wants a test that asserts something only the *real* facilitator returns --
    # a liveness check that passes for any host up is not enough (I-3). Use the
    # same client the flask middleware uses and assert /supported advertises the
    # `exact` scheme on Base Sepolia. Skip ONLY on a transport failure or a
    # transient 5xx; a reachable host that does not advertise exact/eip155:84532
    # must FAIL the pin.
    import re

    import httpx

    from x402.http import FacilitatorConfig, HTTPFacilitatorClientSync

    client = HTTPFacilitatorClientSync(
        FacilitatorConfig(url=constants.FACILITATOR_TESTNET, timeout=20)
    )
    try:
        supported = client.get_supported()
    except httpx.HTTPError as exc:  # connect / read / timeout -> transport outage
        pytest.skip(f"x402 testnet facilitator unreachable: {exc!r}")
    except ValueError as exc:  # get_supported raises bare ValueError on a non-200
        if re.search(r"failed \(5\d\d\)", str(exc)):
            pytest.skip(f"x402 testnet facilitator 5xx: {exc!r}")
        raise
    finally:
        client.close()

    kinds = supported.kinds
    assert any(
        k.scheme == "exact" and k.network == "eip155:84532" for k in kinds
    ), f"{constants.FACILITATOR_TESTNET} does not advertise exact / eip155:84532: {kinds!r}"


def test_transfer_topic_is_keccak_of_transfer_event():
    from eth_utils import keccak
    assert "0x" + keccak(text="Transfer(address,address,uint256)").hex() == constants.TRANSFER_TOPIC


@pytest.mark.parametrize("chain_id", [
    constants.CHAIN_ID_BASE_SEPOLIA, constants.CHAIN_ID_BASE_MAINNET,
])
def test_spend_permission_manager_typehash_matches_pinned_source(chain_id):
    # Pin for SPEND_PERMISSION_MANAGER (constants.py). CLAUDE.md rule 2 wants an
    # assertion only the *real* contract would satisfy -- a bytecode-non-empty
    # check would pass for any contract at that address. SPEND_PERMISSION_TYPEHASH
    # is a public constant getter unique to this ABI; the selector is computed
    # the same way as SYMBOL_SEL/DECIMALS_SEL above (keccak of the signature,
    # first 4 bytes), and the expected return value is recomputed independently
    # from SPEND_PERMISSION_TYPE_STRING rather than hardcoded (same pattern as
    # test_transfer_topic_is_keccak_of_transfer_event).
    from eth_utils import keccak

    selector = "0x" + keccak(text="SPEND_PERMISSION_TYPEHASH()").hex()[:8]
    expected = "0x" + keccak(text=constants.SPEND_PERMISSION_TYPE_STRING).hex()
    got = _eth_call(chain_id, constants.SPEND_PERMISSION_MANAGER, selector)
    assert got.lower() == expected.lower()
