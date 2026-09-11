"""
Merge and filter multiple plant disease image datasets into a single
Jharkhand-focused dataset for training.

Supports:
  - PlantVillage  (38-class, "Crop___Disease" folder naming)
  - PlantDoc      (27-class, "Crop disease" or "Crop healthy" folder naming)
  - Top Agriculture Crop Disease India ("Crop - Disease" folder naming)
  - Wheat Leaf Disease (flat class folders like "septoria", "stripe_rust")
  - Rice Leaf Diseases  (flat class folders like "Bacterial leaf blight")

After running, the output directory will have the standard ImageFolder layout:
    <output>/train/<ClassName>/img_001.jpg
    <output>/val/<ClassName>/img_001.jpg
    <output>/test/<ClassName>/img_001.jpg

Usage:
    python prepare_datasets.py \
        --plantvillage  data/raw/plantvillage \
        --plantdoc      data/raw/plantdoc \
        --wheat         data/raw/wheat_leaf_disease \
        --rice          data/raw/rice_leaf_diseases \
        --output        data/jharkhand_disease_dataset
"""

import argparse
import hashlib
import json
import os
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ──────────────────────────────────────────────────────────────────────────────
# Jharkhand-relevant class mappings
#
# We define a strict canonical mapping from raw folder names (across all
# datasets) to a standardized "Crop___Disease" class name.  Any folder that
# does NOT match a key in these mappings is discarded.
# ──────────────────────────────────────────────────────────────────────────────

# PlantVillage uses "Crop___Disease" format with underscores
PLANTVILLAGE_MAP: Dict[str, str] = {
    # Rice — PlantVillage doesn't have rice; we get it from other datasets
    # Corn / Maize
    "Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot": "Maize___Gray_Leaf_Spot",
    "Corn_(maize)___Common_rust_": "Maize___Common_Rust",
    "Corn_(maize)___Northern_Leaf_Blight": "Maize___Northern_Leaf_Blight",
    "Corn_(maize)___healthy": "Maize___Healthy",
    # Potato
    "Potato___Early_blight": "Potato___Early_Blight",
    "Potato___Late_blight": "Potato___Late_Blight",
    "Potato___healthy": "Potato___Healthy",
    # Tomato
    "Tomato___Bacterial_spot": "Tomato___Bacterial_Spot",
    "Tomato___Early_blight": "Tomato___Early_Blight",
    "Tomato___Late_blight": "Tomato___Late_Blight",
    "Tomato___Leaf_Mold": "Tomato___Leaf_Mold",
    "Tomato___Septoria_leaf_spot": "Tomato___Septoria_Leaf_Spot",
    "Tomato___Spider_mites Two-spotted_spider_mite": "Tomato___Spider_Mites",
    "Tomato___Target_Spot": "Tomato___Target_Spot",
    "Tomato___Tomato_Yellow_Leaf_Curl_Virus": "Tomato___Yellow_Leaf_Curl_Virus",
    "Tomato___Tomato_mosaic_virus": "Tomato___Mosaic_Virus",
    "Tomato___healthy": "Tomato___Healthy",
    # Pepper
    "Pepper,_bell___Bacterial_spot": "Pepper___Bacterial_Spot",
    "Pepper,_bell___healthy": "Pepper___Healthy",
    # Soybean
    "Soybean___healthy": "Soybean___Healthy",
    # Squash
    "Squash___Powdery_mildew": "Squash___Powdery_Mildew",
}

# PlantDoc uses "Crop disease" or "Crop healthy" format with spaces
PLANTDOC_MAP: Dict[str, str] = {
    # Corn / Maize
    "Corn leaf blight": "Maize___Northern_Leaf_Blight",
    "Corn rust leaf": "Maize___Common_Rust",
    "Corn Gray leaf spot": "Maize___Gray_Leaf_Spot",
    "corn healthy": "Maize___Healthy",
    "Corn healthy": "Maize___Healthy",
    # Potato
    "Potato Early blight leaf": "Potato___Early_Blight",
    "Potato leaf early blight": "Potato___Early_Blight",
    "Potato Late blight leaf": "Potato___Late_Blight",
    "Potato leaf late blight": "Potato___Late_Blight",
    "Potato healthy": "Potato___Healthy",
    # Tomato
    "Tomato Early blight leaf": "Tomato___Early_Blight",
    "Tomato leaf early blight": "Tomato___Early_Blight",
    "Tomato Late blight leaf": "Tomato___Late_Blight",
    "Tomato leaf late blight": "Tomato___Late_Blight",
    "Tomato Septoria leaf spot": "Tomato___Septoria_Leaf_Spot",
    "Tomato leaf bacterial spot": "Tomato___Bacterial_Spot",
    "Tomato leaf mosaic virus": "Tomato___Mosaic_Virus",
    "Tomato leaf yellow virus": "Tomato___Yellow_Leaf_Curl_Virus",
    "Tomato mold leaf": "Tomato___Leaf_Mold",
    "Tomato leaf": "Tomato___Healthy",
    "Tomato healthy": "Tomato___Healthy",
    # Pepper
    "Bell pepper leaf spot": "Pepper___Bacterial_Spot",
    "Bell pepper leaf": "Pepper___Healthy",
    # Soybean
    "Soybean leaf": "Soybean___Healthy",
    # Squash
    "Squash Powdery mildew leaf": "Squash___Powdery_Mildew",
}

# India Crop Disease uses "Crop - Disease" or "Crop_Disease" format
INDIA_CROP_MAP: Dict[str, str] = {
    # Rice
    "Rice - Brown Spot": "Rice___Brown_Spot",
    "Rice - Healthy": "Rice___Healthy",
    "Rice - Leaf Blast": "Rice___Leaf_Blast",
    "Rice - Neck Blast": "Rice___Neck_Blast",
    "rice_brownspot": "Rice___Brown_Spot",
    "rice_healthy": "Rice___Healthy",
    "rice_leafblast": "Rice___Leaf_Blast",
    "rice_neckblast": "Rice___Neck_Blast",
    "Rice___Brown_Spot": "Rice___Brown_Spot",
    "Rice___Healthy": "Rice___Healthy",
    "Rice___Leaf_Blast": "Rice___Leaf_Blast",
    "Rice___Neck_Blast": "Rice___Neck_Blast",
    # Maize
    "Maize - Common Rust": "Maize___Common_Rust",
    "Maize - Gray Leaf Spot": "Maize___Gray_Leaf_Spot",
    "Maize - Healthy": "Maize___Healthy",
    "Maize - Northern Leaf Blight": "Maize___Northern_Leaf_Blight",
    "Corn_(maize)___Cercospora_leaf_spot Gray_leaf_spot": "Maize___Gray_Leaf_Spot",
    "Corn_(maize)___Common_rust_": "Maize___Common_Rust",
    "Corn_(maize)___Northern_Leaf_Blight": "Maize___Northern_Leaf_Blight",
    "Corn_(maize)___healthy": "Maize___Healthy",
    # Wheat
    "Wheat - Brown Rust": "Wheat___Brown_Rust",
    "Wheat - Healthy": "Wheat___Healthy",
    "Wheat - Yellow Rust": "Wheat___Yellow_Rust",
    "wheat_brownrust": "Wheat___Brown_Rust",
    "wheat_healthy": "Wheat___Healthy",
    "wheat_yellowrust": "Wheat___Yellow_Rust",
    "Wheat___Brown_Rust": "Wheat___Brown_Rust",
    "Wheat___Healthy": "Wheat___Healthy",
    "Wheat___Yellow_Rust": "Wheat___Yellow_Rust",
    "Brown rust": "Wheat___Brown_Rust",
    "Healthy": "Wheat___Healthy",
    "Loose Smut": "Wheat___Loose_Smut",
    "Yellow rust": "Wheat___Yellow_Rust",
    # Potato
    "Potato - Early Blight": "Potato___Early_Blight",
    "Potato - Healthy": "Potato___Healthy",
    "Potato - Late Blight": "Potato___Late_Blight",
    "Potato___Early_blight": "Potato___Early_Blight",
    "Potato___Late_blight": "Potato___Late_Blight",
    "Potato___healthy": "Potato___Healthy",
    # Tomato (if present)
    "Tomato___Bacterial_spot": "Tomato___Bacterial_Spot",
    "Tomato___Early_blight": "Tomato___Early_Blight",
    "Tomato___Late_blight": "Tomato___Late_Blight",
    "Tomato___healthy": "Tomato___Healthy",
}

# Wheat Leaf Disease dataset (yasserhessein/wheat-disease-dataset-small or kaushik10)
WHEAT_MAP: Dict[str, str] = {
    "Healthy": "Wheat___Healthy",
    "septoria": "Wheat___Septoria",
    "Septoria": "Wheat___Septoria",
    "stripe_rust": "Wheat___Stripe_Rust",
    "yellow_rust": "Wheat___Yellow_Rust",
    "YellowRust": "Wheat___Yellow_Rust",
    "brown_rust": "Wheat___Brown_Rust",
    "BrownRust": "Wheat___Brown_Rust",
    "Mildew": "Wheat___Mildew",
}

# Rice Leaf Diseases dataset — flat class names
RICE_LEAF_MAP: Dict[str, str] = {
    "Bacterial leaf blight": "Rice___Bacterial_Leaf_Blight",
    "BacterialLeafBlight": "Rice___Bacterial_Leaf_Blight",
    "bacterial_leaf_blight": "Rice___Bacterial_Leaf_Blight",
    "Brown spot": "Rice___Brown_Spot",
    "BrownSpot": "Rice___Brown_Spot",
    "brown_spot": "Rice___Brown_Spot",
    "Leaf smut": "Rice___Leaf_Smut",
    "LeafSmut": "Rice___Leaf_Smut",
    "leaf_smut": "Rice___Leaf_Smut",
    "Leaf Blast": "Rice___Leaf_Blast",
    "LeafBlast": "Rice___Leaf_Blast",
    "leaf_blast": "Rice___Leaf_Blast",
    "Rice Blast": "Rice___Leaf_Blast",
    "Blast": "Rice___Leaf_Blast",
    "Healthy": "Rice___Healthy",
    "healthy": "Rice___Healthy",
    "Sheath Blight": "Rice___Sheath_Blight",
    "sheath_blight": "Rice___Sheath_Blight",
    "Hispa": "Rice___Hispa",
    "hispa": "Rice___Hispa",
    "Dead Heart": "Rice___Dead_Heart",
    "dead_heart": "Rice___Dead_Heart",
}

IMAGE_EXTENSIONS: Set[str] = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def file_hash(path: Path) -> str:
    """Return the MD5 hex digest of a file (used for deduplication)."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def find_images(directory: Path) -> List[Path]:
    """Recursively find all image files under a directory."""
    images = []
    for p in directory.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(p)
    return images


def discover_class_dirs(root: Path) -> List[Path]:
    """
    Walk up to 3 levels deep to find leaf directories containing images.
    Many Kaggle datasets nest the actual class folders 1-2 levels down
    (e.g., plantvillage-dataset/PlantVillage/<class>/*.jpg).
    """
    candidates = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = Path(dirpath).relative_to(root).parts
        if len(depth) > 3:
            continue
        has_images = any(
            Path(f).suffix.lower() in IMAGE_EXTENSIONS for f in filenames
        )
        if has_images:
            candidates.append(Path(dirpath))
    return candidates


def process_dataset(
    dataset_dir: Path,
    class_mapping: Dict[str, str],
    source_name: str,
) -> Dict[str, List[Path]]:
    """
    Scans a dataset directory, maps folder names to canonical class names
    using the provided mapping, and returns {canonical_class: [image_paths]}.
    """
    result: Dict[str, List[Path]] = defaultdict(list)

    if not dataset_dir.exists():
        print(f"  [SKIP] {source_name}: directory {dataset_dir} not found")
        return result

    print(f"\n{'='*60}")
    print(f"Processing: {source_name}")
    print(f"Directory:  {dataset_dir}")
    print(f"{'='*60}")

    class_dirs = discover_class_dirs(dataset_dir)
    matched = 0
    skipped_classes = []

    for class_dir in class_dirs:
        raw_name = class_dir.name

        # Try exact match first, then case-insensitive
        canonical = class_mapping.get(raw_name)
        if canonical is None:
            # Try case-insensitive
            for key, val in class_mapping.items():
                if key.lower() == raw_name.lower():
                    canonical = val
                    break

        if canonical is None:
            skipped_classes.append(raw_name)
            continue

        images = [
            p for p in class_dir.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
        ]
        if images:
            result[canonical].extend(images)
            matched += 1
            print(f"  + {raw_name:50s} -> {canonical} ({len(images)} images)")

    if skipped_classes:
        print(f"\n  Skipped {len(skipped_classes)} non-Jharkhand classes:")
        for s in sorted(skipped_classes)[:15]:
            print(f"    - {s}")
        if len(skipped_classes) > 15:
            print(f"    ... and {len(skipped_classes) - 15} more")

    total_imgs = sum(len(v) for v in result.values())
    print(f"\n  Summary: {matched} classes matched, {total_imgs} images collected")
    return result


def deduplicate_images(images: List[Path]) -> List[Path]:
    """Remove duplicate images (by file hash) from a list."""
    seen_hashes: Set[str] = set()
    unique = []
    for img_path in images:
        try:
            h = file_hash(img_path)
            if h not in seen_hashes:
                seen_hashes.add(h)
                unique.append(img_path)
        except Exception:
            unique.append(img_path)  # keep it if we can't hash
    return unique


def stratified_split(
    class_images: Dict[str, List[Path]],
    train_ratio: float = 0.80,
    val_ratio: float = 0.10,
) -> Tuple[Dict[str, List[Path]], Dict[str, List[Path]], Dict[str, List[Path]]]:
    """
    Split each class independently to maintain class proportions.
    Returns (train, val, test) dictionaries.
    """
    train, val, test = {}, {}, {}
    for cls, images in class_images.items():
        random.shuffle(images)
        n = len(images)
        n_train = max(1, int(n * train_ratio))
        n_val = max(1, int(n * val_ratio))

        train[cls] = images[:n_train]
        val[cls] = images[n_train:n_train + n_val]
        test[cls] = images[n_train + n_val:]

        # Ensure test has at least 1 sample
        if not test[cls] and len(val[cls]) > 1:
            test[cls] = [val[cls].pop()]

    return train, val, test


def copy_split(
    split_data: Dict[str, List[Path]],
    split_name: str,
    output_dir: Path,
    source_counter: Counter,
):
    """Copy images to the output directory in ImageFolder layout."""
    total = 0
    for cls, images in split_data.items():
        dest_dir = output_dir / split_name / cls
        dest_dir.mkdir(parents=True, exist_ok=True)
        for i, img_path in enumerate(images):
            # Use index + original extension for clean naming
            ext = img_path.suffix.lower()
            dest_path = dest_dir / f"{cls}_{split_name}_{i:05d}{ext}"
            if not dest_path.exists():
                shutil.copy2(img_path, dest_path)
                total += 1
                source_counter[cls] += 1
    return total


def generate_report(
    class_images: Dict[str, List[Path]],
    train: Dict[str, List[Path]],
    val: Dict[str, List[Path]],
    test: Dict[str, List[Path]],
    output_dir: Path,
):
    """Generate and save a dataset summary report."""
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("JHARKHAND CROP DISEASE DATASET — PREPARATION REPORT")
    report_lines.append("=" * 80)
    report_lines.append("")

    # Class distribution table
    report_lines.append(f"{'Class':<45s} {'Total':>7s} {'Train':>7s} {'Val':>7s} {'Test':>7s}")
    report_lines.append("-" * 80)

    total_all = 0
    class_names_sorted = sorted(class_images.keys())
    for cls in class_names_sorted:
        n_total = len(class_images[cls])
        n_train = len(train.get(cls, []))
        n_val = len(val.get(cls, []))
        n_test = len(test.get(cls, []))
        report_lines.append(f"{cls:<45s} {n_total:>7d} {n_train:>7d} {n_val:>7d} {n_test:>7d}")
        total_all += n_total

    report_lines.append("-" * 80)
    report_lines.append(
        f"{'TOTAL':<45s} {total_all:>7d} "
        f"{sum(len(v) for v in train.values()):>7d} "
        f"{sum(len(v) for v in val.values()):>7d} "
        f"{sum(len(v) for v in test.values()):>7d}"
    )
    report_lines.append("")

    # Crop summary
    crop_counts = Counter()
    for cls in class_names_sorted:
        crop = cls.split("___")[0]
        crop_counts[crop] += len(class_images[cls])

    report_lines.append("Crop-level summary:")
    for crop, count in crop_counts.most_common():
        report_lines.append(f"  {crop:<20s}: {count:>6d} images")

    report_lines.append("")

    # Class imbalance warning
    counts = [len(v) for v in class_images.values()]
    if counts:
        min_c, max_c = min(counts), max(counts)
        ratio = max_c / max(min_c, 1)
        if ratio > 10:
            report_lines.append(f"! SEVERE CLASS IMBALANCE: max/min ratio = {ratio:.1f}x")
            report_lines.append("  The training script will use weighted sampling + focal loss to handle this.")
        elif ratio > 3:
            report_lines.append(f"! MODERATE CLASS IMBALANCE: max/min ratio = {ratio:.1f}x")
            report_lines.append("  The training script will use weighted sampling to handle this.")
        else:
            report_lines.append(f"+ Class balance is reasonable (max/min ratio = {ratio:.1f}x)")

    report_text = "\n".join(report_lines)
    print(f"\n{report_text}")

    # Save report
    report_path = output_dir / "dataset_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\nReport saved to {report_path}")

    # Save class mapping JSON (for training and inference)
    services_dir = Path(__file__).parent.parent / "services"
    services_dir.mkdir(exist_ok=True)
    
    class_mapping_path = services_dir / "disease_classes.json"
    class_list = sorted(class_images.keys())
    mapping = {str(i): name for i, name in enumerate(class_list)}
    with open(class_mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)
    print(f"Class mapping ({len(class_list)} classes) saved to {class_mapping_path}")

    # Save class weights for training
    weights_path = services_dir / "class_weights.json"
    total_samples = sum(len(v) for v in class_images.values())
    n_classes = len(class_list)
    weights = {}
    for i, cls in enumerate(class_list):
        count = len(class_images[cls])
        # Inverse frequency weighting: total / (n_classes * count)
        weights[str(i)] = round(total_samples / (n_classes * max(count, 1)), 4)
    with open(weights_path, "w", encoding="utf-8") as f:
        json.dump(weights, f, indent=2)
    print(f"Class weights saved to {weights_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Merge and filter plant disease datasets for Jharkhand crops"
    )
    parser.add_argument(
        "--plantvillage", type=str,
        default="data/raw/plantvillage",
        help="Path to PlantVillage dataset root"
    )
    parser.add_argument(
        "--plantdoc", type=str,
        default="data/raw/plantdoc",
        help="Path to PlantDoc dataset root"
    )
    parser.add_argument(
        "--india", type=str,
        default="data/raw/india_crop_disease",
        help="Path to Top Agriculture Crop Disease India dataset root"
    )
    parser.add_argument(
        "--wheat", type=str,
        default="data/raw/wheat_leaf_disease",
        help="Path to Wheat Leaf Disease dataset root"
    )
    parser.add_argument(
        "--rice", type=str,
        default="data/raw/rice_leaf_diseases",
        help="Path to Rice Leaf Diseases dataset root"
    )
    parser.add_argument(
        "--output", type=str,
        default="data/jharkhand_disease_dataset",
        help="Output directory for the merged dataset"
    )
    parser.add_argument(
        "--no-dedup", action="store_true",
        help="Skip deduplication (faster, but may have duplicate images)"
    )
    args = parser.parse_args()

    random.seed(42)  # Reproducibility

    # ── Collect images from all sources ──────────────────────────────────
    all_class_images: Dict[str, List[Path]] = defaultdict(list)

    sources = [
        (args.plantvillage, PLANTVILLAGE_MAP, "PlantVillage"),
        (args.plantdoc, PLANTDOC_MAP, "PlantDoc"),
        (args.india, INDIA_CROP_MAP, "Top Agriculture Crop Disease India"),
        (args.wheat, WHEAT_MAP, "Wheat Leaf Disease"),
        (args.rice, RICE_LEAF_MAP, "Rice Leaf Diseases"),
    ]

    found_any = False
    for path_str, mapping, name in sources:
        dataset_path = Path(path_str)
        result = process_dataset(dataset_path, mapping, name)
        for cls, images in result.items():
            all_class_images[cls].extend(images)
        if result:
            found_any = True

    if not found_any:
        print("\n! ERROR: No datasets found! Please download the datasets first.")
        print("   See the implementation plan for download instructions.")
        return

    # ── Deduplicate ──────────────────────────────────────────────────────
    if not args.no_dedup:
        print(f"\n{'='*60}")
        print("Deduplicating images across datasets...")
        print(f"{'='*60}")
        before = sum(len(v) for v in all_class_images.values())
        for cls in all_class_images:
            all_class_images[cls] = deduplicate_images(all_class_images[cls])
        after = sum(len(v) for v in all_class_images.values())
        print(f"  Removed {before - after} duplicates ({before} -> {after} images)")

    # ── Remove classes with too few samples ──────────────────────────────
    MIN_SAMPLES = 10
    removed = []
    for cls in list(all_class_images.keys()):
        if len(all_class_images[cls]) < MIN_SAMPLES:
            removed.append((cls, len(all_class_images[cls])))
            del all_class_images[cls]
    if removed:
        print(f"\n! Removed {len(removed)} classes with fewer than {MIN_SAMPLES} images:")
        for cls, count in removed:
            print(f"  - {cls} ({count} images)")

    # ── Split ────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Splitting into train / val / test (80 / 10 / 10)...")
    print(f"{'='*60}")
    train, val, test = stratified_split(all_class_images)

    # ── Copy to output directory ─────────────────────────────────────────
    output_dir = Path(args.output)
    if output_dir.exists():
        print(f"\n! Output directory {output_dir} already exists. Cleaning...")
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    source_counter = Counter()

    n_train = copy_split(train, "train", output_dir, source_counter)
    n_val = copy_split(val, "val", output_dir, source_counter)
    n_test = copy_split(test, "test", output_dir, source_counter)

    print(f"\n  Copied {n_train} train + {n_val} val + {n_test} test = {n_train + n_val + n_test} total images")

    # ── Report ───────────────────────────────────────────────────────────
    generate_report(all_class_images, train, val, test, output_dir)

    print(f"\n+ Dataset prepared at: {output_dir.absolute()}")
    print(f"   Next step: python train_disease.py --data_dir {args.output}")


if __name__ == "__main__":
    main()
