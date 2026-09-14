import pytest

from payments import constants
from payments.chain import get_web3, wait_for_receipt


def _web3_or_skip(chain_id: int):
    """get_web3 raises a bare ConnectionError when no RPC in the list answers.
    These are default-tier (unmarked) tests, so a third-party RPC outage would
    turn CI red for something that is not a defect -- skip instead, matching
    tests/test_payments_constants.py's _rpc helper. Never a silent pass: the
    skip names the chain and the error."""
    try:
        return get_web3(chain_id)
    except ConnectionError as exc:
        pytest.skip(f"all RPCs unreachable for chain {chain_id}: {exc!r}")


def test_get_web3_connects_to_base_sepolia():
    w3 = _web3_or_skip(constants.CHAIN_ID_BASE_SEPOLIA)
    assert w3.eth.chain_id == constants.CHAIN_ID_BASE_SEPOLIA


def test_wait_for_receipt_raises_after_retries_exhausted():
    w3 = _web3_or_skip(constants.CHAIN_ID_BASE_SEPOLIA)
    with pytest.raises(TimeoutError):
        wait_for_receipt(w3, "0x" + "00" * 32, retries=1, delay=0.01)
