from web3 import Web3

from payments import constants
from payments.chain import get_web3

_ABI = [{"type": "function", "name": "PERMISSION_MANAGER", "stateMutability": "view",
         "inputs": [], "outputs": [{"name": "", "type": "address"}]}]


def test_spend_router_is_bound_to_the_real_spend_permission_manager():
    w3 = get_web3(constants.CHAIN_ID_BASE_SEPOLIA)
    router = w3.eth.contract(address=Web3.to_checksum_address(constants.SPEND_ROUTER), abi=_ABI)
    got = router.functions.PERMISSION_MANAGER().call()
    assert got.lower() == constants.SPEND_PERMISSION_MANAGER.lower()
