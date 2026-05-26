import os
import sys
import json
import logging
import warnings
from typing import List

import numpy as np
from scipy import stats as sp_stats
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score, f1_score, classification_report

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

FASTAPI_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(__file__))
from training import build_dataset_refs, WindowRef, zscore

SEED = 42


def _channel_features(x: np.ndarray) -> List[float]:
    x = x.astype(np.float64)
    d = np.diff(x)
    detrended = x - np.linspace(x[0], x[-1], len(x))
    zc = int(np.sum(np.diff(np.sign(detrended)) != 0))

    return [
        float(np.mean(x)),
        float(np.std(x)),
        float(np.min(x)),
        float(np.max(x)),
        float(np.percentile(x, 5)),
        float(np.percentile(x, 25)),
        float(np.percentile(x, 50)),
        float(np.percentile(x, 75)),
        float(np.percentile(x, 95)),
        float(sp_stats.skew(x)),
        float(sp_stats.kurtosis(x)),
        float(np.mean(np.abs(x - np.mean(x)))),
        float(np.max(x) - np.min(x)),
        float(np.mean(np.abs(d))),
        float(np.std(d)),
        float(zc),
        float(np.mean(x > 160.0)),
        float(np.mean(x < 120.0)),
        float(np.mean(x < 100.0)),
    ]


def extract_features(ref: WindowRef) -> np.ndarray:
    bpm = ref.bpm.astype(np.float64)
    ute = ref.uterus.astype(np.float64)

    fhr_feats = _channel_features(bpm)
    toco_feats = _channel_features(ute)

    pearson = float(np.corrcoef(bpm, ute)[0, 1])
    spearman = float(sp_stats.spearmanr(bpm, ute).statistic)

    toco_thresh = np.percentile(ute, 90)
    high_toco_mask = ute >= toco_thresh
    fhr_on_toco = float(np.mean(bpm[high_toco_mask])) if high_toco_mask.any() else float(np.mean(bpm))

    bpm_z = zscore(bpm)
    ute_z = zscore(ute)
    n = len(bpm_z)
    lag1_corr = float(np.dot(bpm_z[1:], ute_z[:-1]) / n)
    lag5_corr = float(np.dot(bpm_z[5:], ute_z[:-5]) / n)

    cross_feats = [pearson, spearman, fhr_on_toco, lag1_corr, lag5_corr]

    feat = np.array(fhr_feats + toco_feats + cross_feats, dtype=np.float32)
    feat = np.nan_to_num(feat, nan=0.0, posinf=0.0, neginf=0.0)
    return feat


def main():
    try:
        from catboost import CatBoostClassifier
    except ImportError:
        log.error("catboost not installed. Run: pip install catboost")
        return

    data_root = os.path.join(os.path.dirname(__file__))
    all_windows = build_dataset_refs(data_root, stride_sec=300)

    log.info(f"Extracting {len(all_windows)} feature vectors …")
    X = np.stack([extract_features(w) for w in all_windows])
    y = np.array([w.label for w in all_windows], dtype=int)
    groups = np.array([w.case_id for w in all_windows])

    log.info(f"Feature matrix: {X.shape},  class balance: {y.mean():.3f}")

    case_ids = sorted({w.case_id for w in all_windows})
    case_label = {w.case_id: w.label for w in all_windows}
    case_labels_arr = np.array([case_label[c] for c in case_ids])

    n_folds = 3
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=SEED)

    fold_aucs, fold_f1s = [], []

    for fold, (train_ci, val_ci) in enumerate(skf.split(case_ids, case_labels_arr)):
        train_cases = {case_ids[i] for i in train_ci}
        val_cases = {case_ids[i] for i in val_ci}

        tr_mask = np.array([g in train_cases for g in groups])
        va_mask = np.array([g in val_cases for g in groups])

        X_tr, y_tr = X[tr_mask], y[tr_mask]
        X_va, y_va = X[va_mask], y[va_mask]

        n_neg = int((y_tr == 0).sum())
        n_pos = int((y_tr == 1).sum())
        scale_pos = n_neg / max(n_pos, 1)

        model = CatBoostClassifier(
            iterations=500,
            learning_rate=0.05,
            depth=6,
            scale_pos_weight=scale_pos,
            eval_metric="AUC",
            random_seed=SEED,
            verbose=False,
            early_stopping_rounds=40,
        )
        model.fit(X_tr, y_tr, eval_set=(X_va, y_va))

        probs = model.predict_proba(X_va)[:, 1]
        preds = (probs >= 0.5).astype(int)
        auc = roc_auc_score(y_va, probs)
        f1 = f1_score(y_va, preds, zero_division=0)
        fold_aucs.append(auc)
        fold_f1s.append(f1)
        log.info(f"  Fold {fold}: AUC={auc:.4f}  F1={f1:.4f}")

    mean_auc = float(np.mean(fold_aucs))
    std_auc = float(np.std(fold_aucs))
    log.info(f"\nCatBoost CV AUC: {mean_auc:.4f} ± {std_auc:.4f}")

    skf2 = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=SEED)
    _, val_ci0 = next(iter(skf2.split(case_ids, case_labels_arr)))
    val_cases0 = {case_ids[i] for i in val_ci0}
    va_mask0 = np.array([g in val_cases0 for g in groups])
    tr_mask0 = ~va_mask0

    n_neg0 = int((y[tr_mask0] == 0).sum())
    n_pos0 = int((y[tr_mask0] == 1).sum())
    scale_pos0 = n_neg0 / max(n_pos0, 1)

    final_model = CatBoostClassifier(
        iterations=500,
        learning_rate=0.05,
        depth=6,
        scale_pos_weight=scale_pos0,
        eval_metric="AUC",
        random_seed=SEED,
        verbose=False,
        early_stopping_rounds=40,
    )
    final_model.fit(X[tr_mask0], y[tr_mask0], eval_set=(X[va_mask0], y[va_mask0]))

    probs0 = final_model.predict_proba(X[va_mask0])[:, 1]
    preds0 = (probs0 >= 0.5).astype(int)
    y_va0 = y[va_mask0]

    report = classification_report(
        y_va0, preds0,
        target_names=["regular", "hypoxia"],
        output_dict=True,
    )
    log.info("\n" + classification_report(
        y_va0, preds0, target_names=["regular", "hypoxia"]))

    results = {
        "run_id": "catboost",
        "model": "CatBoost (depth=6, iterations=500)",
        "n_features": int(X.shape[1]),
        "n_folds": n_folds,
        "mean_cv_auc": round(mean_auc, 4),
        "std_cv_auc": round(std_auc, 4),
        "fold_aucs": [round(a, 4) for a in fold_aucs],
        "val_fold0": {
            "auc": round(roc_auc_score(y_va0, probs0), 4),
            "f1_hypoxia": round(report["hypoxia"]["f1-score"], 4),
            "precision_hypoxia": round(report["hypoxia"]["precision"], 4),
            "recall_hypoxia": round(report["hypoxia"]["recall"], 4),
            "accuracy": round(report["accuracy"], 4),
        },
    }
    out = os.path.join(FASTAPI_DIR, "results_catboost.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    log.info(f"Results saved → {out}")


if __name__ == "__main__":
    main()
