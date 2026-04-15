from __future__ import annotations

import json

from sklearn.datasets import load_breast_cancer
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split

from model_factory import build_model, load_config


def main() -> None:
    config = load_config()
    dataset = load_breast_cancer()
    X_train, X_test, y_train, y_test = train_test_split(
        dataset.data,
        dataset.target,
        test_size=0.25,
        random_state=42,
        stratify=dataset.target,
    )

    model = build_model(config)
    model.fit(X_train, y_train)

    if hasattr(model, "predict_proba"):
        scores = model.predict_proba(X_test)[:, 1]
    else:
        scores = model.decision_function(X_test)

    predictions = model.predict(X_test)
    metrics = {
        "model": config.get("model"),
        "roc_auc": roc_auc_score(y_test, scores),
        "accuracy": accuracy_score(y_test, predictions),
    }
    print(json.dumps(metrics))


if __name__ == "__main__":
    main()
