import os
import random
import warnings
import argparse
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score, f1_score, classification_report

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TARGET_HZ = 1.0
WINDOW_SEC = 20 * 60
WINDOW_LEN = int(WINDOW_SEC * TARGET_HZ)
STRIDE_SEC = 5 * 60

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
torch.manual_seed(SEED)


@dataclass
class WindowRef:
    case_id: str
    label: int
    bpm: np.ndarray
    uterus: np.ndarray


def interp_to_1hz(times: np.ndarray, arr: np.ndarray) -> np.ndarray:
    t = np.asarray(times, dtype=np.float64)
    a = np.asarray(arr, dtype=np.float64)
    if np.any(np.diff(t) <= 0):
        idx = np.argsort(t)
        t, a = t[idx], a[idx]
    t0, t1 = float(t[0]), float(t[-1])
    nsec = int(round(t1 - t0))
    if nsec <= 0:
        return np.array([], dtype=np.float32)
    grid = np.arange(t0, t0 + nsec + 1e-6, 1.0 / TARGET_HZ, dtype=np.float64)
    return np.interp(grid, t, a).astype(np.float32)


def clip_physiology(bpm: np.ndarray, uterus: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    return np.clip(bpm, 50.0, 210.0), np.clip(uterus, -5.0, 100.0)


def zscore(x: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    m = float(np.nanmean(x))
    s = float(np.nanstd(x))
    if not np.isfinite(s) or s < eps:
        s = 1.0
    return ((x - m) / s).astype(np.float32)


def fix_len(a: np.ndarray, target: int) -> np.ndarray:
    if len(a) >= target:
        return a[:target]
    pad = np.full(target - len(a), a[-1] if len(a) > 0 else 0.0, dtype=a.dtype)
    return np.concatenate([a, pad])


def _read_csv_signal(path: str) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    try:
        df = pd.read_csv(path)
        if "time_sec" not in df.columns or "value" not in df.columns:
            return None
        return df["time_sec"].values.astype(np.float64), df["value"].values.astype(np.float64)
    except Exception as e:
        log.warning(f"Failed to read {path}: {e}")
        return None


def _load_case_signal(case_dir: str, channel: str) -> Optional[np.ndarray]:
    ch_dir = os.path.join(case_dir, channel)
    if not os.path.isdir(ch_dir):
        return None

    suffix = "_1.csv" if channel == "bpm" else "_2.csv"
    files = sorted(f for f in os.listdir(ch_dir) if f.endswith(suffix))
    if not files:
        return None

    segments = []
    for fname in files:
        result = _read_csv_signal(os.path.join(ch_dir, fname))
        if result is None:
            continue
        times, values = result
        seg_1hz = interp_to_1hz(times, values)
        if len(seg_1hz) > 0:
            segments.append(seg_1hz)

    if not segments:
        return None
    return np.concatenate(segments, axis=0).astype(np.float32)


def extract_windows(
    bpm_1hz: np.ndarray,
    uterus_1hz: np.ndarray,
    case_id: str,
    label: int,
    stride: int = int(STRIDE_SEC * TARGET_HZ),
    min_fraction: float = 0.5,
) -> List[WindowRef]:
    n = min(len(bpm_1hz), len(uterus_1hz))
    bpm_1hz = bpm_1hz[:n]
    uterus_1hz = uterus_1hz[:n]

    windows: List[WindowRef] = []

    if n < int(WINDOW_LEN * min_fraction):
        return windows

    if n < WINDOW_LEN:
        bpm_w = fix_len(bpm_1hz, WINDOW_LEN)
        ute_w = fix_len(uterus_1hz, WINDOW_LEN)
        windows.append(WindowRef(case_id, label, bpm_w, ute_w))
        return windows

    starts = list(range(0, n - WINDOW_LEN + 1, stride))
    if not starts:
        starts = [0]
    for s in starts:
        bpm_w = bpm_1hz[s: s + WINDOW_LEN].copy()
        ute_w = uterus_1hz[s: s + WINDOW_LEN].copy()
        windows.append(WindowRef(case_id, label, bpm_w, ute_w))

    return windows


def build_dataset_refs(data_root: str, stride_sec: float = STRIDE_SEC) -> List[WindowRef]:
    stride_pts = int(stride_sec * TARGET_HZ)
    all_windows: List[WindowRef] = []

    for label, subdir in [(1, "hypoxia"), (0, "regular")]:
        class_dir = os.path.join(data_root, subdir)
        if not os.path.isdir(class_dir):
            log.warning(f"Directory not found: {class_dir}")
            continue

        cases = sorted(os.listdir(class_dir))
        for case_id in cases:
            case_dir = os.path.join(class_dir, case_id)
            if not os.path.isdir(case_dir):
                continue

            bpm_sig = _load_case_signal(case_dir, "bpm")
            ute_sig = _load_case_signal(case_dir, "uterus")

            if bpm_sig is None or ute_sig is None:
                log.warning(f"Missing signal for case {subdir}/{case_id}")
                continue

            bpm_sig, ute_sig = clip_physiology(bpm_sig, ute_sig)
            unique_case_id = f"{subdir}_{case_id}"
            wins = extract_windows(bpm_sig, ute_sig, unique_case_id, label, stride=stride_pts)
            all_windows.extend(wins)

        log.info(f"Loaded {subdir}: {len(cases)} cases")

    log.info(f"Total windows: {len(all_windows)}  "
             f"(hypoxia={sum(w.label for w in all_windows)}, "
             f"regular={sum(1-w.label for w in all_windows)})")
    return all_windows


class FhrTocoDataset(Dataset):
    def __init__(self, refs: List[WindowRef], augment: bool = False):
        self.refs = refs
        self.augment = augment

    def __len__(self):
        return len(self.refs)

    def _augment(self, x: np.ndarray) -> np.ndarray:
        if random.random() < 0.5:
            shift = random.randint(-5, 5)
            x = np.roll(x, shift, axis=-1)
        if random.random() < 0.5:
            x = x + np.random.normal(0, 0.02, size=x.shape).astype(np.float32)
        if random.random() < 0.5:
            scale = float(np.clip(np.random.normal(1.0, 0.1), 0.7, 1.3))
            x[1] *= scale
        if random.random() < 0.4:
            scale = float(np.clip(np.random.normal(1.0, 0.08), 0.8, 1.2))
            x[0] *= scale
        return x

    def __getitem__(self, idx: int):
        ref = self.refs[idx]
        bpm_z = zscore(ref.bpm)
        ute_z = zscore(ref.uterus)
        x = np.stack([bpm_z, ute_z], axis=0).astype(np.float32)
        if self.augment:
            x = self._augment(x)
        y = torch.tensor(ref.label, dtype=torch.float32)
        return torch.from_numpy(x), y


class ResidualBlock(nn.Module):
    def __init__(self, c_in, c_out, k=7, d=1, p_drop=0.1):
        super().__init__()
        pad = (k - 1) // 2 * d
        self.conv1 = nn.Conv1d(c_in, c_out, kernel_size=k, padding=pad, dilation=d)
        self.bn1 = nn.BatchNorm1d(c_out)
        self.conv2 = nn.Conv1d(c_out, c_out, kernel_size=k, padding=pad, dilation=d)
        self.bn2 = nn.BatchNorm1d(c_out)
        self.act = nn.SiLU()
        self.dropout = nn.Dropout(p_drop)
        self.skip = nn.Conv1d(c_in, c_out, 1) if c_in != c_out else nn.Identity()

    def forward(self, x):
        h = self.act(self.bn1(self.conv1(x)))
        h = self.dropout(h)
        h = self.bn2(self.conv2(h))
        return self.act(h + self.skip(x))


class TinyTCN(nn.Module):
    def __init__(self, in_ch=2, base=48, num_classes=1, p_drop=0.1):
        super().__init__()
        self.stem = nn.Conv1d(in_ch, base, kernel_size=7, padding=3)
        self.block1 = ResidualBlock(base, base, k=7, d=1, p_drop=p_drop)
        self.block2 = ResidualBlock(base, base * 2, k=7, d=2, p_drop=p_drop)
        self.pool2 = nn.AvgPool1d(2)
        self.block3 = ResidualBlock(base * 2, base * 2, k=7, d=4, p_drop=p_drop)
        self.block4 = ResidualBlock(base * 2, base * 4, k=7, d=8, p_drop=p_drop)
        self.pool4 = nn.AdaptiveAvgPool1d(1)
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(base * 4, base * 2),
            nn.ReLU(),
            nn.Dropout(p_drop),
            nn.Linear(base * 2, num_classes),
        )

    def forward(self, x):
        x = self.stem(x)
        x = self.block1(x)
        x = self.block2(x)
        x = self.pool2(x)
        x = self.block3(x)
        x = self.block4(x)
        x = self.pool4(x)
        return self.head(x).squeeze(-1)


def make_weighted_sampler(refs: List[WindowRef]) -> WeightedRandomSampler:
    labels = np.array([r.label for r in refs])
    counts = np.bincount(labels)
    weights = 1.0 / counts[labels]
    return WeightedRandomSampler(
        weights=torch.from_numpy(weights).float(),
        num_samples=len(refs),
        replacement=True,
    )


def train_one_epoch(model, loader, optimizer, criterion, device, scaler=None):
    model.train()
    total_loss = 0.0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        optimizer.zero_grad()
        if scaler is not None:
            with torch.amp.autocast("cuda"):
                logits = model(x)
                loss = criterion(logits, y)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
        else:
            logits = model(x)
            loss = criterion(logits, y)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
        total_loss += loss.item() * len(y)
    return total_loss / len(loader.dataset)


@torch.no_grad()
def evaluate(model, loader, criterion, device):
    model.eval()
    total_loss = 0.0
    all_probs, all_labels = [], []
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        logits = model(x)
        loss = criterion(logits, y)
        total_loss += loss.item() * len(y)
        probs = torch.sigmoid(logits).cpu().numpy()
        all_probs.extend(probs.tolist())
        all_labels.extend(y.cpu().numpy().tolist())
    avg_loss = total_loss / max(len(loader.dataset), 1)
    labels_arr = np.array(all_labels, dtype=int)
    probs_arr = np.array(all_probs)
    preds_arr = (probs_arr >= 0.5).astype(int)
    auc = roc_auc_score(labels_arr, probs_arr) if len(np.unique(labels_arr)) > 1 else 0.5
    f1 = f1_score(labels_arr, preds_arr, zero_division=0)
    return avg_loss, auc, f1, labels_arr, probs_arr


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--data_root", default=os.path.dirname(__file__))
    p.add_argument("--out_dir", default=os.path.dirname(os.path.dirname(__file__)))
    p.add_argument("--run_id", default="")
    p.add_argument("--n_folds", type=int, default=5)
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--batch_size", type=int, default=16)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--base", type=int, default=48)
    p.add_argument("--p_drop", type=float, default=0.2)
    p.add_argument("--pos_weight", type=float, default=None)
    p.add_argument("--stride_sec", type=int, default=300)
    p.add_argument("--seed", type=int, default=SEED)
    return p.parse_args()


def main():
    args = parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    log.info(f"Device: {device}")

    all_windows = build_dataset_refs(args.data_root, stride_sec=args.stride_sec)
    if len(all_windows) == 0:
        raise RuntimeError("No windows found. Check data_root path.")

    case_ids = list({w.case_id for w in all_windows})
    case_label = {w.case_id: w.label for w in all_windows}
    case_ids_sorted = sorted(case_ids)
    case_labels_arr = np.array([case_label[c] for c in case_ids_sorted])

    log.info(f"Unique cases: {len(case_ids_sorted)}  "
             f"(hypoxia={case_labels_arr.sum()}, regular={(1-case_labels_arr).sum()})")

    n_neg = int((1 - case_labels_arr).sum())
    n_pos = int(case_labels_arr.sum())
    auto_pos_weight = n_neg / max(n_pos, 1)
    pos_weight_val = args.pos_weight if args.pos_weight is not None else auto_pos_weight
    log.info(f"BCEWithLogitsLoss pos_weight = {pos_weight_val:.2f}")

    skf = StratifiedKFold(n_splits=args.n_folds, shuffle=True, random_state=args.seed)
    fold_results = []

    for fold, (train_case_idx, val_case_idx) in enumerate(
            skf.split(case_ids_sorted, case_labels_arr)):

        train_cases = {case_ids_sorted[i] for i in train_case_idx}
        val_cases = {case_ids_sorted[i] for i in val_case_idx}

        train_refs = [w for w in all_windows if w.case_id in train_cases]
        val_refs = [w for w in all_windows if w.case_id in val_cases]

        log.info(f"\n── Fold {fold} ──  train_windows={len(train_refs)}  "
                 f"val_windows={len(val_refs)}")

        train_ds = FhrTocoDataset(train_refs, augment=True)
        val_ds = FhrTocoDataset(val_refs, augment=False)

        sampler = make_weighted_sampler(train_refs)
        train_loader = DataLoader(
            train_ds, batch_size=args.batch_size,
            sampler=sampler, num_workers=0, pin_memory=False,
        )
        val_loader = DataLoader(
            val_ds, batch_size=args.batch_size,
            shuffle=False, num_workers=0,
        )

        model = TinyTCN(in_ch=2, base=args.base, num_classes=1, p_drop=args.p_drop).to(device)

        criterion = nn.BCEWithLogitsLoss(
            pos_weight=torch.tensor([pos_weight_val], device=device))
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=args.epochs, eta_min=1e-5)

        scaler = torch.amp.GradScaler() if device == "cuda" else None

        best_auc = 0.0
        best_state = None
        patience_counter = 0
        patience = 15

        for epoch in range(1, args.epochs + 1):
            train_loss = train_one_epoch(model, train_loader, optimizer, criterion, device, scaler)
            val_loss, val_auc, val_f1, _, _ = evaluate(model, val_loader, criterion, device)
            scheduler.step()

            log.info(f"  Epoch {epoch:3d}  "
                     f"train_loss={train_loss:.4f}  "
                     f"val_loss={val_loss:.4f}  "
                     f"val_auc={val_auc:.4f}  "
                     f"val_f1={val_f1:.4f}")

            if val_auc > best_auc:
                best_auc = val_auc
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    log.info(f"  Early stopping at epoch {epoch}")
                    break

        fold_results.append(best_auc)
        log.info(f"  Fold {fold} best val AUC = {best_auc:.4f}")

        suffix = f"_{args.run_id}" if args.run_id else ""

        if fold == 0 and best_state is not None:
            primary_name = f"best_fold0{suffix}.pt"
            out_path = os.path.join(args.out_dir, primary_name)
            torch.save({"model": best_state}, out_path)
            log.info(f"  Saved {primary_name}  →  {out_path}")

        if best_state is not None:
            fold_name = f"best_fold{fold}{suffix}.pt"
            fold_path = os.path.join(args.out_dir, fold_name)
            torch.save({"model": best_state}, fold_path)

    log.info("\n══ Cross-validation summary ══")
    for i, auc in enumerate(fold_results):
        log.info(f"  Fold {i}: AUC = {auc:.4f}")
    log.info(f"  Mean AUC = {np.mean(fold_results):.4f} ± {np.std(fold_results):.4f}")

    suffix = f"_{args.run_id}" if args.run_id else ""
    fold0_path = os.path.join(args.out_dir, f"best_fold0{suffix}.pt")
    if os.path.exists(fold0_path):
        log.info(f"\nReloading {os.path.basename(fold0_path)} for final classification report …")
        checkpoint = torch.load(fold0_path, map_location=device)
        model_final = TinyTCN(in_ch=2, base=args.base, num_classes=1, p_drop=args.p_drop).to(device)
        model_final.load_state_dict(checkpoint["model"])

        skf2 = StratifiedKFold(n_splits=args.n_folds, shuffle=True, random_state=args.seed)
        _, val_idx0 = next(iter(skf2.split(case_ids_sorted, case_labels_arr)))
        val_cases0 = {case_ids_sorted[i] for i in val_idx0}
        val_refs0 = [w for w in all_windows if w.case_id in val_cases0]
        val_ds0 = FhrTocoDataset(val_refs0, augment=False)
        val_loader0 = DataLoader(val_ds0, batch_size=args.batch_size, shuffle=False)

        criterion0 = nn.BCEWithLogitsLoss(
            pos_weight=torch.tensor([pos_weight_val], device=device))
        _, _, _, labels_arr, probs_arr = evaluate(model_final, val_loader0, criterion0, device)
        preds_arr = (probs_arr >= 0.5).astype(int)
        report = classification_report(
            labels_arr, preds_arr,
            target_names=["regular", "hypoxia"],
            output_dict=True,
        )
        log.info("\n" + classification_report(
            labels_arr, preds_arr, target_names=["regular", "hypoxia"]))

        import json
        mean_auc = float(np.mean(fold_results))
        std_auc = float(np.std(fold_results))
        results_summary = {
            "run_id": args.run_id or "baseline",
            "base": args.base,
            "p_drop": args.p_drop,
            "lr": args.lr,
            "stride_sec": args.stride_sec,
            "n_folds": args.n_folds,
            "epochs_max": args.epochs,
            "mean_cv_auc": round(mean_auc, 4),
            "std_cv_auc": round(std_auc, 4),
            "fold_aucs": [round(a, 4) for a in fold_results],
            "val_fold0": {
                "auc": round(roc_auc_score(labels_arr, probs_arr), 4),
                "f1_hypoxia": round(report["hypoxia"]["f1-score"], 4),
                "precision_hypoxia": round(report["hypoxia"]["precision"], 4),
                "recall_hypoxia": round(report["hypoxia"]["recall"], 4),
                "accuracy": round(report["accuracy"], 4),
            },
        }
        run_label = args.run_id or "baseline"
        results_path = os.path.join(args.out_dir, f"results_{run_label}.json")
        with open(results_path, "w") as f:
            json.dump(results_summary, f, indent=2)
        log.info(f"Results saved → {results_path}")


if __name__ == "__main__":
    main()
