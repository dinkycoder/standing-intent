from decimal import Decimal

import pytest

from payments.constants import CHAIN_ID_BASE_MAINNET, CHAIN_ID_BASE_SEPOLIA
from payments.settlement import ExpectedSettlement, verify_settlement

# Golden historical settlements from the Week-1 gate (docs/archive/probe/findings.md section 4).
SEPOLIA_TX = "0x1b1b78e2fcba693ace023bb8af2ae19277f597d6f82b6a2adcc6bd6765dd309d"
SEPOLIA_PAYER = "0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0"
SEPOLIA_PAYTO = "0xa31C8f81A66C779A312b4aFA85aD38c8436B4F6D"
SEPOLIA_AMOUNT = Decimal("0.01")

MAINNET_TX = "0x44cb0f1e7bd5794e1d57ff10974fa1e544a43bd90796922e14d6a7e1cd43fcc3"
MAINNET_PAYER = "0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0"
MAINNET_PAYTO = "0x0E84dDEdAaE6A779c462C22a59F301EC31B6b808"
MAINNET_AMOUNT = Decimal("0.001")
MAINNET_USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"


def _expected(payer, pay_to, amount, asset):
    return ExpectedSettlement(payer=payer, pay_to=pay_to, asset=asset, amount=amount)


def _verify_or_skip(tx_hash, expected, network):
    """verify_settlement, but skip on a true RPC outage.

    Per the controller ruling: SettlementNotConfirmed means "the tx is not on
    chain", not "I couldn't reach an RPC". A total-RPC-outage surfaces as a
    plain ConnectionError; that must skip these pins, not red the suite.
    """
    try:
        return verify_settlement(tx_hash, expected, network)
    except ConnectionError as exc:
        pytest.skip(f"no RPC reachable: {exc!r}")


def test_verifies_known_mainnet_settlement():
    v = _verify_or_skip(
        MAINNET_TX,
        _expected(MAINNET_PAYER, MAINNET_PAYTO, MAINNET_AMOUNT, MAINNET_USDC),
        CHAIN_ID_BASE_MAINNET,
    )
    assert v.status_ok is True
    assert v.matches_expected is True and v.mismatch is None
    assert v.transfer_from.lower() == MAINNET_PAYER.lower()
    assert v.transfer_to.lower() == MAINNET_PAYTO.lower()
    assert v.amount_atomic == 1000 and v.amount_usdc == MAINNET_AMOUNT
    assert v.submitted_by.lower() != MAINNET_PAYER.lower()   # facilitator relayer
    assert v.payer_paid_gas is False
    assert v.block_number == 50997392


def test_verifies_known_sepolia_settlement():
    v = _verify_or_skip(
        SEPOLIA_TX,
        _expected(SEPOLIA_PAYER, SEPOLIA_PAYTO, SEPOLIA_AMOUNT,
                  "0x036CbD53842c5426634e7929541eC2318f3dCF7e"),
        CHAIN_ID_BASE_SEPOLIA,
    )
    assert v.matches_expected is True
    assert v.amount_atomic == 10000


def test_wrong_expected_amount_does_not_match():
    v = _verify_or_skip(
        MAINNET_TX,
        _expected(MAINNET_PAYER, MAINNET_PAYTO, Decimal("0.999"), MAINNET_USDC),
        CHAIN_ID_BASE_MAINNET,
    )
    assert v.matches_expected is False
    assert "amount" in v.mismatch


def test_wrong_expected_payto_does_not_match():
    v = _verify_or_skip(
        MAINNET_TX,
        _expected(MAINNET_PAYER, "0x000000000000000000000000000000000000dEaD",
                  MAINNET_AMOUNT, MAINNET_USDC),
        CHAIN_ID_BASE_MAINNET,
    )
    assert v.matches_expected is False
    assert "pay_to" in v.mismatch or "to" in v.mismatch


def test_missing_tx_raises_not_confirmed():
    from payments.errors import SettlementNotConfirmed
    try:
        with pytest.raises(SettlementNotConfirmed):
            verify_settlement(
                "0x" + "00" * 32,
                _expected(MAINNET_PAYER, MAINNET_PAYTO, MAINNET_AMOUNT, MAINNET_USDC),
                CHAIN_ID_BASE_MAINNET,
            )
    except ConnectionError as exc:
        pytest.skip(f"no RPC reachable: {exc!r}")
