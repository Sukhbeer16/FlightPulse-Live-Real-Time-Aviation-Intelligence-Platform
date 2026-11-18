# Phase 4.4.1 — Targeted model performance improvement

## Data and safeguards

This experiment retains the existing 21 Phase 4.1.6 allowlisted inputs,
target, and chronological partitions. It loads only training rows
(January 1–February 11, 2024) and validation rows (February 12–20, 2024).whht 
The final test partition (February 21–29) is not loaded, evaluated, or used
for threshold selection. No earlier phase artifacts or saved models are
written. No new feature engineering, synthetic oversampling, cross-validation,
or new dependency is used.

Training contains 150,800 delayed and 565,876 non-delayed flights, giving a
negative-to-positive ratio of 3.75249. Validation contains 26,526 delayed
and 132,650 non-delayed flights. The 21-feature preprocessor is fit on train
only. Random seeds are fixed at 42; estimators run sequentially with one
worker.

## Pilot design

The first pilot held Phase 4.2 Random Forest/XGBoost structure fixed and
changed only the class imbalance treatment:

- Random Forest: `class_weight=None`, `balanced`, or `balanced_subsample`.
- XGBoost: `scale_pos_weight=1` or the training negative/positive ratio
  (3.75249).

Each model's validation probabilities were evaluated at 0.5 and a fixed grid
from 0.05 to 0.80 in increments of 0.05. The grid was selected in advance;
the best threshold is selected on validation and is therefore a validation
result, not an unbiased post-selection estimate. No threshold was chosen
using test data.

### Pilot at threshold 0.5

| Candidate | Accuracy | Precision | Recall | F1 | F2 | AP | ROC-AUC | Balanced accuracy | FPR | TN / FP / FN / TP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| RF unweighted | 0.833354 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.237626 | 0.617344 | 0.500000 | 0.000000 | 132650 / 0 / 26526 / 0 |
| RF balanced | 0.680944 | 0.240646 | 0.424301 | 0.307111 | 0.368114 | 0.239024 | 0.617865 | 0.578283 | 0.267735 | 97135 / 35515 / 15271 / 11255 |
| RF balanced_subsample | 0.660056 | 0.233319 | 0.454912 | 0.308441 | 0.382295 | 0.234261 | 0.613993 | 0.577995 | 0.298922 | 92998 / 39652 / 14459 / 12067 |
| XGBoost unweighted | 0.826877 | 0.242893 | 0.018359 | 0.034138 | 0.022524 | 0.214608 | 0.605700 | 0.503458 | 0.011444 | 131132 / 1518 / 26039 / 487 |
| XGBoost train-ratio weighted | 0.645166 | 0.225148 | 0.462527 | 0.302867 | 0.381981 | 0.222246 | 0.608046 | 0.572108 | 0.318311 | 90426 / 42224 / 14257 / 12269 |

The balanced Phase 4.2 Random Forest is the only pilot candidate that exceeds
the current tuned Random Forest in both accuracy and F1 at the same 0.5
threshold: 0.680944 / 0.307111 versus 0.671276 / 0.306981. The F1 increase
is only 0.000130, so it is a narrow measured improvement. Its recall is
0.424301 (slightly below the tuned model's 0.436892) and FPR is 0.267735
(below 0.281855). The class-weight pilot shows the expected trade-off: class
weighting increases delayed-flight recall and F1 while reducing accuracy.
XGBoost ratio weighting raises recall from 0.018359 to 0.462527 but lowers
accuracy from 0.826877 to 0.645166 and increases FPR.

The best F1 point on the pilot's threshold grid for unweighted Random Forest
is threshold 0.20 (accuracy 0.540433, F1 0.319504); it does not satisfy the
joint accuracy/F1 objective. The best balanced-RF F1 point is threshold 0.45
(accuracy 0.475537, F1 0.317523), also not a useful joint trade-off. The
threshold 0.5 balanced-RF result is the pilot's joint success and is carried
forward as a hypothesis, not claimed as a robust generalization gain.

## Bounded parameter expansion

The expansion is deliberately limited to six sequential fits, based on the
pilot. It compares the tuned Random Forest structure with unweighted and
balanced classes, one regularized balanced Random Forest configuration, the
tuned XGBoost structure with no/half training-ratio class weighting, and one
more regularized, shallower XGBoost configuration with half-ratio weighting.
The RF alternatives explicitly vary tree count, depth, split/leaf minimums,
feature sampling and class weight. XGBoost alternatives vary class weight,
depth, learning rate, child weight, row/column sampling, and L1/L2
regularization. Full configurations and every threshold row are saved in the
expansion report and CSV.

During execution, the first regularized RF proposal using
`max_features=0.6` exceeded 900 CPU-seconds without finishing. That uncheckpointed
fit was stopped to protect laptop resources and replaced with the lower-cost
`max_features="log2"` setting. The two already completed RF checkpoints were
checksum-verified and reused; the stopped fit produced no saved model.

### Expansion at threshold 0.5

| Candidate | Accuracy | Precision | Recall | F1 | F2 | AP | ROC-AUC | Balanced accuracy | FPR | TN / FP / FN / TP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| RF tuned structure, unweighted | 0.833354 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.234953 | 0.615464 | 0.500000 | 0.000000 | 132650 / 0 / 26526 / 0 |
| RF tuned structure, balanced | 0.668750 | 0.236021 | 0.441567 | 0.307618 | 0.376065 | 0.233815 | 0.613520 | 0.577873 | 0.285820 | 94736 / 37914 / 14813 / 11713 |
| RF regularized, balanced | 0.688709 | 0.229270 | 0.367526 | 0.282383 | 0.327971 | 0.217221 | 0.599468 | 0.560231 | 0.247064 | 99877 / 32773 / 16777 / 9749 |
| XGBoost tuned structure, unweighted | 0.822850 | 0.234097 | 0.027746 | 0.049612 | 0.033685 | 0.206727 | 0.587697 | 0.504797 | 0.018153 | 130242 / 2408 / 25790 / 736 |
| XGBoost tuned structure, half-ratio weight | 0.789120 | 0.250655 | 0.133416 | 0.174142 | 0.147185 | 0.217885 | 0.596948 | 0.526829 | 0.079759 | 122070 / 10580 / 22987 / 3539 |
| XGBoost regularized, half-ratio weight | 0.767276 | 0.219879 | 0.155621 | 0.182252 | 0.165281 | 0.205336 | 0.580176 | 0.522605 | 0.110411 | 118004 / 14646 / 22398 / 4128 |

None of the six expansion candidates improves both reference accuracy and F1
at threshold 0.5. The RF tuned-structure balanced variant improves F1 to
0.307618 but falls short on accuracy (0.668750). The regularized balanced RF
improves accuracy to 0.688709 but its F1 is 0.282383. The pilot's Phase 4.2
balanced RF remains the only observed joint improvement, with the small
0.000130 F1 margin described above.

Across the pilot fits, model fitting totaled 230.32 seconds (RF 60.4/72.3/63.5
seconds; XGBoost 17.3/16.8 seconds); its wall runtime was 253.18 seconds and
measured peak working set was 695.01 MiB. Completed expansion fits totaled
368.77 seconds (133.4/144.2/37.0 seconds for RF and 18.3/18.1/17.7 seconds
for XGBoost). The resumed expansion invocation took 108.57 seconds and
reported a 711.77 MiB peak working set. These timings exclude the uncheckpointed
high-cost `max_features=0.6` RF fit that was stopped.

The critical comparison remains accuracy and F1 against the current tuned
Random Forest (0.671276 accuracy, 0.306981 F1). The report lists each
candidate at threshold 0.5, its best observed F1 on the fixed threshold grid,
and its best grid point, if any, exceeding both reference metrics. These
validation-derived comparisons are not final test estimates.

## Outputs and reproduction

All outputs are isolated under the Git-ignored
`data/processed/ml/phase4_4_1/` directory. Pilot and expansion models,
probabilities, per-model threshold metrics, state fingerprints and reports
are checkpointed separately. Interrupted stages can resume matching
checkpoints; mismatched data/configuration fingerprints or checksum failures
stop the run. Existing pilot output is never overwritten by expansion.

Reloaded all 11 saved pilot/expansion estimators and regenerated validation
probabilities using a preprocessor refit on train only. All 11 arrays were
bitwise identical to their saved prediction checkpoints (maximum absolute
difference 0.0). The verification used only train and validation and is saved
in `reproducibility_check.json`.

Run the pilot first, then the bounded expansion:

```powershell
.\.venv\Scripts\python.exe -m pipelines.ml.improve_phase4_4_1 --stage pilot
.\.venv\Scripts\python.exe -m pipelines.ml.improve_phase4_4_1 --stage expansion
```

No Phase 4.5 work is part of this phase.
