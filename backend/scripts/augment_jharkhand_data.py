"""
Augments the base Crop-AI crop_recommendation dataset with rows that reflect
Jharkhand's ACTUAL measured growing conditions, so the retrained model leans
toward locally-viable crops instead of only the generalized all-India
distribution.

WHERE THE JHARKHAND CONDITIONS COME FROM
----------------------------------------
Earlier versions of this script invented the local soil profile from a
hard-coded normal distribution (ph ~ N(5.4, 0.55)). It now draws from real
measured soil instead: 12,014 Jharkhand villages derived from the Soil Health
Card "Soil Nutrient Analysis" export by scripts/build_soil_profiles.py. Run
that script first - this one reads data/jharkhand_village_soil.csv.

Villages are sampled in proportion to how many soil samples they contributed,
so districts that were surveyed more heavily carry more weight, matching where
the measurements actually came from.

HOW THE REAL SOIL IS APPLIED
----------------------------
  - ph: taken directly from the sampled village (plus small jitter). pH is a
    soil property independent of which crop is planted, so replacing it
    outright is both safe and the whole point - Jharkhand's laterite/red soils
    are markedly more acidic than the pan-India dataset.

  - N/P/K: blended only PARTWAY toward the village values (see NPK_BLEND).
    These are the features that actually discriminate between crop labels in
    this dataset, so overwriting them with arbitrary village soil would teach
    the model that any crop grows at any nutrient level and destroy the label
    signal. Blending shifts the marginal distribution toward real Jharkhand
    soil while keeping each crop's characteristic N/P/K signature intact.

  - rainfall: the soil export contains no climate data, so rainfall keeps the
    rain-fed monsoon scaling (lower mean, wider spread) used previously.

The script does NOT invent a new crop label - the existing XGBoost label
encoding and the frontend's fixed 22-crop set must stay compatible.
"""

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
rng = np.random.default_rng(SEED)

BASE_DIR = Path(__file__).parent
INPUT_CSV = BASE_DIR / "data" / "crop_recommendation_base.csv"
SOIL_CSV = BASE_DIR / "data" / "jharkhand_village_soil.csv"
OUTPUT_CSV = BASE_DIR / "data" / "crop_recommendation_jharkhand.csv"

# Crops actually grown at meaningful scale in Jharkhand.
JHARKHAND_CROPS = [
    "rice", "maize", "chickpea", "kidneybeans", "pigeonpeas",
    "mungbean", "blackgram", "mothbeans", "lentil", "jute",
]

# How many extra rows to add per Jharkhand crop. Tuned by sweep: 120 leaves the
# rice/jute boundary under-sampled, 300 starts diluting the non-Jharkhand crops.
ROWS_PER_CROP = 200

# How far to pull a crop's N/P/K toward the sampled village's measured soil.
# 0.0 = ignore the real soil entirely, 1.0 = overwrite the crop signature.
NPK_BLEND = 0.30

# Rain-fed monsoon scaling applied to each crop's rainfall.
#
# This band is deliberately narrow. Rice and jute are near-identical in this
# dataset on N/P/K (rice N=79.9/P=47.6/K=39.9 vs jute N=78.4/P=46.9/K=40.0) -
# rainfall is effectively the ONLY feature separating them (rice ~236mm vs jute
# ~175mm). An earlier wide band, N(0.85, 0.18) clipped [0.5, 1.15], inflated
# rice's rainfall spread until it overlapped jute and cost ~25% of rice recall.
# Since rice is roughly 80% of Jharkhand's cropped area, that was the single
# most damaging error the model could make. Narrowing the band still reflects
# lower rain-fed rainfall while preserving the rice/jute separation.
RAIN_SCALE_MEAN, RAIN_SCALE_STD = 0.90, 0.06
RAIN_SCALE_MIN, RAIN_SCALE_MAX = 0.78, 1.02


def load_soil_profiles() -> pd.DataFrame:
    if not SOIL_CSV.exists():
        raise SystemExit(
            f"Missing {SOIL_CSV}.\nRun `python scripts/build_soil_profiles.py` first."
        )
    soil = pd.read_csv(SOIL_CSV)
    soil = soil.dropna(subset=["N", "P", "K", "ph"])
    print(f"Loaded {len(soil):,} village soil profiles from {SOIL_CSV.name}")
    print(f"  measured pH across villages: mean {soil.ph.mean():.2f}, "
          f"min {soil.ph.min():.2f}, max {soil.ph.max():.2f}")
    print(f"  measured N/P/K means: N={soil.N.mean():.1f}, "
          f"P={soil.P.mean():.1f}, K={soil.K.mean():.1f}")
    return soil


def sample_villages(soil: pd.DataFrame, n_rows: int) -> pd.DataFrame:
    """Sample villages weighted by how many soil samples they contributed."""
    weights = soil["total_samples"].clip(lower=1)
    return soil.sample(n=n_rows, replace=True, weights=weights, random_state=SEED)


def augment_crop(df: pd.DataFrame, soil: pd.DataFrame, crop: str, n_rows: int) -> pd.DataFrame:
    crop_rows = df[df["label"] == crop]
    if crop_rows.empty:
        print(f"  skip '{crop}': not present in base dataset")
        return pd.DataFrame(columns=df.columns)

    sampled = crop_rows.sample(n=n_rows, replace=True, random_state=SEED)
    villages = sample_villages(soil, n_rows)

    # pH straight from the measured village soil, with a little jitter so rows
    # aren't exact repeats of the 12k village values.
    new_ph = villages["ph"].to_numpy() + rng.normal(0, 0.12, size=n_rows)
    new_ph = np.clip(new_ph, 3.5, 9.9)

    # Rain-fed monsoon agriculture: pull rainfall down slightly, within a band
    # narrow enough to keep each crop's rainfall signature intact (see the
    # RAIN_SCALE_* comment above).
    rainfall_scale = np.clip(
        rng.normal(RAIN_SCALE_MEAN, RAIN_SCALE_STD, size=n_rows),
        RAIN_SCALE_MIN, RAIN_SCALE_MAX,
    )
    new_rainfall = np.clip(sampled["rainfall"].to_numpy() * rainfall_scale, 20, 300)

    def blend_npk(col: str) -> np.ndarray:
        crop_vals = sampled[col].to_numpy(dtype=float)
        village_vals = villages[col].to_numpy(dtype=float)
        blended = (1 - NPK_BLEND) * crop_vals + NPK_BLEND * village_vals
        noise = rng.normal(0, 0.05, size=n_rows)  # small realistic jitter
        return np.clip(blended * (1 + noise), 0, None)

    def jitter(col: str, pct: float) -> np.ndarray:
        vals = sampled[col].to_numpy(dtype=float)
        return np.clip(vals * (1 + rng.normal(0, pct, size=n_rows)), 0, None)

    return pd.DataFrame({
        "N": blend_npk("N").round(0),
        "P": blend_npk("P").round(0),
        "K": blend_npk("K").round(0),
        "temperature": jitter("temperature", 0.05),
        "humidity": jitter("humidity", 0.05),
        "ph": new_ph,
        "rainfall": new_rainfall,
        "label": crop,
    })


def main() -> None:
    df = pd.read_csv(INPUT_CSV)
    print(f"Base dataset: {len(df)} rows, {df['label'].nunique()} crops")
    soil = load_soil_profiles()

    augmented_frames = [df]
    print(f"\nAugmenting {len(JHARKHAND_CROPS)} Jharkhand-relevant crops with "
          f"{ROWS_PER_CROP} measured-soil rows each (N/P/K blend={NPK_BLEND})...")
    for crop in JHARKHAND_CROPS:
        extra = augment_crop(df, soil, crop, ROWS_PER_CROP)
        augmented_frames.append(extra)
        if not extra.empty:
            print(f"  + {crop}: {len(extra)} rows "
                  f"(ph mean {extra.ph.mean():.2f}, N {extra.N.mean():.0f}, "
                  f"P {extra.P.mean():.0f}, K {extra.K.mean():.0f})")

    final = pd.concat(augmented_frames, ignore_index=True)
    final = final.sample(frac=1.0, random_state=SEED).reset_index(drop=True)  # shuffle

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    final.to_csv(OUTPUT_CSV, index=False)

    print(f"\nWrote {len(final)} rows -> {OUTPUT_CSV}")
    print(f"Dataset pH: base mean {df.ph.mean():.2f} -> augmented mean {final.ph.mean():.2f} "
          f"(shifted toward Jharkhand's acidic soils)")
    print(final["label"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
