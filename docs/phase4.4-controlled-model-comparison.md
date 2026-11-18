# Phase 4.4 — Controlled baseline versus tuned comparison

## Purpose and split discipline

Phase 4.4 retrains the four Phase 4.2 baseline classifiers using the same 21
approved input columns that Phase 4.2.1 used. It compares them with the saved
Phase 4.2.1 models on the original chronological validation partition
(February 12–20, 2024), at the fixed 0.5 threshold. All preprocessing is fitted
on the original training partition (January 1–February 11, 2024).

The runner calls the existing partition loader only for `train` and
`validation`. It never loads, predicts on, selects against, or otherwise uses
the final test rows (February 21–29). The combined Parquet checksum is used
only for input integrity. The runner records before/after hashes for the
Phase 4.2, 4.2.1 and 4.3 artifacts and fails if any protected artifact changes.

## Models and configurations

The baseline Logistic Regression is the balanced Phase 4.2 candidate used in
the Phase 4.2.1 family comparison. Decision Tree, Random Forest and XGBoost
use their fixed Phase 4.2 settings. Model fits run sequentially with one
worker. Phase 4.2 used external validation for XGBoost early stopping; Phase
4.4 disables early stopping and retains its fixed 250 estimators so that the
validation partition remains an evaluation set for this comparison. This
adjustment is explicitly recorded in the report.

Phase 4.2.1 model configurations are read from its saved `best_configurations`
artifact. They are not refit or changed. Its already computed validation
metrics are reused at threshold 0.5. Both model families use one-hot encoding
for the three categorical columns and scale the nine numeric columns plus the
nine existing missingness indicators. The feature names are checked against
the exact Phase 4.1.6 allowlist; no feature engineering is added.

For each model and each version, the report contains accuracy, precision,
recall, F1, F2, ROC-AUC, average precision, balanced accuracy, confusion
matrix, false-positive rate among actual non-delayed flights, false-positive
alerts per 100 validation flights, and overall alert rate. Deltas are tuned
minus baseline. No threshold search or cross-validation is performed.

## Checkpointing and resource limits

The experiment writes to the ignored directory
`data/processed/ml/phase4_4/`. It refuses to overwrite a non-empty directory.
After each sequential baseline fit, the estimator, validation probabilities,
metrics, and checksums are persisted before the next fit starts. A run with a
matching fingerprint can resume completed model checkpoints; mismatched or
corrupt checkpoints fail closed. Phase 4.2 and 4.2.1 model artifacts are
read-only inputs.

## Outputs

- `phase4_4_comparison.json`: configurations, feature contract, split counts,
  metrics, deltas, resource measurements, package versions and integrity
  hashes.
- `confusion_matrices.csv` and `confusion_matrices.png`: baseline and tuned
  confusion matrices for all four families.
- `baseline_<family>.joblib`: newly retrained baseline classifiers.
- `baseline_<family>_validation_metrics.json` and
  `baseline_<family>_validation_probabilities.npy`: durable per-model
  checkpoints.
- `run_state.json`: run fingerprint and checkpoint status.

Run from the project root with:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ml.compare_phase4_4
```

Measured model metrics, total runtime and peak working set are recorded in
`phase4_4_comparison.json` and summarized in the completion report.

## Measured validation results

The validation partition contains 159,176 flights (26,526 delayed). Each cell
below is measured at the fixed 0.5 threshold; confusion matrices use
`TN / FP / FN / TP`. FPR is false positives divided by actual non-delayed
flights; FP/100 is false-positive alerts per 100 validation flights.

| Model | Version | Accuracy | Precision | Recall | F1 | F2 | ROC-AUC | AP | Balanced accuracy | FPR | FP/100 | TN / FP / FN / TP |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Logistic Regression | Baseline | 0.804399 | 0.279916 | 0.110495 | 0.158445 | 0.125713 | 0.615435 | 0.234569 | 0.526827 | 0.056841 | 4.736895 | 125110 / 7540 / 23595 / 2931 |
| Logistic Regression | Tuned | 0.822693 | 0.292998 | 0.045276 | 0.078433 | 0.054490 | 0.602951 | 0.223523 | 0.511715 | 0.021847 | 1.820626 | 129752 / 2898 / 25325 / 1201 |
| Decision Tree | Baseline | 0.820029 | 0.170754 | 0.020734 | 0.036979 | 0.025154 | 0.600973 | 0.214822 | 0.500299 | 0.020136 | 1.678017 | 129979 / 2671 / 25976 / 550 |
| Decision Tree | Tuned | 0.818861 | 0.197799 | 0.028463 | 0.049764 | 0.034343 | 0.598120 | 0.215259 | 0.502690 | 0.023083 | 1.923657 | 129588 / 3062 / 25771 / 755 |
| Random Forest | Baseline | 0.833354 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.617344 | 0.237626 | 0.500000 | 0.000000 | 0.000000 | 132650 / 0 / 26526 / 0 |
| Random Forest | Tuned | 0.671276 | 0.236621 | 0.436892 | 0.306981 | 0.373643 | 0.614909 | 0.234503 | 0.577519 | 0.281855 | 23.488466 | 95262 / 37388 / 14937 / 11589 |
| XGBoost | Baseline | 0.826877 | 0.242893 | 0.018359 | 0.034138 | 0.022524 | 0.605700 | 0.214608 | 0.503458 | 0.011444 | 0.953661 | 131132 / 1518 / 26039 / 487 |
| XGBoost | Tuned | 0.614194 | 0.207070 | 0.464827 | 0.286508 | 0.372172 | 0.587408 | 0.207259 | 0.554445 | 0.355937 | 29.662135 | 85435 / 47215 / 14196 / 12330 |

The tuned Decision Tree has small measured gains in AP (+0.000437), F1
(+0.012786) and F2 (+0.009188), alongside a lower ROC-AUC. Tuned Logistic
Regression increases precision but decreases recall, F1, F2 and AP. Tuned
Random Forest and XGBoost recover many more delayed flights at 0.5, with
substantially higher false-positive alert rates and lower accuracy. AP is
slightly lower for both than their re-trained baselines. These are validation
observations, not evidence of generalization or production readiness.

Measured baseline fit time was 57.63 seconds for Logistic Regression, 22.85
seconds for Decision Tree, 63.98 seconds for Random Forest, and 17.85 seconds
for XGBoost (162.31 seconds total). The completed report packaging invocation
took 4.49 seconds after resuming these fit checkpoints. During the original
fit process, the largest externally sampled working set was 484,552,704 bytes
(462.17 MiB); this was a periodic process sample, not a continuously captured
OS peak counter. The run manifest's Windows peak-counter field is null because
the API did not return a value in the initial invocation.

Focused Phase 4.4 tests: 2 passed. The full project suite was not run.
