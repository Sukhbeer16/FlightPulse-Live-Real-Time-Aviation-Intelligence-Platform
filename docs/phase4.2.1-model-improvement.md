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

The model-data contract allows 21 input fields, but inspection found that the
existing Phase 4.2 `ColumnTransformer` transforms the three categorical
columns and nine numeric columns and drops the nine approved missingness
indicators via `remainder="drop"`. This phase retains that preprocessor
unchanged so model comparisons isolate hyperparameter search rather than
silently changing the input representation. The dropped-indicator behavior
is recorded as a limitation for a separately scoped feature-preprocessing
change.

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

| Family | Trial budget | Search space |
|---|---:|---|
| Logistic Regression | 20 | `C` log-uniform [0.001, 100]; compatible `liblinear`/`saga` × L1/L2; class weight None/balanced; fixed `max_iter=1000`, `tol=0.001` |
| Decision Tree | 20 | `max_depth` 4–30 or None; split 2–100; leaf 50–1,000; gini/entropy; class weight None/balanced |
| Random Forest | 15 | 100–400 estimators; depth 8–30 or None; split 2–50; leaf 20–500; max features sqrt/0.3/0.6/0.9; class weight None/balanced/balanced_subsample |
| XGBoost | 20 | 100–500 estimators; log-uniform learning rate 0.01–0.2; depth 2–8; min child weight 1–20; subsample/column sample 0.6–1.0; alpha 0–10; log-uniform lambda 0.1–20; positive weight is the fitting-data negative/positive ratio multiplied by 0.5/0.75/1/1.25/1.5/2 |

XGBoost does not use external-validation early stopping during this search;
`n_estimators` is directly optimized against the inner validation objective.
For final refits, `scale_pos_weight` is recalculated from the full training
partition only, preserving the selected multiplier.

## Refit, evaluation, and thresholds

For each family, the best inner-validation-PR-AUC configuration is refit on
the complete original training partition and scored once on the existing
external validation partition (February 12–20). Hyperparameter selection
does not use this external validation partition. The original Phase 4.2
validation metrics are loaded from their existing validation report for
comparison; the original test metrics are not opened.

Threshold analysis is separate from search. It reports precision, recall,
F1, F2, false positives, false negatives, and percent flagged across fixed
thresholds from 0.10 to 0.80. No threshold is selected as production-ready;
operational costs and alert capacity have not been specified.

Category distribution diagnostics report unknown-category rates and total
variation distance for inner train-to-inner validation and full train-to-
external validation. These describe chronological distribution shift and
are not causal findings.

## Outputs and reproduction

Artifacts are generated under the Git-ignored
`data/processed/ml/phase4_2_improvements/` directory:

- Four optimized joblib pipelines with their fitted preprocessing.
- Per-trial JSONL records and a best-configuration/search summary.
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

Measured trial outcomes, comparison results, runtime, and validation status
are added to this report after the bounded studies finish. This analysis
does not claim operational readiness or use the final test partition.
