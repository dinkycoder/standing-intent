from collections import Counter

from evals.ml.synthetic_data import _CATEGORY_PRICE_PARAMS, _LABELS, generate_offers


def test_generate_offers_returns_matching_lengths():
    features, labels = generate_offers(n=100, seed=1)
    assert len(features) == 100
    assert len(labels) == 100


def test_generate_offers_zscores_are_approximately_standard_normal_per_category():
    features, _ = generate_offers(n=20000, seed=1)
    for category in _CATEGORY_PRICE_PARAMS:
        zs = [f["price_zscore_in_category"] for f in features if f["category"] == category]
        assert len(zs) > 1000  # sanity: each category got a meaningful sample
        mean_z = sum(zs) / len(zs)
        std_z = (sum((z - mean_z) ** 2 for z in zs) / len(zs)) ** 0.5
        assert abs(mean_z) < 0.05
        assert abs(std_z - 1.0) < 0.05


def test_generate_offers_labels_are_one_of_the_three_classes():
    _, labels = generate_offers(n=500, seed=1)
    assert set(labels) <= set(_LABELS)
    assert "accept" in labels


def test_generate_offers_high_zscore_offers_skew_toward_reject():
    features, labels = generate_offers(n=20000, seed=1)
    high_z_labels = [
        label for f, label in zip(features, labels)
        if f["price_zscore_in_category"] > 2.5
    ]
    assert len(high_z_labels) > 50  # sanity: enough high-z samples exist
    reject_rate = high_z_labels.count("reject") / len(high_z_labels)
    assert reject_rate > 0.6


def test_generate_offers_reference_price_missing_flag_is_consistent():
    features, _ = generate_offers(n=2000, seed=1)
    for f in features:
        if f["reference_price_missing"]:
            assert f["reference_price_ratio"] == 1.0


def test_generate_offers_label_distribution_is_not_degenerate():
    # Guards against the exact "one class dominates so hard a trained
    # model can't beat guessing it" failure mode found during design --
    # every class must have a real, non-trivial share.
    _, labels = generate_offers(n=20000, seed=1)
    counts = Counter(labels)
    for label in _LABELS:
        assert counts[label] / len(labels) > 0.05


def test_generate_offers_is_reproducible_with_the_same_seed():
    f1, l1 = generate_offers(n=50, seed=7)
    f2, l2 = generate_offers(n=50, seed=7)
    assert f1 == f2
    assert l1 == l2
