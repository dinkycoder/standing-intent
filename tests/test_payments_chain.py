import pytest

from payments import constants
from payments.chain import get_web3, wait_for_receipt


def test_get_web3_connects_to_base_sepolia():
    w3 = get_web3(constants.CHAIN_ID_BASE_SEPOLIA)
    assert w3.eth.chain_id == constants.CHAIN_ID_BASE_SEPOLIA


def test_wait_for_receipt_raises_after_retries_exhausted():
    w3 = get_web3(constants.CHAIN_ID_BASE_SEPOLIA)
    with pytest.raises(TimeoutError):
        wait_for_receipt(w3, "0x" + "00" * 32, retries=1, delay=0.01)
