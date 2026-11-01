# Phase 4.2 — Delay model training and evaluation

This phase trains four baseline model families on the verified January and
February 2024 feature dataset. It uses fixed chronological partitions, selects
the candidate using validation data only, and evaluates the selected candidate
on the test partition once. It does not train Isolation Forest or implement
model serving.

## Dataset and feature contract

Input: `data/processed/ml/flight_delay_features_2024_01_02.parquet`, verified
against `feature_manifest_2024_01_02.json` and its SHA-256 before training.
The source contains 1,040,639 eligible flights and 24 columns: 21 allowlisted
features, the target, `flight_date`, and `split`.

The target is `target_arr_delay_gt_15`: 1 when `ArrDelay > 15` minutes and 0
otherwise. Delayed flights are the positive class.

The model input is checked against the exact Phase 4.1.6 allowlist:

- Categorical: `Reporting_Airline`, `Origin`, `Dest`.
- Numeric: `month`, `day_of_month`, `day_of_week`,
  `scheduled_departure_sin`, `scheduled_departure_cos`,
  `scheduled_arrival_sin`, `scheduled_arrival_cos`,
  `scheduled_elapsed_time_minutes`, `distance_miles`.
- The nine existing `is_missing_<numeric feature>` indicators.

The target, `flight_date`, `split`, arrival/departure actuals, flight-progress
fields, cancellation/diversion outcomes, and delay causes cannot enter the
model matrix. Any missing, extra, or reordered feature column fails validation.

| Partition | Dates | Rows | Delayed | Non-delayed | Delayed prevalence |
|---|---|---:|---:|---:|---:|
| Train | Jan 1–Feb 11 | 716,676 | 150,800 | 565,876 | 21.04% |
| Validation | Feb 12–20 | 159,176 | 26,526 | 132,650 | 16.66% |
| Test | Feb 21–29 | 164,787 | 23,971 | 140,816 | 14.55% |

This is January–February 2024 only. Its changing positive prevalence and short
date range mean it does not demonstrate generalization across seasons, years,
or operating regimes.

## Preprocessing and leakage controls

The feature Parquet already contains range-checked numeric features, missing
indicators, and median-imputed values. Those medians were fitted on the
716,676-row training partition and are verified from the dataset manifest.
No new imputation is fitted in Phase 4.2.

A scikit-learn `ColumnTransformer` is fitted once using training rows only:

- `OneHotEncoder(handle_unknown="ignore", sparse_output=True)` for the three
  categorical features.
- `StandardScaler(with_mean=False)` for numeric features, preserving sparse
  output and fitting scale parameters only on training rows.

Validation and test are transformed with this fitted preprocessor. The
training matrix is CSR sparse with shape 716,676 × 692 and 8,495,490 nonzero
values. The test target is not used for preprocessing, tuning, selection, or
early stopping.

## Model configurations

All model random seeds are 42; parallel model execution is limited to two
workers.

| Model candidate | Configuration |
|---|---|
| Logistic Regression, unweighted | SAGA, `max_iter=1000`, `tol=0.001`, no class weights |
| Logistic Regression, balanced | SAGA, `max_iter=1000`, `tol=0.001`, `class_weight="balanced"` |
| Decision Tree | `max_depth=16`, `min_samples_leaf=200`, `min_samples_split=400` |
| Random Forest | 100 trees, `max_depth=16`, `min_samples_leaf=200`, `min_samples_split=400`, `max_features="sqrt"`, `n_jobs=2` |
| XGBoost | CPU histogram tree method, 250 estimators, depth 6, learning rate 0.1, row/column subsampling 0.8, `max_bin=128`, PR-AUC early stopping after 25 rounds, `n_jobs=2` |

The two Logistic Regression configurations assess class weighting without
assuming it is beneficial. XGBoost used the validation partition for
early-stopping evaluation; its best iteration was 1.

## Validation comparison and selection

All metrics use threshold 0.5 for hard classifications. ROC-AUC and PR-AUC
(average precision) use predicted scores. The predefined selection rule was
the highest validation F2, then higher PR-AUC, recall, and precision as
tie-breakers. F2 weights delayed-flight recall more strongly than precision.
No test metric participates in this selection.

| Validation candidate | Accuracy | Precision | Recall | F1 | F2 | ROC-AUC | PR-AUC | Balanced accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Logistic Regression, unweighted | 0.8334 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.6160 | 0.2356 | 0.5000 |
| Logistic Regression, balanced | 0.8044 | 0.2799 | 0.1105 | 0.1584 | **0.1257** | 0.6154 | 0.2346 | 0.5268 |
| Decision Tree | 0.8200 | 0.1708 | 0.0207 | 0.0370 | 0.0252 | 0.6010 | 0.2146 | 0.5003 |
| Random Forest | 0.8334 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.6137 | 0.2327 | 0.5000 |
| XGBoost | 0.8334 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.6059 | 0.2300 | 0.5000 |

The selected candidate is **balanced Logistic Regression**. On validation, it
detected 2,931 of 26,526 delayed flights, missed 23,595, and incorrectly
flagged 7,540 non-delayed flights (true negatives: 125,110). The unweighted
Logistic Regression, Random Forest, and XGBoost all predicted no positives at
the fixed 0.5 threshold. Accuracy alone would obscure this failure because
non-delayed flights are the majority class.

## One-time final test result

After selection, the selected candidate was evaluated once on the untouched
164,787-row test partition:

| Metric | Final test |
|---|---:|
| Accuracy | 0.8380 |
| Precision | 0.2548 |
| Recall | 0.0590 |
| F1 | 0.0959 |
| F2 | 0.0697 |
| ROC-AUC | 0.6216 |
| PR-AUC (average precision) | 0.2078 |
| Balanced accuracy | 0.5148 |
| Positive prevalence | 14.55% |

Confusion matrix (rows are actual; columns are predicted):

|  | Predicted non-delayed | Predicted delayed |
|---|---:|---:|
| Actual non-delayed | 136,677 | 4,139 |
| Actual delayed | 22,556 | 1,415 |

The result is a weak baseline, not an operationally useful delay detector:
recall is low, so 22,556 delayed flights were missed. The 25.48% precision
means roughly three quarters of its delay alerts were false positives.
Thresholds or model configurations must not be changed based on this test
result. Any subsequent tuning requires a new validation period and a later
untouched test dataset.

## Interpretability and limitations

`feature_importance.csv` stores signed coefficients for both Logistic
Regression candidates and impurity-based importance for the tree models, all
using transformed feature names. Logistic coefficients describe fitted
associations conditional on this encoding; tree impurity scores can favor
high-cardinality or correlated features. Neither is evidence of causation.

The test period immediately follows the training and validation windows, and
all data are from two months in one year. Delayed-flight prevalence fell from
21.04% in training to 14.55% in testing. This is a material distribution
change and limits the interpretation of the comparison. More BTS months,
operational threshold requirements, and a later-period final test are needed
before claiming generalization or using these models for flight operations.

## Artifacts, environment, and reproduction

Generated files are Git-ignored under `data/processed/ml/phase4_2/`:

- `logistic_regression.joblib`, `decision_tree.joblib`,
  `random_forest.joblib`, `xgboost.joblib`: inference pipelines that include
  the fitted preprocessor and classifier. The Logistic Regression artifact
  uses the validation-selected balanced configuration.
- `preprocessor.joblib`: shared fitted `ColumnTransformer`.
- `validation_metrics.json`, `final_test_metrics.json`,
  `experiment_manifest.json`.
- Validation ROC/precision-recall plots; selected validation and test
  confusion matrices; selected test ROC/precision-recall plot.
- `feature_importance.csv`.

The experiment manifest records the input SHA-256, feature contract,
preprocessing metadata, model parameters and random seed, package versions,
validation/test metrics, runtime, and artifact names. The verified input
feature dataset, January-only ML outputs, and Phase 3.2 analytics are not
modified.

Install the declared requirements and run from the repository root in
PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pipelines.ml.train_models
```

The command refuses to overwrite a populated `phase4_2` directory. To retain
existing artifacts and run another experiment, provide a new output path:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ml.train_models --output-dir data/processed/ml/phase4_2_repeat
```

The measured full run completed in 261 seconds. A two-second process sample
observed a peak working set of about 556 MiB and peak private bytes of about
1,321 MiB; no memory exhaustion was observed. Installed versions were Python
3.11.0, scikit-learn 1.9.1, XGBoost 3.2.0, SciPy 1.17.1, and NumPy 2.4.6.
