from scripts.train_price_classifier import main


def test_main_trains_and_saves_a_classifier(tmp_path):
    artifact_path = tmp_path / "model.joblib"
    result = main(artifact_path=artifact_path)

    assert artifact_path.exists()
    assert result["n"] == 5000
    assert result["seed"] == 42
    # Verified during design at these exact values: accuracy ~0.654.
    assert result["accuracy"] > 0.60
