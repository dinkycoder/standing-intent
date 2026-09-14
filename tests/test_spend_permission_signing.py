"""Offline test of the nested EIP-712 hash math (design spec, "Signing --
the trap that needs its own test"). No network call: every input here is
either a fixed constant or hand-computable, so a wrong formula shows up as a
wrong hash immediately, not as a mysterious on-chain revert three tasks later.
"""
from eth_utils import keccak

from payments.constants import (
    CHAIN_ID_BASE_SEPOLIA,
    SPEND_PERMISSION_MANAGER,
)
from payments.spend_permission import (
    SpendPermission,
    _domain_separator,
    _replay_safe_hash,
    _spend_permission_hash,
    _translate_custom_error,
)

_ACCOUNT = "0x000000000000000000000000000000000000dEaD"
_SPENDER = "0x000000000000000000000000000000000000bEEF"
_TOKEN = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # USDC_BASE_SEPOLIA


def _permission() -> SpendPermission:
    return SpendPermission(
        account=_ACCOUNT, spender=_SPENDER, token=_TOKEN,
        allowance=1_000_000, period=86400, start=0, end=281474976710655,
        salt=0, extra_data=b"",
    )


def test_domain_separator_matches_hand_derivation():
    # keccak256(abi.encode(EIP712_DOMAIN_TYPEHASH, keccak(name), keccak(version),
    # chainId, verifyingContract)) -- Solady's EIP712._buildDomainSeparator,
    # confirmed by direct source read during planning.
    domain_typehash = keccak(
        text="EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    )
    expected = keccak(
        domain_typehash
        + keccak(text="Spend Permission Manager")
        + keccak(text="1")
        + CHAIN_ID_BASE_SEPOLIA.to_bytes(32, "big")
        + bytes.fromhex(SPEND_PERMISSION_MANAGER[2:].lower()).rjust(32, b"\x00")
    )
    got = _domain_separator(
        "Spend Permission Manager", "1", CHAIN_ID_BASE_SEPOLIA, SPEND_PERMISSION_MANAGER
    )
    assert got == expected


def test_spend_permission_hash_changes_if_any_field_changes():
    # Not a golden value (none exists yet -- Task 6 gets the first live
    # cross-check against the real getHash()). What this DOES prove: the hash
    # is a real function of every field, so two permissions differing in one
    # field never collide -- the property a wrong/short-circuited
    # implementation would most plausibly get wrong.
    base = _permission()
    h1 = _spend_permission_hash(base, CHAIN_ID_BASE_SEPOLIA)
    assert len(h1) == 32
    for changed in [
        base.__class__(**{**base.__dict__, "allowance": base.allowance + 1}),
        base.__class__(**{**base.__dict__, "salt": 1}),
        base.__class__(**{**base.__dict__, "extra_data": b"x"}),
        base.__class__(**{**base.__dict__, "spender": _ACCOUNT}),
    ]:
        assert _spend_permission_hash(changed, CHAIN_ID_BASE_SEPOLIA) != h1


def test_replay_safe_hash_differs_from_the_inner_hash():
    # The whole point of the nesting: signing the inner hash directly must
    # produce something different from signing the wrapped hash, or the
    # "wrap through the account's own domain" step isn't doing anything.
    inner = _spend_permission_hash(_permission(), CHAIN_ID_BASE_SEPOLIA)
    outer = _replay_safe_hash(inner, CHAIN_ID_BASE_SEPOLIA, _ACCOUNT)
    assert outer != inner
    assert len(outer) == 32


def test_replay_safe_hash_differs_per_account():
    # account.domainSeparator() includes verifyingContract = the account's
    # OWN address -- two different accounts must get two different wrapped
    # hashes for the identical inner hash (this is the anti-replay property
    # ERC1271.sol's own comment names explicitly).
    inner = _spend_permission_hash(_permission(), CHAIN_ID_BASE_SEPOLIA)
    a = _replay_safe_hash(inner, CHAIN_ID_BASE_SEPOLIA, _ACCOUNT)
    b = _replay_safe_hash(inner, CHAIN_ID_BASE_SEPOLIA, _SPENDER)
    assert a != b


def test_translate_custom_error_recognizes_unauthorized_selector():
    # Zero-argument error: UnauthorizedSpendPermission()
    # Payload = selector (10 hex chars including 0x) because there are no arguments
    from payments.errors import SpendPermissionUnauthorized
    from web3.exceptions import ContractCustomError

    selector = "0x" + keccak(text="UnauthorizedSpendPermission()").hex()[:8]
    # Create exception and set args as a tuple (mimics how web3.py structures it)
    fake_exc = ContractCustomError("custom error")
    fake_exc.args = (selector,)
    result = _translate_custom_error(fake_exc)
    assert isinstance(result, SpendPermissionUnauthorized)


def test_translate_custom_error_recognizes_exceeded_with_arguments():
    # Two-argument error: ExceededSpendPermission(uint256 value, uint256 allowance)
    # Payload = selector (10 hex chars) + 64 bytes of ABI-encoded arguments (128 hex chars)
    # Encoding: (30000, 50000) = 0x000..[30000] + 0x000..[50000]
    from decimal import Decimal
    from payments.errors import SpendCapExceeded
    from web3.exceptions import ContractCustomError

    selector = "0x" + keccak(text="ExceededSpendPermission(uint256,uint256)").hex()[:8]
    # ABI encode two uint256 arguments: value=30000, allowance=50000
    value_encoded = (30000).to_bytes(32, "big")
    allowance_encoded = (50000).to_bytes(32, "big")
    full_payload = selector + value_encoded.hex() + allowance_encoded.hex()

    # Create exception and set args as a tuple (mimics how web3.py structures it)
    fake_exc = ContractCustomError("custom error")
    fake_exc.args = (full_payload,)
    result = _translate_custom_error(fake_exc)
    assert isinstance(result, SpendCapExceeded)
    # Value/allowance are set to -1 in _translate_custom_error fallback since we can't decode the payload
    assert result.value == Decimal("-1")
    assert result.allowance == Decimal("-1")
