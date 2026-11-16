# Phase 4.2.1 — Systematic hyperparameter optimization

## Scope and safeguards

This phase tunes only the four existing model families. The combined
January–February feature dataset, Phase 4.2 training artifacts, and Phase 4.3
explainability outputs are inputs/protected references and are not rewritten.
The final February 21–29 test partition is not loaded, scored, or used for
threshold selection. Its co-located Parquet bytes are covered only by the
input SHA-256 integrity check; row filters used for model fitting/evaluation
are limited to the training and external-validation partitions.

The model input is checked against the exact existing 21-column allowlist.
Actual arrival/departure outcomes, delay causes, cancellation/diversion
outcomes, and flight-progress fields are excluded by the allowlist contract.
Categorical encoding remains `OneHotEncoder(handle_unknown="ignore")` and all
search/final fitting is single-worker to limit laptop resource use.

## Baseline and data observations

Phase 4.2's saved validation results are used as the original baseline. The
saved Logistic Regression pipeline is the balanced candidate selected by its
original validation F2 rule. The unweighted Logistic Regression was a
comparison candidate but has no separately saved pipeline.

The existing Phase 4.2 `ColumnTransformer` transforms the three categorical
columns and nine numeric columns but drops the nine approved missingness
indicators via `remainder="drop"`. This optimization uses the requested full
21-feature allowlist, including those indicators. The comparison therefore
does not isolate hyperparameter tuning from the input-representation change.

### Chronological windows

| Window | Dates | Rows | Delayed | Non-delayed | Delayed prevalence |
|---|---|---:|---:|---:|---:|
| Inner training | Jan 1–Feb 1, 2024 | 543,602 | 125,106 | 418,496 | 23.01% |
| Inner validation | Feb 2–11, 2024 | 173,074 | 25,694 | 147,380 | 14.85% |
| External validation | Feb 12–20, 2024 | 159,176 | 26,526 | 132,650 | 16.66% |
| Final refit training | Jan 1–Feb 11, 2024 | 716,676 | 150,800 | 565,876 | 21.04% |

The first two windows reconcile exactly to the original training partition.
Their calendar-date ranges are disjoint and no random split is used. For each
tuning window, numeric medians are recomputed from observed inner-training
values only, using the existing missingness flags; those medians are applied
to inner-training and inner-validation rows before fitting the preprocessor.
Final model preprocessing is then fit on the complete original training
partition only.

## Search method and budgets

Optuna was not installed in the project environment. Searches use
scikit-learn `ParameterSampler`, with a fixed seed of 42, run sequentially
(`n_jobs=1`). The objective is inner-validation average precision (PR-AUC).
Precision, recall, F1, F2, ROC-AUC, balanced accuracy, and the 0.5-threshold
confusion matrix are also recorded for each successful trial. Failed trials
are recorded with the exception; this implementation does not prune trials.
Search fits use a reproducible uniform sample of 180,000 inner-training rows
without replacement (seed 42), restored to chronological row order. Inner
validation uses all 173,074 rows. The one-hot encoder and scaler are fit only
on the inner-training sample; unknown validation categories are ignored.
No cross-validation is used.

| Family | Trial budget | Search space |
|---|---:|---|
| Logistic Regression | 8 | `C` log-uniform [0.001, 100]; compatible `liblinear`/`saga` × L1/L2; class weight None/balanced; fixed `max_iter=500`, `tol=0.001` |
| Decision Tree | 8 | `max_depth` 4–30 or None; split 2–100; leaf 50–1,000; gini/entropy; class weight None/balanced |
| Random Forest | 5 | 100–400 estimators; depth 8–30 or None; split 2–50; leaf 20–500; max features sqrt/0.3/0.6/0.9; class weight None/balanced/balanced_subsample |
| XGBoost | 8 | 100–500 estimators; log-uniform learning rate 0.01–0.2; depth 2–8; min child weight 1–20; subsample/column sample 0.6–1.0; alpha 0–10; log-uniform lambda 0.1–20; positive weight is the fitting-data negative/positive ratio multiplied by 0.5/0.75/1/1.25/1.5/2 |

XGBoost uses inner-validation `aucpr` early stopping with patience 30; the
best iteration is retained for refitting. The external validation partition
is not used for early stopping. For final refits, `scale_pos_weight` is
recalculated from the full training partition only, preserving the selected
multiplier.

The budgets above are maxima. Measured execution required 2,413 seconds for
Random Forest trial 2 and 1,381 seconds for XGBoost trial 1 on this laptop.
To keep the study resource-bounded, the executed limits were reduced to two
trials for each of those families; the remaining trials are recorded as
skipped. The in-progress third Random Forest trial was interrupted and has no
completed metric record. Logistic Regression and Decision Tree used their
full budgets. The final report records completed, skipped, and failed counts
per family rather than presenting the maximum budgets as completed work.

The interrupted implementation had no durable per-trial checkpoints and
saved zero completed trials. Recovery inspection found no active optimizer
process, no completed study, and no existing output directory to resume.
The replacement writes each terminal trial result atomically and fingerprints
the data and base search configuration; actual resource-limited execution
limits are also recorded in the manifest. A matching interrupted run resumed
completed trials without refitting them; mismatched or completed output
directories are rejected rather than overwritten.

### Completed search results

| Family | Trials completed / max | Failed | Skipped | Best trial | Best inner AP |
|---|---:|---:|---:|---:|---:|
| Logistic Regression | 8 / 8 | 0 | 0 | 4 | 0.20438 |
| Decision Tree | 8 / 8 | 0 | 0 | 3 | 0.16477 |
| Random Forest | 2 / 5 | 0 | 3 | 1 | 0.19566 |
| XGBoost | 2 / 8 | 0 | 6 | 1 | 0.17448 |

Selected configurations (full sampled and refit configurations are in
`best_configurations.json`):

- **Logistic Regression:** `C=0.00195`, L1, `liblinear`, balanced class
  weights.
- **Decision Tree:** depth 13, gini, leaf 137, split 25, no class weighting.
- **Random Forest:** 171 trees, depth 26, sqrt features, leaf 290, split 44,
  `balanced_subsample`.
- **XGBoost:** depth 4, learning rate 0.17255, 288 requested trees, child
  weight 8, subsample 0.7837, column sample 0.7498, alpha 5.9685, lambda
  1.0614, scale-weight multiplier 1.0. The final refit recalculates
  `scale_pos_weight=3.75249` from the full training partition.

The Random Forest second trial took 2,413 seconds; the in-progress third trial
was interrupted and the remaining three candidates were recorded as skipped.
XGBoost trial 1 took 1,381 seconds and trial 2 took 643 seconds; six remaining
candidates were recorded as skipped. These are explicit resource-driven
stops, not successful full-budget searches. The best Random Forest and
XGBoost configurations are provisional because only two candidates were
evaluated for each.

## Refit, evaluation, and thresholds

For each family, the best inner-validation-PR-AUC configuration is refit on
the complete original training partition and scored once on the existing
external validation partition (February 12–20). Hyperparameter selection
does not use this external validation partition. The original Phase 4.2
validation metrics are loaded from their existing validation report for
comparison. The Phase 4.2 test-metrics artifact is only included in the
read-only protected-artifact checksum check; its contents are not parsed or
used for model evaluation or decisions.

Threshold analysis is separate from search. It reports precision, recall,
F1, F2, false positives, false negatives, and percent flagged across fixed
thresholds from 0.10 to 0.80. No threshold is selected as production-ready;
operational costs and alert capacity have not been specified.

Category distribution diagnostics report unknown-category rates and total
variation distance for inner train-to-inner validation and full train-to-
external validation. These describe chronological distribution shift and
are not causal findings. Here there were no unseen airlines, origins, or
destinations. The inner-to-inner-validation total-variation distances were
about 1.29%–1.40%; full-train-to-external-validation distances were about
1.41%–1.52%, indicating small measured categorical share shifts in these
partitions.

## Measured external-validation results

The validation set has 159,176 flights, with 26,526 delayed (16.66%). The
following compares the saved Phase 4.2 results with the refitted candidates
at the unchanged 0.5 threshold. Values are measured, not production
recommendations.

| Model | Phase 4.2 P / R / F1 / F2 / AP | Tuned P / R / F1 / F2 / AP |
|---|---|---|
| Logistic Regression | 0.2799 / 0.1105 / 0.1584 / 0.1257 / 0.23457 | 0.2930 / 0.0453 / 0.0784 / 0.0545 / 0.22352 |
| Decision Tree | 0.1708 / 0.0207 / 0.0370 / 0.0252 / 0.21464 | 0.1978 / 0.0285 / 0.0498 / 0.0343 / 0.21526 |
| Random Forest | 0 / 0 / 0 / 0 / 0.23275 | 0.2366 / 0.4369 / 0.3070 / 0.3736 / 0.23450 |
| XGBoost | 0 / 0 / 0 / 0 / 0.23005 | 0.2071 / 0.4648 / 0.2865 / 0.3722 / 0.20726 |

Other refitted-model validation metrics at threshold 0.5:

| Model | Accuracy | ROC-AUC | Balanced accuracy | TN / FP / FN / TP |
|---|---:|---:|---:|---|
| Logistic Regression | 0.8227 | 0.6030 | 0.5117 | 129,752 / 2,898 / 25,325 / 1,201 |
| Decision Tree | 0.8189 | 0.5981 | 0.5027 | 129,588 / 3,062 / 25,771 / 755 |
| Random Forest | 0.6713 | 0.6149 | 0.5775 | 95,262 / 37,388 / 14,937 / 11,589 |
| XGBoost | 0.6142 | 0.5874 | 0.5544 | 85,435 / 47,215 / 14,196 / 12,330 |

Decision Tree and Random Forest AP increased by only 0.00062 and 0.00176,
respectively; Logistic Regression decreased by 0.01105 and XGBoost by
0.02279. Thus there are small measured AP gains for two candidates, not a
general improvement across all four. Random Forest's large threshold-0.5
recall change is meaningful on this validation set, while its AP gain is
small. Phase 4.2 dropped the missingness indicators that Phase 4.2.1 adds,
so the changes cannot be attributed to hyperparameter tuning alone. The
limited Random Forest/XGBoost searches and absence of uncertainty intervals
also mean the small AP gains are not evidence of robust generalization.

At 0.5, the refitted Random Forest flags 30.77% of flights (precision
0.2366, recall 0.4369); XGBoost flags 37.41% (precision 0.2071, recall
0.4648). Logistic Regression flags 2.58% and recalls only 4.53% of delayed
flights. Decision Tree recalls 2.85%.

### Why the Phase 4.2 baselines were weak

The external-validation positive prevalence is 16.66%, so an all-negative
classifier already attains 83.34% accuracy. The Phase 4.2 Random Forest and
XGBoost each had 83.34% accuracy but predicted no positives at threshold
0.5, yielding zero precision, recall, and F2 despite AP values of 0.23275
and 0.23005. Their probability rankings contained some signal, but the
default threshold did not produce delayed-flight alerts. The balanced
Logistic Regression traded higher recall for low precision and still recalled
only 11.05% of delayed flights. These are measured threshold and class
imbalance effects, not evidence that the models are production-ready.

The selected tuned models use class weighting and the same 0.5 reporting
threshold, but their performance is not uniform: Random Forest gains recall
while Logistic Regression loses it, and XGBoost's AP declines. Calibration
was not part of this phase, so the results do not establish that the scores
are calibrated probabilities. Two months of data and the restricted
scheduled-time, distance, and categorical features also limit
generalization; later time periods and a larger feature review are needed.

## Validation threshold trade-offs

Thresholds were evaluated after refitting on February 12–20 only. The CSV
contains all ten thresholds from 0.10 to 0.80, including precision, recall,
F1, F2, false positives, false negatives, and flagged-flight rate. A few
contrasting points illustrate why no threshold is selected for production:

| Model | Threshold | Precision | Recall | F2 | False positives | False negatives | Flights flagged |
|---|---:|---:|---:|---:|---:|---:|---:|
| Logistic Regression | 0.25 | 0.1739 | 0.9419 | 0.5002 | 118,669 | 1,542 | 90.25% |
| Logistic Regression | 0.50 | 0.2930 | 0.0453 | 0.0545 | 2,898 | 25,325 | 2.58% |
| Decision Tree | 0.10 | 0.1970 | 0.7189 | 0.4699 | 77,729 | 7,457 | 60.81% |
| Decision Tree | 0.15 | 0.2405 | 0.3913 | 0.3477 | 32,776 | 16,146 | 27.11% |
| Random Forest | 0.40 | 0.1817 | 0.8984 | 0.5022 | 107,345 | 2,694 | 82.41% |
| Random Forest | 0.50 | 0.2366 | 0.4369 | 0.3736 | 37,388 | 14,937 | 30.77% |
| XGBoost | 0.40 | 0.1951 | 0.7202 | 0.4681 | 78,837 | 7,422 | 61.53% |
| XGBoost | 0.50 | 0.2071 | 0.4648 | 0.3722 | 47,215 | 14,196 | 37.41% |

The high-F2 points flag 60.8%–90.3% of all flights. Without an agreed alert
capacity and false-positive cost, none is justified as an operational
threshold; all are validation-derived experiments.

## Explainability and early stopping

The Logistic Regression's largest absolute coefficients include
`Reporting_Airline_YX` (-0.457), `Reporting_Airline_DL` (-0.319), and
`month` (-0.309). These are coefficients after one-hot encoding and numeric
scaling; categorical coefficients are relative to the encoder's reference
category. They are associations, not causal effects.

For the Decision Tree, impurity importance is led by `day_of_month` (0.360)
and `day_of_week` (0.147). Random Forest impurity importance is led by
`day_of_month` (0.203), `Reporting_Airline` (0.133 when dummy importances are
summed), and `month` (0.127). XGBoost's gain-based `feature_importances_`,
summed over dummy variables, is led by `Origin` (0.452), `Dest` (0.291), and
`Reporting_Airline` (0.171). These importance values are model-dependent, not
causal; impurity measures can favor high-cardinality or correlated features.
The methods and scales are not directly comparable across model families.

XGBoost trial 1 selected iteration 287 of 288; early stopping did not
materially shorten that trial. Trial 2 selected iteration 84 of 443, showing
early stopping did take effect there. The best configuration refit uses 288
trees (`best_iteration + 1`) on the full training partition; external
validation did not control early stopping.

## Resource use, outputs, and verification

Completed search estimator fits totaled approximately 4,618 seconds and
full-training refits approximately 790 seconds (about 90 minutes combined),
excluding preprocessing, validation scoring, interrupted work, and final
artifact writing. Process sampling observed a peak working set of about
528 MB and peak private memory of about 1.40 GB during final refits. The
output manifest records the final resumed packaging invocation's runtime;
per-trial and per-refit durations are the appropriate cumulative fit-time
records.

The manifest records 543,602 inner-training rows, 173,074 inner-validation
rows, 716,676 final-refit training rows, and 159,176 external-validation
rows, with the expected date boundaries. The combined dataset SHA-256 was
unchanged at
`04a1c910665325d2dfdfaf549487dfbf76e774651a01af10ad978807c23b3013`.
Before/after hashes for the protected Phase 4.2 and Phase 4.3 artifacts
match. The final test partition was not loaded or scored; the Parquet file
was read only for its integrity checksum, and Phase 4.2 test-metric bytes
were only included in a read-only preservation checksum.

Generated files include four fitted pipelines, per-family trial checkpoints,
`randomized_search_trials.jsonl`, `hyperparameter_search_summary.json`,
`best_configurations.json`, `optimized_validation_metrics.json`,
`phase42_vs_optimized_validation.csv`,
`optimized_validation_thresholds.csv`,
`optimized_validation_confusion_matrices.csv`,
`optimized_feature_importance.csv`, ROC/PR plots, `refit_*.json`, and
`experiment_manifest.json`. These reside in the Git-ignored output directory.

Focused tests: 14 passed. The full suite completed with 94 passed and one
existing Starlette `TestClient`/httpx deprecation warning. `pip check`
reported no broken requirements, and `git diff --check` passed. The working
tree contains five modified source/documentation files; all generated model
and data outputs are Git-ignored. No commit or push was made.

During execution, Parquet row order was found not to be globally
chronological. The loader now applies a stable date sort to each approved
training/validation window without modifying the source dataset. A final
manifest-generation error caused by a deleted temporary label array was
fixed by persisting its summary counts before releasing the array; the
already-fitted model artifacts were safely reused to complete the report.

## Outputs and reproduction

Artifacts are generated under the Git-ignored
`data/processed/ml/phase4_2_improvements/` directory:

- Four optimized joblib pipelines with their fitted preprocessing.
- Per-family atomic trial checkpoints, per-refit records, per-trial JSONL
  records, and a best-configuration/search summary.
- Original-versus-optimized external-validation comparison.
- Per-model validation metrics, confusion matrices, threshold table, and ROC
  and precision-recall plots.
- Coefficients/tree impurity importance where supported.
- An experiment manifest with partition counts, date boundaries, search
  budgets, package versions, input checksum, protected Phase 4.2/4.3 artifact
  checksums, and generated-file checksums.

Run with:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ml.optimize_models
```

This analysis does not claim operational readiness or use the final test
partition. Reproduce (or safely resume) with the command above; a completed
output directory is intentionally protected from reruns.
