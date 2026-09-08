# Week 3 — mainnet gate

One real payment against a live Bazaar endpoint on Base mainnet, exercising the
permanent `payments/` module (not a throwaway script). Run once:

    Set-Item -Path Env:X402_WALLET_KEY -Value "0x..."   # mainnet-funded throwaway
    python -m pytest tests/test_payments_mainnet_gate.py -m manual -s

## Result

- **Date:** 2026-09-08
- **Endpoint:** https://x402.ottoai.services/crypto-news
- **Tx hash:** `0xff7c3778bf149396b2ce678f7dbbaba9bd141e1b6d3732a73136aa43adcad002`
- **Network:** eip155:8453
- **Block:** 51060607
- **Amount:** 0.001 USDC
- **payer_paid_gas:** false — the transaction was submitted by the x402 facilitator
  relayer `0x625d8a65134079f8faAAc39a7947c73d93C6aC39`, not by the buyer
  (`0xA85F4a77714431c4583f8adD0BC6Bd90f6Ce2CB0`). The buyer's USDC moved via an
  EIP-3009 `transferWithAuthorization` signature; the buyer paid no gas and holds no ETH.
- **BaseScan:** https://basescan.org/tx/0xff7c3778bf149396b2ce678f7dbbaba9bd141e1b6d3732a73136aa43adcad002
- **verify_settlement matches_expected:** true (asserted by the test; receipt
  independently re-read at 50 confirmations — status 1, USDC contract
  `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`)

Run against `payments/` **after** the whole-branch fix wave (`I-2` changed the
`set_spend_controls` value); `tests/test_payments_integration.py` +
`tests/test_harness_real_x402.py` `-m integration` also pass on Base Sepolia.

This file is the durable record; the test stays in the repo, marked `manual`, for
re-running.
