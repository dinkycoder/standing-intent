# Week 3 — mainnet gate

One real payment against a live Bazaar endpoint on Base mainnet, exercising the
permanent `payments/` module (not a throwaway script). Run once:

    Set-Item -Path Env:X402_WALLET_KEY -Value "0x..."   # mainnet-funded throwaway
    python -m pytest tests/test_payments_mainnet_gate.py -m manual -s

## Result

- **Date:** _pending_
- **Endpoint:** _pending_
- **Tx hash:** _pending_
- **Network:** eip155:8453
- **Amount:** _pending_ USDC
- **payer_paid_gas:** _pending_ (expected: false)
- **BaseScan:** _pending_
- **verify_settlement matches_expected:** _pending_

Once filled in, this file is the durable record; the test stays in the repo,
marked `manual`, for re-running.
