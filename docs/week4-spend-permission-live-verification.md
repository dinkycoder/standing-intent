# Spend Permission Live Verification

PR #10 merged with one explicit, prominent gap: the spend path (as opposed to
signing/registration/revocation) was only verified by a correct pre-flight
revert, not a completed transfer — the test Smart Wallet had gas but no test
USDC. This closes that gap.

## What changed

`0x76F44Df1ef96909607680A8D0EdF5DC5bb45ED5C` (the Smart Wallet every Spend
Permission integration test provisions at nonce 0) was funded with 20 test
USDC on Base Sepolia via the Circle faucet (https://faucet.circle.com).

## Result

Full run, same day, against the funded wallet:

```
python -m pytest tests/test_payments_spend_permission.py \
  tests/test_payments_spend_permission_provisioning.py \
  tests/test_payments_spend_router.py -v -m integration
```

```
tests/test_payments_spend_permission.py::test_spend_within_cap_settles_on_chain PASSED
tests/test_payments_spend_permission.py::test_spend_above_cap_is_rejected_on_chain PASSED
tests/test_payments_spend_permission.py::test_revoked_permission_rejects_further_spend PASSED
tests/test_payments_spend_permission_provisioning.py::test_provision_is_idempotent_and_has_spend_permission_manager_as_owner PASSED
tests/test_payments_spend_permission_provisioning.py::test_sign_and_register_makes_the_permission_approved PASSED
tests/test_payments_spend_permission_provisioning.py::test_registering_a_revoked_permission_does_not_silently_succeed PASSED
tests/test_payments_spend_permission_provisioning.py::test_spend_within_cap_then_above_cap_then_revoke PASSED
tests/test_payments_spend_router.py::test_spend_and_route_pays_the_recipient_directly_not_our_wallet PASSED

8 passed in 54.54s
```

PR #8's original three headline assertions — spend within cap settles on
chain; spend above cap reverts with `ExceededSpendPermission`; a revoked
permission rejects further spend — all passed live, for real, along with
the full provisioning/signing/registration/router suite. Every Spend
Permission integration test in the repo now passes given a funded wallet;
none of this depended on a dry-run revert standing in for a real transfer.

## What this does not close

- The custodial-hop path is still gated Sepolia-only pending the
  money-transmission opinion `docs/PMF_AND_BUILD_PLAN.md`'s Caveats section
  calls for — this run does not touch that gate, it only proves the
  Sepolia-side mechanics are correct.
- The five residual, non-blocking findings from PR #10's fix-wave re-review
  (an inaccurate code comment, a loosely-scoped test assertion, a missing
  offline positive-case test, a pre-existing unmatched-error gap, a cosmetic
  inconsistency) are unaffected by this run and remain open follow-ups.
