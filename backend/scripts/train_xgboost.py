"""
Retrains the crop recommendation XGBoost model on the Jharkhand dataset built by
augment_jharkhand_data.py (which grounds soil pH / N-P-K in real Soil Health
Card measurements - see build_soil_profiles.py), and saves it to
ml_models/crop-recommendation/XGBoost.pkl, matching the format the original
Crop-AI ml-server's xgboost_inference.py expects (joblib-dumped classifier,
label order = sorted crop names -> 0..21).

Pipeline order:
    1. python scripts/build_soil_profiles.py     (raw soil export -> village profiles)
    2. python scripts/augment_jharkhand_data.py  (village profiles -> training set)
    3. python scripts/train_xgboost.py           (this file)

The train/test split is stratified by crop and written out to
data/crop_recommendation_train.csv / _test.csv so the exact split used for the
reported accuracy can be inspected and re-run. The test set is held out
entirely - it is never seen during fitting.
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier

BASE_DIR = Path(__file__).parent
DATA_CSV = BASE_DIR / "data" / "crop_recommendation_jharkhand.csv"
TRAIN_CSV = BASE_DIR / "data" / "crop_recommendation_train.csv"
TEST_CSV = BASE_DIR / "data" / "crop_recommendation_test.csv"
MODEL_OUT = BASE_DIR.parent / "ml_models" / "crop-recommendation" / "XGBoost.pkl"
MAPPING_OUT = BASE_DIR.parent / "ml_models" / "crop-recommendation" / "label_mapping.json"
METRICS_OUT = BASE_DIR.parent / "ml_models" / "crop-recommendation" / "training_metrics.json"

FEATURES = ["N", "P", "K", "temperature", "humidity", "ph", "rainfall"]
TEST_SIZE = 0.20
SEED = 42


def main() -> None:
    df = pd.read_csv(DATA_CSV)
    print(f"Dataset: {len(df)} rows, {df['label'].nunique()} crops")

    encoder = LabelEncoder()
    y = encoder.fit_transform(df["label"])
    X = df[FEATURES]

    # Stratified so every crop keeps the same train/test proportion.
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=SEED, stratify=y
    )
    print(f"Split: {len(X_train)} train / {len(X_test)} test "
          f"({TEST_SIZE:.0%} held out, stratified by crop)")

    # Persist the exact split for inspection / reproducibility.
    TRAIN_CSV.parent.mkdir(parents=True, exist_ok=True)
    X_train.assign(label=encoder.inverse_transform(y_train)).to_csv(TRAIN_CSV, index=False)
    X_test.assign(label=encoder.inverse_transform(y_test)).to_csv(TEST_CSV, index=False)
    print(f"  wrote {TRAIN_CSV.name} and {TEST_CSV.name}")

    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="mlogloss",
        random_state=SEED,
    )

    # 5-fold CV on the training half only - catches overfitting that a single
    # held-out split can hide.
    cv = cross_val_score(model, X_train, y_train, cv=5, scoring="accuracy")
    print(f"\n5-fold CV on training set: {cv.mean():.4f} (+/- {cv.std():.4f})")

    model.fit(X_train, y_train)

    train_acc = accuracy_score(y_train, model.predict(X_train))
    preds = model.predict(X_test)
    test_acc = accuracy_score(y_test, preds)

    print(f"Train accuracy: {train_acc:.4f}")
    print(f"TEST accuracy (held-out, never seen during fitting): {test_acc:.4f}\n")
    print(classification_report(y_test, preds, target_names=encoder.classes_, digits=3))

    # Which crops does it actually confuse? Only report real confusions.
    cm = confusion_matrix(y_test, preds)
    confusions = [
        (encoder.classes_[i], encoder.classes_[j], int(cm[i, j]))
        for i in range(len(cm)) for j in range(len(cm))
        if i != j and cm[i, j] > 0
    ]
    if confusions:
        print("Misclassifications on the test set (actual -> predicted, count):")
        for actual, predicted, count in sorted(confusions, key=lambda c: -c[2]):
            print(f"  {actual} -> {predicted}: {count}")
    else:
        print("No misclassifications on the test set.")

    importances = sorted(
        zip(FEATURES, model.feature_importances_), key=lambda kv: -kv[1]
    )
    print("\nFeature importance:")
    for name, score in importances:
        print(f"  {name:<12} {score:.4f}")

    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_OUT)
    print(f"\nSaved model -> {MODEL_OUT}")

    mapping = {int(i): label for i, label in enumerate(encoder.classes_)}
    with open(MAPPING_OUT, "w") as f:
        json.dump(mapping, f, indent=2)
    print(f"Saved label mapping -> {MAPPING_OUT}")

    metrics = {
        "dataset_rows": int(len(df)),
        "n_crops": int(df["label"].nunique()),
        "train_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "test_size": TEST_SIZE,
        "cv_accuracy_mean": round(float(cv.mean()), 4),
        "cv_accuracy_std": round(float(cv.std()), 4),
        "train_accuracy": round(float(train_acc), 4),
        "test_accuracy": round(float(test_acc), 4),
        "feature_importance": {name: round(float(score), 4) for name, score in importances},
        "misclassifications": [
            {"actual": a, "predicted": p, "count": c} for a, p, c in confusions
        ],
    }
    with open(METRICS_OUT, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Saved metrics -> {METRICS_OUT}")


if __name__ == "__main__":
    main()
