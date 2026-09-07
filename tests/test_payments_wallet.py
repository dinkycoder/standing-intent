from decimal import Decimal

import pytest
from eth_account import Account

from payments.constants import CHAIN_ID_BASE_MAINNET
from payments.wallet import CdpWallet, LocalWallet, Wallet


@pytest.fixture
def throwaway_key():
    return Account.create().key.hex()   # generated per test; never a real funded key


def test_local_wallet_address_matches_key(throwaway_key):
    w = LocalWallet(throwaway_key)
    assert w.address == Account.from_key(throwaway_key).address
    assert w.address.startswith("0x") and len(w.address) == 42


def test_local_wallet_is_a_wallet(throwaway_key):
    assert isinstance(LocalWallet(throwaway_key), Wallet)   # runtime_checkable Protocol


def test_x402_signer_is_usable(throwaway_key):
    from x402.mechanisms.evm import EthAccountSigner
    signer = LocalWallet(throwaway_key).x402_signer()
    assert isinstance(signer, EthAccountSigner)


def test_from_env_reads_the_var(monkeypatch, throwaway_key):
    monkeypatch.setenv("X402_WALLET_KEY", throwaway_key)
    assert LocalWallet.from_env().address == Account.from_key(throwaway_key).address


def test_from_env_missing_var_raises(monkeypatch):
    monkeypatch.delenv("X402_WALLET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        LocalWallet.from_env()


def test_usdc_balance_reads_known_address():
    # The Week-1 buyer wallet holds ~1.999 USDC on Base mainnet (findings section 7).
    from payments.wallet import _usdc_balance_of
    known = "0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0"
    try:
        b = _usdc_balance_of(known, CHAIN_ID_BASE_MAINNET)
    except ConnectionError:
        pytest.skip("no Base mainnet RPC reachable")
    assert isinstance(b, Decimal)
    # > 0 catches a zero-decode (wrong selector / padding / token addr);
    # < 1000 catches a garbage huge-int decode. Loose on purpose: this wallet
    # is designed to be spent down, so don't couple to the live balance.
    assert Decimal(0) < b < Decimal(1000)


def test_cdp_wallet_is_a_seam():
    with pytest.raises(NotImplementedError):
        CdpWallet()
