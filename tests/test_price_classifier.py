from collections import Counter

from sklearn.model_selection import train_test_split

from evals.ml.price_classifier import _vectorize, load, train
from evals.ml.synthetic_data import generate_offers


def test_train_produces_a_classifier_with_predict_proba():
    features = [
        {"price_zscore_in_category": -2.0, "reference_price_ratio": 1.0,
         "reference_price_missing": False, "budget_utilization": 0.1},
        {"price_zscore_in_category": -1.8, "reference_price_ratio": 0.9,
         "reference_price_missing": False, "budget_utilization": 0.2},
        {"price_zscore_in_category": 3.0, "reference_price_ratio": 3.0,
         "reference_price_missing": False, "budget_utilization": 0.9},
        {"price_zscore_in_category": 3.2, "reference_price_ratio": 3.5,
         "reference_price_missing": True, "budget_utilization": 0.95},
    ]
    labels = ["accept", "accept", "reject", "reject"]

    clf = train(features, labels, seed=0)
    low_z_proba = clf.predict_proba(features[0])
    high_z_proba = clf.predict_proba(features[2])

    assert set(low_z_proba) == {"accept", "reject"}
    assert abs(sum(low_z_proba.values()) - 1.0) < 1e-9
    assert low_z_proba["accept"] > high_z_proba["accept"]


def test_predict_proba_output_sums_to_one_for_three_classes():
    features = [
        {"price_zscore_in_category": z, "reference_price_ratio": 1.0,
         "reference_price_missing": False, "budget_utilization": 0.3}
        for z in (-2.0, -1.0, 0.0, 1.0, 2.0, 2.5, 3.0, 3.5)
    ]
    labels = ["accept", "accept", "accept", "escalate", "escalate", "escalate", "reject", "reject"]

    clf = train(features, labels, seed=0)
    proba = clf.predict_proba(features[0])
    assert set(proba) == {"accept", "escalate", "reject"}
    assert abs(sum(proba.values()) - 1.0) < 1e-9


def test_vectorize_encodes_reference_price_missing_as_the_third_position():
    with_ref = {"price_zscore_in_category": 0.0, "reference_price_ratio": 1.0,
                "reference_price_missing": False, "budget_utilization": 0.5}
    without_ref = {**with_ref, "reference_price_missing": True}
    assert _vectorize(with_ref)[2] == 0.0
    assert _vectorize(without_ref)[2] == 1.0


def test_save_and_load_round_trip(tmp_path):
    features = [
        {"price_zscore_in_category": -2.0, "reference_price_ratio": 1.0,
         "reference_price_missing": False, "budget_utilization": 0.1},
        {"price_zscore_in_category": 3.0, "reference_price_ratio": 3.0,
         "reference_price_missing": False, "budget_utilization": 0.9},
    ]
    labels = ["accept", "reject"]
    clf = train(features, labels, seed=0)
    path = tmp_path / "model.joblib"
    clf.save(path)

    loaded = load(path)
    assert loaded.predict_proba(features[0]) == clf.predict_proba(features[0])


def test_committed_artifact_loads_and_predicts_sensibly():
    clf = load()  # DEFAULT_ARTIFACT_PATH -- the real, committed file
    base = {"reference_price_ratio": 1.0, "reference_price_missing": False,
            "budget_utilization": 0.3}
    cheap = clf.predict_proba({**base, "price_zscore_in_category": -2.0})
    dear = clf.predict_proba({**base, "price_zscore_in_category": 3.0})
    assert set(cheap) == {"accept", "escalate", "reject"}
    assert abs(sum(cheap.values()) - 1.0) < 1e-9
    assert cheap["accept"] > dear["accept"]
    assert dear["reject"] > cheap["reject"]


def test_full_train_test_run_beats_the_majority_class_baseline():
    features, labels = generate_offers(n=5000, seed=42)
    x_train, x_test, y_train, y_test = train_test_split(
        features, labels, test_size=0.2, random_state=42, stratify=labels
    )
    clf = train(x_train, y_train, seed=42)

    correct = sum(
        1 for f, y in zip(x_test, y_test)
        if max((p := clf.predict_proba(f)), key=p.get) == y
    )
    accuracy = correct / len(y_test)
    majority_class = Counter(y_train).most_common(1)[0][0]
    baseline_accuracy = sum(1 for y in y_test if y == majority_class) / len(y_test)

    # Verified during design at these exact seeds: accuracy ~0.654,
    # baseline ~0.571. Both floors have margin below the observed values.
    assert accuracy > 0.60
    assert accuracy > baseline_accuracy + 0.05
