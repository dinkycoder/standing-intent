import pytest

from evals.stats import pass_k_interval, wilson_interval


# ---- wilson_interval -------------------------------------------------

def test_wilson_interval_matches_hand_computed_value():
    # successes=5, n=20 (p_hat=0.25). Computed from the closed-form Wilson
    # score formula directly, not quoted from memory (CLAUDE.md rule 2's
    # spirit applies to constants in tests too).
    lo, hi = wilson_interval(5, 20)
    assert lo == pytest.approx(0.11186, abs=1e-5)
    assert hi == pytest.approx(0.46871, abs=1e-5)


def test_wilson_interval_stays_within_unit_interval_at_extremes():
    lo, hi = wilson_interval(0, 8)
    assert lo == 0.0
    assert 0.0 < hi < 1.0  # not zero-width, unlike the naive Wald interval

    lo, hi = wilson_interval(8, 8)
    assert hi == 1.0
    assert 0.0 < lo < 1.0


def test_wilson_interval_widens_as_n_shrinks():
    # Same p_hat (3/8 == 30/80 == 0.375), 10x less data at n=8.
    narrow_lo, narrow_hi = wilson_interval(30, 80)
    wide_lo, wide_hi = wilson_interval(3, 8)
    assert (wide_hi - wide_lo) > (narrow_hi - narrow_lo)


def test_wilson_interval_rejects_bad_input():
    with pytest.raises(ValueError):
        wilson_interval(1, 0)
    with pytest.raises(ValueError):
        wilson_interval(9, 8)


# ---- pass_k_interval ---------------------------------------------------

def test_pass_k_interval_at_k_1_equals_wilson_interval():
    assert pass_k_interval(6, 8, 1) == wilson_interval(6, 8)


def test_pass_k_interval_is_wilson_bounds_raised_to_k():
    lo, hi = wilson_interval(6, 8)
    assert pass_k_interval(6, 8, 4) == pytest.approx((lo**4, hi**4))


def test_pass_k_interval_bounds_shrink_as_k_grows():
    # Both Wilson bounds are < 1 here, so raising them to a higher power must
    # pull both ends down -- a sign/exponent error would show up as this
    # failing to hold or as bounds moving the wrong way.
    lo1, hi1 = pass_k_interval(6, 8, 1)
    lo4, hi4 = pass_k_interval(6, 8, 4)
    assert lo4 < lo1
    assert hi4 < hi1
