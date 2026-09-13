"""On-chain pin for SMART_WALLET_FACTORY_V1_1 (CLAUDE.md rule 2).

Same discipline as test_payments_constants.py's SpendPermissionManager pin: a
primary-doc citation is not enough on its own, so this calls the real deployed
contracts and compares against a value recomputed independently at test time,
not hardcoded.

Two calls, chained: the factory's own `implementation()` getter, then
`domainSeparator()` on whatever address that returns. A wrong or unrelated
contract at SMART_WALLET_FACTORY_V1_1 would need to (a) expose an
`implementation()` getter AND (b) have *that* address implement the exact
EIP-712 domain formula with these exact name/version strings
(src/ERC1271.sol / src/CoinbaseSmartWallet.sol, same pinned commit as the
constant) to pass this by coincidence -- vanishingly unlikely.
"""

import json
import urllib.error
import urllib.request

import pytest
from eth_utils import keccak

from payments import constants

_HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

IMPLEMENTATION_SEL = "0x" + keccak(text="implementation()").hex()[:8]
DOMAIN_SEPARATOR_SEL = "0x" + keccak(text="domainSeparator()").hex()[:8]

# keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
# -- quoted verbatim from src/ERC1271.sol's domainSeparator(), recomputed here rather
# than hardcoded (same treatment as SPEND_PERMISSION_TYPE_STRING).
_EIP712_DOMAIN_TYPE_STRING = (
    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
)


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


def _decode_address(hex_result: str) -> str:
    return "0x" + hex_result[-40:]


def _left_pad32(b: bytes) -> bytes:
    return b.rjust(32, b"\x00")


def _address_bytes(addr: str) -> bytes:
    return _left_pad32(bytes.fromhex(addr[2:].lower()))


def _expected_domain_separator(chain_id: int, verifying_contract: str) -> str:
    # abi.encode(bytes32, bytes32, bytes32, uint256, address): five static words,
    # concatenated in order -- no offsets needed, all fixed-size types.
    encoded = (
        keccak(text=_EIP712_DOMAIN_TYPE_STRING)
        + keccak(text=constants.SMART_WALLET_DOMAIN_NAME)
        + keccak(text=constants.SMART_WALLET_DOMAIN_VERSION)
        + chain_id.to_bytes(32, "big")
        + _address_bytes(verifying_contract)
    )
    return "0x" + keccak(encoded).hex()


@pytest.mark.parametrize("chain_id", [
    constants.CHAIN_ID_BASE_SEPOLIA, constants.CHAIN_ID_BASE_MAINNET,
])
def test_smart_wallet_factory_implementation_domain_matches_pinned_source(chain_id):
    implementation = _decode_address(
        _eth_call(chain_id, constants.SMART_WALLET_FACTORY_V1_1, IMPLEMENTATION_SEL)
    )
    got = _eth_call(chain_id, implementation, DOMAIN_SEPARATOR_SEL)
    expected = _expected_domain_separator(chain_id, implementation)
    assert got.lower() == expected.lower()
