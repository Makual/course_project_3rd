# Fetal hypoxia prediction model training

## Dataset structure

The training data is expected to have the following structure:

```text
training/
  hypoxia/              # 30 hypoxia cases
    <case_id>/
      bpm/              # fetal heart rate CSV files, *_1.csv
      uterus/           # uterine contraction CSV files, *_2.csv
  regular/              # 98 normal cases
    <case_id>/
      bpm/              # fetal heart rate CSV files, *_1.csv
      uterus/           # uterine contraction CSV files, *_2.csv
```

Each CSV file contains two columns:

```text
time_sec,value
```

The original signals are sampled at an irregular rate of about 7.87 Hz

## Preprocessing

### 1. Loading and merging segments

For each case, all CSV files from the `bpm` and `uterus` folders are loaded separately. Files are sorted by name and concatenated in chronological order

The model uses two channels:

- `bpm`: fetal heart rate (FHR)
- `uterus`: uterine contraction signal (TOCO)

### 2. Resampling to 1 Hz

The source signals have irregular timestamps, so both channels are resampled to a uniform 1-second grid using linear interpolation (`numpy.interp`)

### 3. Value clipping

Signals are clipped to remove clear measurement artifacts:

| Channel | Range |
|---|---:|
| FHR | 50 to 210 bpm |
| TOCO | -5 to 100 |

### 4. Windowing

Each case is split into 20-minute windows:

- window size: `1200` points
- stride: `300` points, or 5 minutes

Overlapping windows are used as a simple form of data augmentation.

If a recording is shorter than 1200 seconds, it is padded with edge values, but only if the original recording covers at least 50% of the target window length

### 5. Per-window normalization

Each channel is normalized independently inside each window:

```text
x_norm = (x - mean) / std
```

If the standard deviation is smaller than `1e-6`, it is replaced with `1` to avoid division by very small values

### 6. Final input tensor

The final model input has shape:

```text
(2, 1200)
```

where:

- channel 0 is FHR
- channel 1 is TOCO

## Training augmentations

The following augmentations are applied during training:

| Augmentation | Probability |
|---|---:|
| Time shift by up to ±5 points using `numpy.roll` | 0.5 |
| Gaussian noise, `N(0, 0.02)` | 0.5 |
| TOCO amplitude scaling by `U[0.7, 1.3]` | 0.5 |
| FHR amplitude scaling by `U[0.8, 1.2]` | 0.4 |

## Model architecture

The model is a small Temporal Convolutional Network. It uses dilated 1D convolutions and residual blocks

```text
Stem:    Conv1d(2 -> 48, kernel_size=7)
Block1:  ResidualBlock(48 -> 48,  kernel_size=7, dilation=1)
Block2:  ResidualBlock(48 -> 96,  kernel_size=7, dilation=2)
Pool2:   AvgPool1d(2)
Block3:  ResidualBlock(96 -> 96,  kernel_size=7, dilation=4)
Block4:  ResidualBlock(96 -> 192, kernel_size=7, dilation=8)
Pool4:   AdaptiveAvgPool1d(1)
Head:    Linear(192 -> 96) -> ReLU -> Dropout(0.2) -> Linear(96 -> 1)
```

The model outputs one logit. During inference, a sigmoid is applied to convert it into a hypoxia probability in the range `[0, 1]`.

The model uses `base=48`, which matches the `best_fold0.pt` checkpoint used by the inference code.

## Training setup

The training script uses case-level cross-validation. Splitting is done by `case_id`, not by individual windows, to avoid placing windows from the same recording into both the training and validation sets

Main training settings:

| Setting | Value |
|---|---|
| Split | Stratified K-Fold, `k=5` |
| Loss | `BCEWithLogitsLoss` |
| Positive class weight | `n_negative / n_positive`, about `3.3` for this dataset |
| Optimizer | `AdamW` |
| Learning rate | `3e-4` |
| Weight decay | `1e-4` |
| Scheduler | `CosineAnnealingLR` |
| `T_max` | `60` |
| `eta_min` | `1e-5` |
| Sampler | `WeightedRandomSampler` |
| Early stopping | 15 epochs without validation AUC improvement |
| Checkpoint metric | validation ROC-AUC |
| Max epochs | 60 |

## Output checkpoint

The best checkpoint from fold 0 is saved as:

```text
fastapi/best_fold0.pt
```

```python
{"model": state_dict}
```

## How to run training

```bash
source training_venv/bin/activate

python training/training.py \
  --data_root training \
  --out_dir . \
  --epochs 60 \
  --n_folds 5 \
  --batch_size 16 \
  --lr 3e-4 \
  --base 48
```