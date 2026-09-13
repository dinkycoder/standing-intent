"""Verified on-chain constants for the payment path.

Every value carries a primary-source URL. Values already read on chain during the
Week-1 gate cite docs/archive/probe/findings.md section 6. Each is re-pinned by
tests/test_payments_constants.py (CLAUDE.md rule 2).
"""

from __future__ import annotations

import os

# USDC, Base Sepolia -- Circle official docs:
# https://developers.circle.com/stablecoins/usdc-contract-addresses  (Testnet -> Base Sepolia)
# On-chain (findings section 6): symbol()="USDC", decimals()=6
USDC_BASE_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"

# USDC, Base mainnet -- Circle official docs:
# https://developers.circle.com/stablecoins/usdc-contract-addresses  (Mainnet -> Base)
# On-chain (findings section 6): name()="USD Coin", symbol()="USDC", decimals()=6
USDC_BASE_MAINNET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# Chain ids -- docs.x402.org/getting-started/quickstart-for-sellers + flask README
CHAIN_ID_BASE_SEPOLIA = 84532   # CAIP-2 eip155:84532  (findings section 6: eth_chainId)
CHAIN_ID_BASE_MAINNET = 8453    # CAIP-2 eip155:8453

USDC_BY_CHAIN = {
    CHAIN_ID_BASE_SEPOLIA: USDC_BASE_SEPOLIA,
    CHAIN_ID_BASE_MAINNET: USDC_BASE_MAINNET,
}

# Facilitators -- docs.x402.org/getting-started/quickstart-for-sellers
# test_testnet_facilitator_advertises_exact_base_sepolia pins this: GET /supported must
# advertise a kind with scheme "exact" and network "eip155:84532" (skips only on transport/5xx)
FACILITATOR_TESTNET = "https://x402.org/facilitator"          # Base Sepolia + Solana devnet only
FACILITATOR_CDP = "https://api.cdp.coinbase.com/platform/v2/x402"   # GET /discovery/resources -> 200 no auth
FACILITATOR_PAYAI = "https://facilitator.payai.network"            # GET /discovery/resources -> 200 no auth

# keccak256("Transfer(address,address,uint256)")  (ERC-20 Transfer event topic0)
# EIP-20: https://eips.ethereum.org/EIPS/eip-20  ("event Transfer(address indexed _from, address indexed _to, uint256 _value)")
# test_transfer_topic_is_keccak_of_transfer_event recomputes this with eth_utils.keccak.
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Read-only RPC endpoints, tried in order. publicnode first for mainnet: the
# Week-1 probe found sepolia.base.org / mainnet.base.org return 403 to a bare
# client while publicnode works. Env overrides prepend to the list.
DEFAULT_RPC: dict[int, tuple[str, ...]] = {
    CHAIN_ID_BASE_SEPOLIA: ("https://base-sepolia-rpc.publicnode.com", "https://sepolia.base.org"),
    CHAIN_ID_BASE_MAINNET: ("https://base-rpc.publicnode.com", "https://mainnet.base.org", "https://base.drpc.org"),
}

X402_SDK_REF = "git+https://github.com/x402-foundation/x402@e398a9e#subdirectory=python/x402"

# Base Spend Permissions -- Coinbase's primary repo, README.md "Deployments" section:
# https://github.com/coinbase/spend-permissions (pinned at commit e0004e6, 2026-09-12)
# Same address on every deployed chain (Base, Base Sepolia, and others) -- a
# deterministic (CREATE2-style) deployment, per the README's address table.
# On-chain (tests/test_payments_constants.py): SPEND_PERMISSION_TYPEHASH() ==
# keccak256(SPEND_PERMISSION_TYPE_STRING), recomputed independently, not hardcoded.
SPEND_PERMISSION_MANAGER = "0xf85210B21cC50302F477BA56686d2019dC9b67Ad"

# The exact EIP-712 struct signature src/SpendPermissionManager.sol keccak256's to
# get SPEND_PERMISSION_TYPEHASH, quoted verbatim from the pinned commit above.
SPEND_PERMISSION_TYPE_STRING = (
    "SpendPermission(address account,address spender,address token,"
    "uint160 allowance,uint48 period,uint48 start,uint48 end,uint256 salt,"
    "bytes extraData)"
)

# Coinbase Smart Wallet factory (v1.1) -- Coinbase's primary repo, README.md
# "Deployments" section: https://github.com/coinbase/smart-wallet (pinned at
# commit a4e83fd, 2026-09-13). "Deployed via Safe Singleton Factory, which today
# will give the same address across 248 chains" per the README -- unlike
# SPEND_PERMISSION_MANAGER this is quoted from the README only; the on-chain pin
# below (tests/test_smart_wallet_constants.py) is what actually earns the trust.
SMART_WALLET_FACTORY_V1_1 = "0xBA5ED110eFDBa3D005bfC882d75358ACBbB85842"

# The account implementation's own EIP-712 domain name/version, quoted verbatim
# from src/CoinbaseSmartWallet.sol's _domainNameAndVersion() override at the same
# pinned commit. Used by the on-chain pin to recompute domainSeparator()
# independently rather than hardcoding its hash.
SMART_WALLET_DOMAIN_NAME = "Coinbase Smart Wallet"
SMART_WALLET_DOMAIN_VERSION = "1"


def rpc_urls(chain_id: int) -> tuple[str, ...]:
    """RPC endpoints for a chain, env override first."""
    env = {
        CHAIN_ID_BASE_SEPOLIA: os.environ.get("BASE_SEPOLIA_RPC_URL"),
        CHAIN_ID_BASE_MAINNET: os.environ.get("BASE_MAINNET_RPC_URL"),
    }.get(chain_id)
    base = DEFAULT_RPC.get(chain_id, ())
    return (env, *base) if env else base
