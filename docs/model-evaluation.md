# Delay model evaluation (22 November 2026)

The target is **arrival delay greater than 15 minutes**, measured from completed
BTS flights. It is a binary pre-departure classification task. No score is a
prediction of delay minutes, and no reported cause is a model feature.

## Data and root causes

- The approved 21-column feature table uses carrier, origin, destination,
  scheduled clock and duration, route distance, calendar values and nine
  missing-value indicators. The old `ColumnTransformer` dropped those nine
  indicators despite listing them in the feature contract. The retrained
  pipeline includes them.
- The former model was selected at a fixed 0.5 threshold. On the untouched
  February 21–29 test period, this yielded only 1,415 true positives from
  23,971 delayed flights (recall 0.059). Threshold choice was the main
  classification defect; changing it trades precision for recall.
- Delay prevalence shifted from 0.210 in training to 0.167 in validation and
  0.145 in test. Available pre-departure schedule and route features provide
  limited predictive signal. The new PR-AUC is 0.209 against a test prevalence
  baseline of 0.145, so the model remains experimental.
- Calibration bins show underprediction: for scores from 0.1 to 0.2, the
  observed test delay rate was 0.174 versus a mean score of 0.138. Scores
  should not be treated as calibrated probabilities.

Eligible records exclude cancellations, diversions and missing arrival delay.
The dataset contains 1,040,639 eligible flights from January–February 2024.
Training is January 1–February 11 (716,676 rows), validation is February
12–20 (159,176), and the test is February 21–29 (164,787). The target and
source are never fitted into the preprocessor. Median imputation was fitted
on the training partition; one-hot encoding and scaling were fitted on the
training partition. The exact allowlist and leakage denylist live in
`pipelines/ml/feature_dataset.py`.

## Selection and held-out results

Five candidates from four families were retrained: unweighted and balanced
logistic regression, decision tree, random forest and XGBoost. Each threshold
was selected on validation to maximize F2 while meeting precision at least
0.25 where feasible. The final test partition was read only after candidate
and threshold selection. Unweighted logistic regression won validation F2
(0.338) at threshold **0.160998** with validation precision 0.250 and recall
0.370.

| Test metric | Previous balanced logistic, 0.5 | Retrained unweighted logistic, 0.160998 |
|---|---:|---:|
| Accuracy | 0.8380 | 0.7659 |
| Precision | 0.2548 | 0.2347 |
| Recall | 0.0590 | 0.2695 |
| F1 | 0.0959 | 0.2509 |
| F2 | 0.0697 | 0.2618 |
| PR-AUC | 0.2078 | 0.2085 |
| ROC-AUC | 0.6216 | 0.6216 |
| True positives | 1,415 | 6,461 |
| False positives | 4,139 | 21,068 |
| False negatives | 22,556 | 17,510 |

The new test Brier score is 0.1224 versus 0.1285 for a constant training
prevalence score. Majority-class accuracy is 0.8545, above either model's
accuracy; accuracy is therefore a poor selection criterion here. The new
threshold detects 5,046 more delayed flights and flags 16,929 more flights
incorrectly. Test precision fell below the 0.25 validation floor, evidence
of temporal drift. Do not use the classifier as a sole operational alert rule.

The saved output includes `test_calibration.json`, `test_subgroups.json` for
carrier and airports with at least 500 test rows, ROC/PR curves, a confusion
matrix, validation metrics, model manifests and full preprocessing pipelines.
Fifteen carriers, 63 origins and 63 destinations met the subgroup sample floor.
The complete artifact is under ignored `data/processed/ml/phase4_2/` and the
previous artifact is preserved under `phase4_2_backup_2026_11_22/` locally.
The original Isolation Forest and its original preprocessing manifest remain
paired with the new delay artifacts. The source dataset and artifact manifests
record checksums, feature order, target and training dates. Model artifacts
are excluded from Git, so a new checkout must restore them or rerun training.

Rebuild without overwriting a working artifact:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ml.train_models --output-dir data/processed/ml/phase4_2_retrained
```

Review `validation_metrics.json` and `final_test_metrics.json` before
promoting the new directory. The backend reads `phase4_2` by default.

## Follow-up inference audit

Saved research random-forest and XGBoost variants were rechecked against the
same validation selection rule and precision floor. The best research variant,
an unweighted random forest, reached validation F2 0.3350 versus 0.3378 for
the deployed logistic model, so no replacement was promoted. Exploratory
isotonic calibration reduced test Brier score from 0.12243 to 0.12157 but
reduced test PR-AUC from 0.20854 to 0.20557. Because this comparison reused
the existing test partition, it is not an independent basis for promotion.

Inference now declines dates outside January-February 2024 and carriers or
airports absent from the fitted training categories. Responses identify
schedule values replaced by training medians, and display held-out test
precision and recall only for the candidate actually evaluated on that test
partition. Predictions for dates within the training partition are marked as
in-sample. A later-year operational model needs later-year data and a fresh
chronological holdout; the present schedule-only features cannot support a
claim of perfect delay prediction.
