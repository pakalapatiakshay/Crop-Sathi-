"""
Train an EfficientNet-B4 for Jharkhand crop disease classification.

Architecture choices (optimised for RTX 5050 + accuracy):
  - EfficientNet-B4 backbone (ImageNet pretrained, via timm)
  - 380×380 input resolution (native for EfficientNet-B4)
  - 2-phase training: frozen backbone → full fine-tuning
  - Focal Loss for class-imbalance robustness
  - CutMix / MixUp augmentation
  - AdamW + cosine-annealing LR schedule
  - Mixed-precision (fp16) training via torch.amp
  - Weighted random sampling to combat class imbalance
  - Early stopping with patience

Usage:
    python train_disease.py --data_dir data/jharkhand_disease_dataset --epochs_phase1 10 --epochs_phase2 20

Outputs:
    models/jharkhand_efficientnet_b4_best.pth   — best checkpoint (by val acc)
    models/disease_classes.json                 — class index → class name mapping
    models/training_report.png                  — confusion matrix + training curves
"""

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
import timm
import torch
import torch.nn as nn
import torch.optim as optim
from torch.cuda.amp import GradScaler, autocast
from torch.optim.lr_scheduler import CosineAnnealingWarmRestarts
from torch.utils.data import DataLoader, WeightedRandomSampler
from torchvision import datasets, transforms
from tqdm import tqdm

# ──────────────────────────────────────────────────────────────────────────────
# Focal Loss — handles class imbalance better than CrossEntropy
# ──────────────────────────────────────────────────────────────────────────────

class FocalLoss(nn.Module):
    """
    Focal Loss (Lin et al., 2017) with optional label smoothing.
    Down-weights well-classified examples so the model focuses on hard cases.
    """
    def __init__(self, alpha: Optional[torch.Tensor] = None, gamma: float = 2.0,
                 label_smoothing: float = 0.1, reduction: str = "mean"):
        super().__init__()
        self.alpha = alpha  # per-class weights
        self.gamma = gamma
        self.label_smoothing = label_smoothing
        self.reduction = reduction

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        n_classes = logits.size(1)
        ce = nn.functional.cross_entropy(
            logits, targets, weight=self.alpha,
            label_smoothing=self.label_smoothing, reduction="none",
        )
        pt = torch.exp(-ce)  # probability of the correct class
        focal = ((1 - pt) ** self.gamma) * ce

        if self.reduction == "mean":
            return focal.mean()
        elif self.reduction == "sum":
            return focal.sum()
        return focal


# ──────────────────────────────────────────────────────────────────────────────
# CutMix / MixUp augmentation
# ──────────────────────────────────────────────────────────────────────────────

def cutmix_data(x: torch.Tensor, y: torch.Tensor, alpha: float = 1.0):
    """Apply CutMix augmentation to a batch."""
    lam = np.random.beta(alpha, alpha)
    batch_size = x.size(0)
    index = torch.randperm(batch_size).to(x.device)

    # Generate random bounding box
    _, _, H, W = x.shape
    cut_ratio = np.sqrt(1.0 - lam)
    cut_h, cut_w = int(H * cut_ratio), int(W * cut_ratio)
    cx, cy = np.random.randint(W), np.random.randint(H)

    x1 = np.clip(cx - cut_w // 2, 0, W)
    x2 = np.clip(cx + cut_w // 2, 0, W)
    y1 = np.clip(cy - cut_h // 2, 0, H)
    y2 = np.clip(cy + cut_h // 2, 0, H)

    x_mixed = x.clone()
    x_mixed[:, :, y1:y2, x1:x2] = x[index, :, y1:y2, x1:x2]

    # Adjust lambda based on actual clipped area
    lam = 1 - ((x2 - x1) * (y2 - y1) / (H * W))

    return x_mixed, y, y[index], lam


def mixup_data(x: torch.Tensor, y: torch.Tensor, alpha: float = 0.4):
    """Apply MixUp augmentation to a batch."""
    lam = np.random.beta(alpha, alpha)
    index = torch.randperm(x.size(0)).to(x.device)
    x_mixed = lam * x + (1 - lam) * x[index]
    return x_mixed, y, y[index], lam


# ──────────────────────────────────────────────────────────────────────────────
# Training loop
# ──────────────────────────────────────────────────────────────────────────────

def train_one_epoch(
    model: nn.Module,
    dataloader: DataLoader,
    criterion: nn.Module,
    optimizer: optim.Optimizer,
    device: torch.device,
    scaler: GradScaler,
    epoch: int,
    use_cutmix: bool = True,
    cutmix_prob: float = 0.5,
) -> Tuple[float, float]:
    """Train for one epoch. Returns (avg_loss, accuracy)."""
    model.train()
    running_loss = 0.0
    running_corrects = 0
    total_samples = 0

    pbar = tqdm(dataloader, desc=f"  Train Epoch {epoch}", leave=False, ncols=100)
    for inputs, labels in pbar:
        inputs = inputs.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        batch_size = inputs.size(0)

        optimizer.zero_grad(set_to_none=True)

        # Stochastically apply CutMix or MixUp
        apply_mix = use_cutmix and np.random.random() < cutmix_prob
        if apply_mix:
            if np.random.random() < 0.5:
                inputs, targets_a, targets_b, lam = cutmix_data(inputs, labels)
            else:
                inputs, targets_a, targets_b, lam = mixup_data(inputs, labels)

        with autocast(device_type="cuda", dtype=torch.float16):
            outputs = model(inputs)
            if apply_mix:
                loss = lam * criterion(outputs, targets_a) + (1 - lam) * criterion(outputs, targets_b)
            else:
                loss = criterion(outputs, labels)

        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        scaler.step(optimizer)
        scaler.update()

        # Statistics
        running_loss += loss.item() * batch_size
        _, preds = torch.max(outputs, 1)
        running_corrects += torch.sum(preds == labels).item()
        total_samples += batch_size

        pbar.set_postfix(loss=f"{loss.item():.4f}")

    avg_loss = running_loss / total_samples
    accuracy = running_corrects / total_samples
    return avg_loss, accuracy


@torch.no_grad()
def evaluate(
    model: nn.Module,
    dataloader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
    desc: str = "  Validate",
) -> Tuple[float, float, list, list]:
    """Evaluate model. Returns (avg_loss, accuracy, all_preds, all_labels)."""
    model.eval()
    running_loss = 0.0
    running_corrects = 0
    total_samples = 0
    all_preds = []
    all_labels = []

    pbar = tqdm(dataloader, desc=desc, leave=False, ncols=100)
    for inputs, labels in pbar:
        inputs = inputs.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)
        batch_size = inputs.size(0)

        with autocast(device_type="cuda", dtype=torch.float16):
            outputs = model(inputs)
            loss = criterion(outputs, labels)

        running_loss += loss.item() * batch_size
        _, preds = torch.max(outputs, 1)
        running_corrects += torch.sum(preds == labels).item()
        total_samples += batch_size

        all_preds.extend(preds.cpu().numpy())
        all_labels.extend(labels.cpu().numpy())

    avg_loss = running_loss / total_samples
    accuracy = running_corrects / total_samples
    return avg_loss, accuracy, all_preds, all_labels


def generate_training_report(
    train_losses: list,
    train_accs: list,
    val_losses: list,
    val_accs: list,
    all_preds: list,
    all_labels: list,
    class_names: list,
    output_dir: str,
    phase1_epochs: int,
):
    """Generate and save training curves + confusion matrix."""
    fig, axes = plt.subplots(1, 3, figsize=(24, 8))

    # Loss curves
    axes[0].plot(train_losses, label="Train Loss", linewidth=2)
    axes[0].plot(val_losses, label="Val Loss", linewidth=2)
    if phase1_epochs > 0 and phase1_epochs < len(train_losses):
        axes[0].axvline(x=phase1_epochs - 1, color="red", linestyle="--",
                        alpha=0.7, label="Phase 2 Start")
    axes[0].set_xlabel("Epoch")
    axes[0].set_ylabel("Loss")
    axes[0].set_title("Training & Validation Loss")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    # Accuracy curves
    axes[1].plot(train_accs, label="Train Acc", linewidth=2)
    axes[1].plot(val_accs, label="Val Acc", linewidth=2)
    if phase1_epochs > 0 and phase1_epochs < len(train_accs):
        axes[1].axvline(x=phase1_epochs - 1, color="red", linestyle="--",
                        alpha=0.7, label="Phase 2 Start")
    axes[1].set_xlabel("Epoch")
    axes[1].set_ylabel("Accuracy")
    axes[1].set_title("Training & Validation Accuracy")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    # Confusion matrix (from final test evaluation)
    n_classes = len(class_names)
    cm = np.zeros((n_classes, n_classes), dtype=int)
    for pred, label in zip(all_preds, all_labels):
        cm[label][pred] += 1

    # Truncate long class names for readability
    short_names = [n.replace("___", "\n") for n in class_names]

    sns.heatmap(
        cm, annot=True if n_classes <= 25 else False,
        fmt="d", cmap="Blues", ax=axes[2],
        xticklabels=short_names, yticklabels=short_names,
    )
    axes[2].set_xlabel("Predicted")
    axes[2].set_ylabel("True")
    axes[2].set_title("Confusion Matrix (Test Set)")
    plt.setp(axes[2].get_xticklabels(), rotation=45, ha="right", fontsize=6)
    plt.setp(axes[2].get_yticklabels(), rotation=0, fontsize=6)

    plt.tight_layout()
    report_path = os.path.join(output_dir, "confusion_matrix.png")
    plt.savefig(report_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"\n📊 Training report saved to {report_path}")

    # Per-class precision, recall, F1
    print(f"\n{'='*80}")
    print("PER-CLASS METRICS (Test Set)")
    print(f"{'='*80}")
    print(f"{'Class':<45s} {'Prec':>7s} {'Recall':>7s} {'F1':>7s} {'Support':>8s}")
    print("-" * 80)

    precisions, recalls, f1s, supports = [], [], [], []
    for i, cls in enumerate(class_names):
        tp = cm[i][i]
        fp = cm[:, i].sum() - tp
        fn = cm[i, :].sum() - tp
        support = cm[i, :].sum()

        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-8)

        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)
        supports.append(support)

        print(f"{cls:<45s} {precision:>7.4f} {recall:>7.4f} {f1:>7.4f} {support:>8d}")

    # Weighted averages
    total_support = sum(supports)
    if total_support > 0:
        w_prec = sum(p * s for p, s in zip(precisions, supports)) / total_support
        w_rec = sum(r * s for r, s in zip(recalls, supports)) / total_support
        w_f1 = sum(f * s for f, s in zip(f1s, supports)) / total_support
        print("-" * 80)
        print(f"{'WEIGHTED AVG':<45s} {w_prec:>7.4f} {w_rec:>7.4f} {w_f1:>7.4f} {total_support:>8d}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Train EfficientNet-B4 for Jharkhand crop disease detection"
    )
    parser.add_argument("--data_dir", type=str, default="data/jharkhand_disease_dataset",
                        help="Path to prepared dataset (output of prepare_datasets.py)")
    parser.add_argument("--epochs_phase1", type=int, default=10,
                        help="Epochs for Phase 1 (frozen backbone)")
    parser.add_argument("--epochs_phase2", type=int, default=20,
                        help="Epochs for Phase 2 (full fine-tuning)")
    parser.add_argument("--batch_size", type=int, default=16,
                        help="Batch size (16 works well for EfficientNet-B4 on 8GB VRAM)")
    parser.add_argument("--lr_phase1", type=float, default=1e-3,
                        help="Learning rate for Phase 1 (head only)")
    parser.add_argument("--lr_phase2", type=float, default=1e-4,
                        help="Max learning rate for Phase 2 (full model)")
    parser.add_argument("--patience", type=int, default=7,
                        help="Early stopping patience (epochs without improvement)")
    parser.add_argument("--output_dir", type=str, default=".",
                        help="Directory to save model checkpoints and reports")
    parser.add_argument("--resume", type=str, default=None,
                        help="Path to checkpoint to resume training from")
    parser.add_argument("--workers", type=int, default=4,
                        help="Number of data loading workers")
    parser.add_argument("--img_size", type=int, default=380,
                        help="Input image resolution (380 for EfficientNet-B4)")
    parser.add_argument("--no-cutmix", action="store_true",
                        help="Disable CutMix/MixUp augmentation")
    args = parser.parse_args()

    # ── Validate ─────────────────────────────────────────────────────────
    if not os.path.exists(args.data_dir):
        print(f"❌ Dataset directory not found: {args.data_dir}")
        print("   Run prepare_datasets.py first.")
        sys.exit(1)

    for split in ["train", "val"]:
        split_dir = os.path.join(args.data_dir, split)
        if not os.path.exists(split_dir):
            print(f"❌ Missing split directory: {split_dir}")
            sys.exit(1)

    # ── Device setup ─────────────────────────────────────────────────────
    if not torch.cuda.is_available():
        print("⚠ CUDA not available. Training will be VERY slow on CPU.")
        device = torch.device("cpu")
    else:
        device = torch.device("cuda:0")
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_mem / 1e9
        print(f"🖥 GPU: {gpu_name} ({gpu_mem:.1f} GB)")
        torch.backends.cudnn.benchmark = True  # Optimise for fixed input size

    # ── Data transforms ──────────────────────────────────────────────────
    IMG_SIZE = args.img_size
    IMAGENET_MEAN = [0.485, 0.456, 0.406]
    IMAGENET_STD = [0.229, 0.224, 0.225]

    train_transforms = transforms.Compose([
        transforms.RandomResizedCrop(IMG_SIZE, scale=(0.7, 1.0)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomVerticalFlip(p=0.2),
        transforms.RandomRotation(20),
        transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.3, hue=0.1),
        transforms.RandomGrayscale(p=0.05),
        transforms.RandomPerspective(distortion_scale=0.2, p=0.3),
        transforms.GaussianBlur(kernel_size=3, sigma=(0.1, 2.0)),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        transforms.RandomErasing(p=0.15, scale=(0.02, 0.15)),
    ])

    val_transforms = transforms.Compose([
        transforms.Resize(int(IMG_SIZE * 1.15)),  # Slight over-resize
        transforms.CenterCrop(IMG_SIZE),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])

    # ── Load datasets ────────────────────────────────────────────────────
    print(f"\n📂 Loading datasets from {args.data_dir}...")
    train_dataset = datasets.ImageFolder(os.path.join(args.data_dir, "train"), train_transforms)
    val_dataset = datasets.ImageFolder(os.path.join(args.data_dir, "val"), val_transforms)

    test_dir = os.path.join(args.data_dir, "test")
    test_dataset = datasets.ImageFolder(test_dir, val_transforms) if os.path.exists(test_dir) else None

    class_names = train_dataset.classes
    num_classes = len(class_names)

    print(f"  Classes: {num_classes}")
    print(f"  Train:   {len(train_dataset)} images")
    print(f"  Val:     {len(val_dataset)} images")
    if test_dataset:
        print(f"  Test:    {len(test_dataset)} images")

    # ── Weighted sampler for class imbalance ──────────────────────────────
    targets = [s[1] for s in train_dataset.samples]
    class_counts = np.bincount(targets, minlength=num_classes)
    class_weights = 1.0 / np.maximum(class_counts, 1).astype(np.float64)
    sample_weights = [class_weights[t] for t in targets]
    sampler = WeightedRandomSampler(sample_weights, num_samples=len(sample_weights), replacement=True)

    # ── DataLoaders ──────────────────────────────────────────────────────
    loader_kwargs = dict(
        batch_size=args.batch_size,
        num_workers=args.workers,
        pin_memory=True,
        persistent_workers=True if args.workers > 0 else False,
    )
    train_loader = DataLoader(train_dataset, sampler=sampler, drop_last=True, **loader_kwargs)
    val_loader = DataLoader(val_dataset, shuffle=False, **loader_kwargs)
    test_loader = DataLoader(test_dataset, shuffle=False, **loader_kwargs) if test_dataset else None

    # ── Model ────────────────────────────────────────────────────────────
    print(f"\n🏗 Building EfficientNet-B4 ({num_classes} output classes)...")
    model = timm.create_model(
        "efficientnet_b4",
        pretrained=True,
        num_classes=num_classes,
        drop_rate=0.3,
        drop_path_rate=0.2,
    )
    model = model.to(device)

    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Total params:     {total_params:,}")
    print(f"  Trainable params: {trainable_params:,}")

    # ── Loss function ────────────────────────────────────────────────────
    # Load class weights if available
    weights_path = os.path.join(args.data_dir, "class_weights.json")
    if os.path.exists(weights_path):
        with open(weights_path) as f:
            weight_dict = json.load(f)
        alpha = torch.tensor([weight_dict[str(i)] for i in range(num_classes)],
                             dtype=torch.float32).to(device)
        print(f"  Using class weights from {weights_path}")
    else:
        alpha = torch.tensor(class_weights, dtype=torch.float32).to(device)

    # Clamp extreme weights to prevent instability
    alpha = torch.clamp(alpha / alpha.mean(), 0.3, 3.0)

    criterion = FocalLoss(alpha=alpha, gamma=2.0, label_smoothing=0.1)

    # ── Mixed precision scaler ───────────────────────────────────────────
    scaler = GradScaler()

    # ── Training history ─────────────────────────────────────────────────
    all_train_losses, all_train_accs = [], []
    all_val_losses, all_val_accs = [], []
    best_val_acc = 0.0
    best_model_wts = None
    epochs_no_improve = 0
    total_phase1_epochs = 0

    services_dir = os.path.join(os.path.dirname(__file__), "..", "services")
    os.makedirs(services_dir, exist_ok=True)
    model_save_path = os.path.join(services_dir, "jharkhand_efficientnet_b4.pth")

    # ══════════════════════════════════════════════════════════════════════
    # PHASE 1: Freeze backbone, train only the classifier head
    # ══════════════════════════════════════════════════════════════════════
    if args.epochs_phase1 > 0:
        print(f"\n{'='*60}")
        print(f"PHASE 1: Training classifier head ({args.epochs_phase1} epochs)")
        print(f"  Backbone: FROZEN | LR: {args.lr_phase1}")
        print(f"{'='*60}")

        # Freeze all backbone parameters
        for name, param in model.named_parameters():
            if "classifier" not in name and "fc" not in name:
                param.requires_grad = False

        trainable_p1 = sum(p.numel() for p in model.parameters() if p.requires_grad)
        print(f"  Trainable params (Phase 1): {trainable_p1:,}")

        optimizer_p1 = optim.AdamW(
            filter(lambda p: p.requires_grad, model.parameters()),
            lr=args.lr_phase1, weight_decay=1e-4,
        )
        scheduler_p1 = CosineAnnealingWarmRestarts(optimizer_p1, T_0=5, T_mult=1, eta_min=1e-6)

        for epoch in range(1, args.epochs_phase1 + 1):
            t_loss, t_acc = train_one_epoch(
                model, train_loader, criterion, optimizer_p1, device, scaler,
                epoch, use_cutmix=False,  # No CutMix in Phase 1 for stable head training
            )
            v_loss, v_acc, _, _ = evaluate(model, val_loader, criterion, device)
            scheduler_p1.step()

            all_train_losses.append(t_loss)
            all_train_accs.append(t_acc)
            all_val_losses.append(v_loss)
            all_val_accs.append(v_acc)

            is_best = v_acc > best_val_acc
            if is_best:
                best_val_acc = v_acc
                best_model_wts = copy.deepcopy(model.state_dict())
                epochs_no_improve = 0
            else:
                epochs_no_improve += 1

            marker = " ★ BEST" if is_best else ""
            print(f"  Epoch {epoch:3d} | Train Loss: {t_loss:.4f} Acc: {t_acc:.4f} | "
                  f"Val Loss: {v_loss:.4f} Acc: {v_acc:.4f}{marker}")

        total_phase1_epochs = args.epochs_phase1

    # ══════════════════════════════════════════════════════════════════════
    # PHASE 2: Unfreeze backbone, fine-tune entire model with lower LR
    # ══════════════════════════════════════════════════════════════════════
    if args.epochs_phase2 > 0:
        print(f"\n{'='*60}")
        print(f"PHASE 2: Full fine-tuning ({args.epochs_phase2} epochs)")
        print(f"  Backbone: UNFROZEN | LR: {args.lr_phase2} | Patience: {args.patience}")
        print(f"{'='*60}")

        # Unfreeze all parameters
        for param in model.parameters():
            param.requires_grad = True

        trainable_p2 = sum(p.numel() for p in model.parameters() if p.requires_grad)
        print(f"  Trainable params (Phase 2): {trainable_p2:,}")

        # Differential learning rate: backbone gets 10x lower LR
        backbone_params = []
        head_params = []
        for name, param in model.named_parameters():
            if "classifier" in name or "fc" in name:
                head_params.append(param)
            else:
                backbone_params.append(param)

        optimizer_p2 = optim.AdamW([
            {"params": backbone_params, "lr": args.lr_phase2 * 0.1},  # backbone: 10x lower
            {"params": head_params, "lr": args.lr_phase2},
        ], weight_decay=1e-4)

        scheduler_p2 = CosineAnnealingWarmRestarts(optimizer_p2, T_0=5, T_mult=2, eta_min=1e-7)

        epochs_no_improve = 0  # reset for phase 2

        for epoch in range(1, args.epochs_phase2 + 1):
            t_loss, t_acc = train_one_epoch(
                model, train_loader, criterion, optimizer_p2, device, scaler,
                epoch, use_cutmix=not args.no_cutmix, cutmix_prob=0.4,
            )
            v_loss, v_acc, _, _ = evaluate(model, val_loader, criterion, device)
            scheduler_p2.step()

            all_train_losses.append(t_loss)
            all_train_accs.append(t_acc)
            all_val_losses.append(v_loss)
            all_val_accs.append(v_acc)

            is_best = v_acc > best_val_acc
            if is_best:
                best_val_acc = v_acc
                best_model_wts = copy.deepcopy(model.state_dict())
                # Save checkpoint immediately
                torch.save({
                    "epoch": total_phase1_epochs + epoch,
                    "model_state_dict": best_model_wts,
                    "best_val_acc": best_val_acc,
                    "class_names": class_names,
                    "num_classes": num_classes,
                    "img_size": IMG_SIZE,
                }, model_save_path)
                epochs_no_improve = 0
            else:
                epochs_no_improve += 1

            marker = " ★ BEST" if is_best else ""
            print(f"  Epoch {epoch:3d} | Train Loss: {t_loss:.4f} Acc: {t_acc:.4f} | "
                  f"Val Loss: {v_loss:.4f} Acc: {v_acc:.4f}{marker}")

            # Early stopping
            if epochs_no_improve >= args.patience:
                print(f"\n  ⏹ Early stopping triggered (no improvement for {args.patience} epochs)")
                break

    # ── Load best weights ────────────────────────────────────────────────
    if best_model_wts is not None:
        model.load_state_dict(best_model_wts)

    # Save final best model
    torch.save({
        "model_state_dict": model.state_dict(),
        "best_val_acc": best_val_acc,
        "class_names": class_names,
        "num_classes": num_classes,
        "img_size": IMG_SIZE,
    }, model_save_path)
    print(f"\n💾 Best model saved to {model_save_path} (Val Acc: {best_val_acc:.4f})")

    # Save class mapping
    classes_path = os.path.join(args.output_dir, "disease_classes.json")
    class_mapping = {str(i): name for i, name in enumerate(class_names)}
    with open(classes_path, "w") as f:
        json.dump(class_mapping, f, indent=2)
    print(f"📋 Class mapping ({num_classes} classes) saved to {classes_path}")

    # ── Test evaluation ──────────────────────────────────────────────────
    if test_loader is not None:
        print(f"\n{'='*60}")
        print("FINAL TEST EVALUATION")
        print(f"{'='*60}")

        test_loss, test_acc, test_preds, test_labels = evaluate(
            model, test_loader, criterion, device, desc="  Testing"
        )
        print(f"\n  Test Loss: {test_loss:.4f}")
        print(f"  Test Accuracy: {test_acc:.4f} ({test_acc*100:.2f}%)")
    else:
        print("\n⚠ No test split found — skipping final evaluation.")
        # Use val for report
        _, _, test_preds, test_labels = evaluate(
            model, val_loader, criterion, device, desc="  Evaluating (Val)"
        )

    # ── Generate report ──────────────────────────────────────────────────
    generate_training_report(
        all_train_losses, all_train_accs,
        all_val_losses, all_val_accs,
        test_preds, test_labels,
        class_names, args.output_dir,
        total_phase1_epochs,
    )

    time_total = sum(1 for _ in all_train_losses)  # placeholder
    print(f"\n✅ Training complete!")
    print(f"  Best Val Accuracy: {best_val_acc:.4f} ({best_val_acc*100:.2f}%)")
    print(f"  Model: {model_save_path}")
    print(f"  Classes: {classes_path}")
    print(f"\n  Next step: python export_onnx.py --model_path {model_save_path} --num_classes {num_classes}")


if __name__ == "__main__":
    main()
