"""Trained accept/reject/escalate price classifier.

See docs/superpowers/specs/2026-09-19-week7-trained-model-design.md.
"""

from __future__ import annotations

from pathlib import Path

import joblib
from sklearn.linear_model import LogisticRegression

FEATURE_NAMES = [
    "price_zscore_in_category", "reference_price_ratio",
    "reference_price_missing", "budget_utilization",
]
DEFAULT_ARTIFACT_PATH = Path(__file__).parent / "price_classifier.joblib"


def _vectorize(features: dict) -> list[float]:
    return [
        float(features["price_zscore_in_category"]),
        float(features["reference_price_ratio"]),
        1.0 if features["reference_price_missing"] else 0.0,
        float(features["budget_utilization"]),
    ]


class TrainedClassifier:
    def __init__(self, model: LogisticRegression):
        self._model = model

    def predict_proba(self, features: dict) -> dict[str, float]:
        x = [_vectorize(features)]
        proba = self._model.predict_proba(x)[0]
        # str(c): classes_ entries are numpy.str_, not plain str -- cast so
        # the returned dict's keys have a predictable, plain-Python type.
        return dict(zip((str(c) for c in self._model.classes_), (float(p) for p in proba)))

    def save(self, path: Path = DEFAULT_ARTIFACT_PATH) -> None:
        joblib.dump(self._model, path)


def train(features: list[dict], labels: list[str], seed: int) -> TrainedClassifier:
    x = [_vectorize(f) for f in features]
    model = LogisticRegression(max_iter=1000, random_state=seed)
    model.fit(x, labels)
    return TrainedClassifier(model)


def load(path: Path = DEFAULT_ARTIFACT_PATH) -> TrainedClassifier:
    model = joblib.load(path)
    return TrainedClassifier(model)
