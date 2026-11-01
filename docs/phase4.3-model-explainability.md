# Phase 4.3 — Model explainability and validation error analysis

## Scope and safeguards

This study reuses the saved Phase 4.2 pipelines and analyzes the validation
partition only (159,176 flights, February 12–20, 2024). It does not read or
score test rows, tune from test metrics, retrain the Phase 4.2 candidate
pipelines, change their metrics, or modify the source feature dataset. SHA-256
snapshots of every Phase 4.2 artifact, including the previously recorded test
metrics, are checked before and after the analysis. The test metrics were
hashed for preservation only; they were not opened for analysis.

The analysis checks the combined-data manifest and checksum, the 21-feature
allowlist, the target definition, date boundaries, date-grouped split
guarantee, and training-only upstream imputation metadata. It reads only
validation features for the main comparisons. The calibration experiment
reads training rows only and uses disjoint chronological windows:

- Base pipeline fit: January 1–21 (354,632 flights).
- Sigmoid calibrator fit: January 22–February 11 (362,044 flights).
- Numeric medians for this experiment are re-fitted from observed values in
  the base-fit window only; the persisted missingness indicators identify
  values to re-impute in the calibration and validation windows.
- Calibration results are assessed on the validation partition only.

No values below imply causal effects. Airport, airline, schedule, and distance
comparisons are retrospective associations in this two-month sample.

## Feature contract

The exact model-input allowlist has 21 features:

| Type | Features |
|---|---|
| Categorical (3) | `Reporting_Airline`, `Origin`, `Dest` |
| Numeric (9) | `month`, `day_of_month`, `day_of_week`, `scheduled_departure_sin`, `scheduled_departure_cos`, `scheduled_arrival_sin`, `scheduled_arrival_cos`, `scheduled_elapsed_time_minutes`, `distance_miles` |
| Missingness indicators (9) | `is_missing_month`, `is_missing_day_of_month`, `is_missing_day_of_week`, `is_missing_scheduled_departure_sin`, `is_missing_scheduled_departure_cos`, `is_missing_scheduled_arrival_sin`, `is_missing_scheduled_arrival_cos`, `is_missing_scheduled_elapsed_time_minutes`, `is_missing_distance_miles` |

Target: `target_arr_delay_gt_15` (1 when `ArrDelay > 15` minutes; delayed is
the positive class). `flight_date` and `split` are metadata, not features.
Actual arrival/departure outcomes, flight-progress values,
cancellation/diversion outcomes, and delay causes are excluded by requiring
the exact allowlist. The saved model preprocessing expands the 21 inputs to
one-hot and scaled transformed columns; categorical transformed names are
aggregated back to their source field for global summaries.

## Artifacts and model availability

The four persisted Phase 4.2 pipelines are:

- `logistic_regression.joblib` (the validation-selected balanced configuration)
- `decision_tree.joblib`
- `random_forest.joblib`
- `xgboost.joblib`

Phase 4.2 also trained an unweighted Logistic Regression candidate, but did
not save a separate pipeline. Its saved transformed coefficients in
`phase4_2/feature_importance.csv` are reused for the coefficient and global
importance summaries; no new model was fitted for that candidate.

All generated Phase 4.3 files are under the Git-ignored
`data/processed/ml/phase4_3/` directory. `analysis_manifest.json` records the
input checksum, feature and target contract, partition boundaries, saved
model names/configuration, calibration metadata, validation-only/test-set
protection flags, before/after Phase 4.2 artifact hashes, and the SHA-256 and
byte size of each generated artifact (excluding the manifest itself).

## Global explainability

### Logistic Regression

The selected balanced candidate has the following largest signed coefficients
in its transformed input space:

| Direction | Transformed feature | Coefficient |
|---|---|---:|
| Positive | `Dest_HNL` | +1.5025 |
| Positive | `Reporting_Airline_HA` | +1.3522 |
| Positive | `Reporting_Airline_AS` | +1.3398 |
| Positive | `Origin_IAG` | +1.2791 |
| Positive | `Reporting_Airline_OH` | +1.2062 |
| Negative | `Origin_GUM` | −4.0072 |
| Negative | `Origin_SPN` | −2.5631 |
| Negative | `Origin_ITO` | −1.7719 |
| Negative | `Origin_OTZ` | −1.5362 |
| Negative | `Origin_CYS` | −1.5207 |

The unweighted candidate’s largest positive coefficients were `Dest_HNL`
(+1.4205), `Origin_IAG` (+1.2281), and `Origin_CIU` (+1.0662); its largest
negative coefficients were `Origin_GUM` (−3.8921), `Origin_SPN` (−2.3846),
and `Origin_ITO` (−1.7854).

These are fitted associations, not causal effects. Numeric coefficients are
on the fitted scaled representation; categorical coefficients correspond to
one-hot columns. Airport/airline coefficients can also be sensitive to
category frequency and regularization. The global summaries aggregate
absolute coefficient magnitudes by source field, which is not comparable as
an absolute scale across model families.

### Tree models

The Decision Tree has depth 16, 2,985 nodes, and 1,493 leaves
(`min_samples_leaf=200`). Its largest normalized impurity importances by
source feature are `day_of_month` (0.334), `day_of_week` (0.163),
`Reporting_Airline` (0.105), `Origin` (0.092), and
`scheduled_departure_sin` (0.083). The exported decision paths are limited to
depth four for readability; the complexity metadata reflects the full fitted
tree.

Random Forest’s largest normalized impurity importances are `day_of_month`
(0.188), `Reporting_Airline` (0.129), `month` (0.119),
`scheduled_departure_sin` (0.115), and `Origin` (0.098). On validation,
three-repeat permutation importance by average-precision decrease ranks
`Reporting_Airline` (+0.01245), `Dest` (+0.01021),
`scheduled_departure_sin` (+0.00905), `scheduled_arrival_cos` (+0.00821),
and `Origin` (+0.00721) highest. These results are model- and
distribution-dependent; correlated features can share or mask importance.
Impurity importance can favor features with many possible split points, so
the permutation ranking is the preferred validation-based RF comparison.

XGBoost source-level gain from its effective best iteration ranks `month`
(0.324 normalized), `Origin` (0.171), `Reporting_Airline` (0.164), `Dest`
(0.093), and `scheduled_arrival_cos` (0.086) highest. The reported gain,
tree impurity, permutation decrease, and coefficient magnitudes have
different definitions and must not be interpreted as a common causal scale.

## Validation performance and errors

Validation prevalence is 26,526 / 159,176 = **16.66% delayed**. The selected
balanced Logistic Regression at the original 0.5 threshold produced:

| Actual / predicted | Predicted non-delayed | Predicted delayed |
|---|---:|---:|
| Non-delayed | 125,110 | 7,540 |
| Delayed | 23,595 | 2,931 |

It flags 10,471 flights, detects 11.05% of delayed flights, and misses 23,595
(88.95%) delayed flights. Precision is 27.99%, F1 0.1584, and validation
average precision is 0.2346. Average precision is above the 0.1666 positive
prevalence baseline, but the improvement is modest. The delayed and
non-delayed score distributions overlap substantially: their medians are
0.3755 and 0.3283, respectively.

The unweighted Logistic Regression, Random Forest, and XGBoost candidates
predict no positives at threshold 0.5, yielding 83.34% accuracy from the
majority non-delayed class but zero delayed-flight recall. The Decision Tree
has 2.07% recall and 82.00% accuracy. The selected balanced Logistic
Regression improves recall over those no-positive candidates, but remains a
weak detector. This is a verified class-imbalance/threshold result; it is not
evidence that accuracy alone measures operational value.

### Group patterns

All group metrics are saved in
`selected_validation_group_performance.csv`. The minimum reporting size is
500 flights per group; undersized groups are excluded, with omission counts
recorded in the manifest. The table contains number of flights, actual and
predicted delayed rates, precision, recall, F1, and confusion components for
airline, origin, destination, scheduled departure band, weekday, and distance
band.

Examples at the 0.5 threshold:

- Airline recall varies widely: AA has 23,111 flights, 17.87% actual delayed
  rate, and 25.86% recall; DL has 21,821 flights, 13.03% actual delayed rate,
  and 1.13% recall. For DL, predicted delayed rate is only 0.30%.
- Destination SFO has 2,967 flights, 43.85% actual delayed rate, and 35.05%
  recall. Destination groups ABQ (505 flights) and BUR (639) have zero recall.
- Wednesday’s actual delayed rate is 8.95% and recall 15.22%; Saturday’s
  delayed rate is 28.96%. Weekday outcomes do not align monotonically with
  recall.
- Departure-time recall ranges from 1.07% for 00:00–05:59 (4,502 flights) to
  16.07% for 12:00–17:59 (57,803 flights). The 18:00–23:59 band has a 20.94%
  actual delayed rate and 14.67% recall.
- The 751+ mile band has a 18.98% delayed rate and 13.41% recall; the
  251–750 mile band has 7.90% recall.

These are descriptive validation associations. They do not establish that an
airline, airport, weekday, schedule band, or distance causes delay or
prediction errors.

## Validation thresholds

Thresholds were evaluated on validation only; the complete table is in
`selected_validation_thresholds.csv`. Changes are relative to the original
0.5 threshold:

| Threshold | Precision | Recall | F1 | F2 | True positives | False positives | Additional delayed detected | Additional false positives |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.10 | 0.1667 | 0.9996 | 0.2858 | 0.5000 | 26,516 | 132,529 | 23,585 | 124,989 |
| 0.15 | 0.1679 | 0.9931 | 0.2872 | 0.5008 | 26,344 | 130,579 | 23,413 | 123,039 |
| 0.20 | 0.1729 | 0.9588 | 0.2930 | **0.5022** | 25,433 | 121,671 | 22,502 | 114,131 |
| 0.25 | 0.1836 | 0.8812 | 0.3039 | 0.5007 | 23,374 | 103,927 | 20,443 | 96,387 |
| 0.30 | 0.1995 | 0.7567 | **0.3158** | 0.4855 | 20,072 | 80,530 | 17,141 | 72,990 |
| 0.40 | 0.2421 | 0.4146 | 0.3057 | 0.3629 | 10,998 | 34,432 | 8,067 | 26,892 |
| 0.50 | 0.2799 | 0.1105 | 0.1584 | 0.1257 | 2,931 | 7,540 | 0 | 0 |

The table does not justify an operational threshold: the high-recall
thresholds flag most validation flights and produce very large false-positive
counts, while the 0.5 threshold misses nearly nine in ten delayed flights.
No operational cost/alert-capacity requirement was supplied. Any threshold is
therefore experimental and validation-derived, not production-verified.

## Probability calibration

Equal-frequency ten-bin reliability metrics on validation:

| Prediction set | Brier | Log loss | ECE | Average precision | ROC-AUC |
|---|---:|---:|---:|---:|---:|
| Saved Phase 4.2 model (trained on full training partition) | 0.16816 | 0.51914 | 0.17449 | 0.23457 | 0.61544 |
| Chronological base, no sigmoid (Jan 1–21 fit) | 0.26186 | 0.71947 | 0.34174 | 0.20568 | 0.58497 |
| Same chronological base + training-only sigmoid | 0.13802 | 0.44727 | 0.02481 | 0.20568 | 0.58497 |

The matched chronological experiment’s sigmoid mapping reduced Brier score,
log loss, and equal-frequency ECE, while leaving ranking metrics effectively
unchanged. This is evidence of improved validation probability calibration
for that experiment, **not** improved discrimination or proof that
calibration improves the saved full-training model. The saved full-training
model is shown separately because it used more base-fit data. At 0.5, the
calibrated experiment predicts no delayed flights, so calibration does not
make the original threshold suitable. Use the validation-derived threshold
table only as a trade-off study.

## XGBoost early stopping

The saved configuration uses `eval_metric="aucpr"`, 250 requested estimators,
and `early_stopping_rounds=25`. Its saved evaluation history has 27 rounds.
The best validation metric is 0.233582 at zero-based iteration 1 (the second
round); round one was 0.206257, and the 25 rounds following the best did not
improve. The best-score attribute exactly matches the history, and the
configured patience was exhausted. The booster stores 27 rounds, while the
effective best model uses two trees. This is consistent with the configured
early-stopping behavior; the saved history provides no evidence of a
configuration error or of a best iteration at the first round. Feature gain
was computed from the effective two-tree slice, not all stored rounds.

## Limitations and next steps

**Verified:** the model has weak recall at the saved 0.5 threshold, group
performance varies, the chronological training-only sigmoid experiment
improves its proper scoring/calibration metrics, and the dataset spans only
January–February 2024.

**Not established:** causal reasons for subgroup differences, performance in
other seasons/years, operational alert utility, or a production threshold.
The short history, distribution change across chronological windows, limited
features, correlated features, and positive-class imbalance are plausible
limitations to investigate with later sourced data and operational
requirements; they are hypotheses, not findings proven by this study.

## Reproduction and validation

Run the study with:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ml.explain_models
```

The script loads only validation rows for model comparison and uses training
rows only for its separate calibration experiment. It does not train the
original Phase 4.2 models. Unit and full-suite tests, dependency health, and
diff checks are recorded in the task completion report.
