import pytest
import requests
from web3 import Web3

from payments import constants
from payments.chain import get_web3

_ABI = [{"type": "function", "name": "PERMISSION_MANAGER", "stateMutability": "view",
         "inputs": [], "outputs": [{"name": "", "type": "address"}]}]


def test_spend_router_is_bound_to_the_real_spend_permission_manager():
    # This is a default-tier (unmarked) test, so it must not go red on a
    # third-party RPC outage -- same discipline as tests/test_payments_
    # constants.py's _rpc helper: skip on a transport failure, never pass
    # silently. Only transport exceptions are caught; a reachable RPC that
    # returns the wrong address, or no code at SPEND_ROUTER (which surfaces as
    # web3's BadFunctionCallOutput, deliberately NOT caught here), still FAILS
    # the pin.
    try:
        w3 = get_web3(constants.CHAIN_ID_BASE_SEPOLIA)
        router = w3.eth.contract(address=Web3.to_checksum_address(constants.SPEND_ROUTER), abi=_ABI)
        got = router.functions.PERMISSION_MANAGER().call()
    except (ConnectionError, TimeoutError, requests.exceptions.RequestException) as exc:
        pytest.skip(f"Base Sepolia RPC unreachable: {exc!r}")
    assert got.lower() == constants.SPEND_PERMISSION_MANAGER.lower()
