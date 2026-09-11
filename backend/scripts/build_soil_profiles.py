"""
Turns the Jharkhand Soil Nutrient Analysis export (Soil Health Card programme,
data.gov.in) into a per-village soil profile usable by the crop recommendation
model and by the app's village auto-fill.

WHAT THE RAW FILE ACTUALLY IS
-----------------------------
The export is in *long* format: one row per
(year x village x nutrient x nutrient_level), and `value` is the NUMBER OF SOIL
SAMPLES that fell into that level - not a measurement. So a single village
legitimately produces ~29 rows, e.g. for village "Ara" (Chatra, 2024-25):

    Nitrogen  Low     11      <- 11 samples tested Low
    Nitrogen  Medium  10
    Nitrogen  High     0

Those rows share state/district/block/village and differ only in
nutrient_name/nutrient_level/value. They look like duplicates but they are a
histogram - dropping them would destroy the distribution. There are in fact
ZERO exact duplicate rows in the export (asserted below). The correct operation
is to PIVOT them into one row per village, which is what this script does.

LEVEL -> NUMERIC CALIBRATION
----------------------------
The Soil Health Card reports categories (Low/Medium/High), while the crop
recommendation model consumes continuous N/P/K on the scale of the Kaggle
crop_recommendation dataset. Those two are not in the same units and there is
no published conversion between them, so we anchor by DISTRIBUTION rather than
pretend a unit conversion exists: "Low" maps to the 15th percentile of that
feature in the model's own training data, "Medium" to the 50th, "High" to the
85th. A village's value is then the sample-count-weighted average of the
anchors, which yields a smooth continuous value per village instead of only
three discrete ones.

pH is handled differently: it is a genuine physical scale shared by both
datasets, so Acidic/Neutral/Alkaline map to real agronomic pH values for
Jharkhand's laterite/red soils rather than to percentiles.

Outputs:
  data/jharkhand_village_soil.csv        - full per-village table (analysis)
  ml_models/crop-recommendation/jharkhand_soil_profiles.json  - API lookup
"""

import json
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).parent
RAW_CSV = BASE_DIR / "data" / "raw" / "soil_nutrient_analysis_jharkhand.csv"
BASE_CROP_CSV = BASE_DIR / "data" / "crop_recommendation_base.csv"
VILLAGE_CSV_OUT = BASE_DIR / "data" / "jharkhand_village_soil.csv"
PROFILES_JSON_OUT = (
    BASE_DIR.parent / "ml_models" / "crop-recommendation" / "jharkhand_soil_profiles.json"
)

# Prefer the most recent survey year; fall back to the older one for villages
# that were only surveyed then (keeps village coverage at its maximum).
YEAR_PRIORITY = ["2024-25", "2023-24"]

# Percentile anchors used to place Low/Medium/High on the model's feature scale.
ANCHOR_PERCENTILES = {"Low": 0.15, "Medium": 0.50, "High": 0.85}

# pH is a real shared scale, so these are agronomic values, not percentiles.
# Jharkhand is dominated by acidic laterite/red soil (ICAR Ranchi soil surveys).
PH_ANCHORS = {"Acidic": 5.3, "Neutral": 6.8, "Alkaline": 7.8}

# Soil Health Card organic carbon bands (%), used for display only.
OC_ANCHORS = {"Low": 0.35, "Medium": 0.60, "High": 0.90}

# nutrient_name in the export -> model feature name
MACRO_TO_FEATURE = {"Nitrogen": "N", "Phosphorus": "P", "Potassium": "K"}

# Micronutrients reported as Deficient/Sufficient; we keep the % deficient.
MICRONUTRIENTS = ["Zinc", "Iron", "Boron", "Copper", "Manganese", "Sulphur"]


def load_raw() -> pd.DataFrame:
    df = pd.read_csv(RAW_CSV)
    # Header cells look like "State Name (state_name)" - keep the snake_case part.
    df.columns = [c.split("(")[-1].rstrip(")").strip() for c in df.columns]

    before = len(df)
    df = df.drop_duplicates()
    print(f"Raw rows: {before:,}  |  exact duplicate rows removed: {before - len(df):,}")

    # A (year, village, nutrient, level) key must be unique - if it is not, the
    # same histogram bucket was reported twice and the counts need summing.
    key = ["year", "village_code", "nutrient_name", "nutrient_level"]
    dupe_keys = df.duplicated(subset=key).sum()
    if dupe_keys:
        print(f"  collapsing {dupe_keys:,} repeated histogram buckets by summing counts")
        df = df.groupby(key, as_index=False).agg(
            {
                "state_name": "first",
                "state_code": "first",
                "district_name": "first",
                "district_code": "first",
                "block_name": "first",
                "block_code": "first",
                "village_name": "first",
                "nutrient_type": "first",
                "value": "sum",
            }
        )
    return df


def compute_anchors() -> dict[str, dict[str, float]]:
    """Percentile anchors for N/P/K taken from the model's own training data."""
    base = pd.read_csv(BASE_CROP_CSV)
    anchors = {}
    for feature in ("N", "P", "K"):
        anchors[feature] = {
            level: round(float(base[feature].quantile(q)), 2)
            for level, q in ANCHOR_PERCENTILES.items()
        }
    return anchors


def weighted_value(counts: dict[str, float], anchors: dict[str, float]) -> float | None:
    """Sample-count-weighted average of the level anchors."""
    total = sum(counts.get(level, 0.0) for level in anchors)
    if total <= 0:
        return None
    return sum(anchors[level] * counts.get(level, 0.0) for level in anchors) / total


def share(counts: dict[str, float], level: str, levels: list[str]) -> float | None:
    total = sum(counts.get(x, 0.0) for x in levels)
    if total <= 0:
        return None
    return round(counts.get(level, 0.0) / total * 100, 1)


def build_profiles(df: pd.DataFrame, anchors: dict[str, dict[str, float]]) -> pd.DataFrame:
    # counts[village-year][nutrient][level] = number of samples
    pivot = df.pivot_table(
        index=["year", "state_name", "district_name", "district_code",
               "block_name", "block_code", "village_name", "village_code"],
        columns=["nutrient_name", "nutrient_level"],
        values="value",
        aggfunc="sum",
        fill_value=0,
    )
    print(f"Pivoted to {len(pivot):,} village-year rows x {pivot.shape[1]} level columns")

    def get(row, nutrient: str, level: str) -> float:
        return float(row.get((nutrient, level), 0.0))

    records = []
    for idx, row in pivot.iterrows():
        (year, state_name, district_name, district_code,
         block_name, block_code, village_name, village_code) = idx

        rec = {
            "year": year,
            "state_name": state_name,
            "district_name": district_name,
            "district_code": int(district_code),
            "block_name": block_name,
            "block_code": int(block_code),
            "village_name": village_name,
            "village_code": int(village_code),
        }

        # --- N / P / K on the model's feature scale ---
        for nutrient, feature in MACRO_TO_FEATURE.items():
            counts = {lvl: get(row, nutrient, lvl) for lvl in ("Low", "Medium", "High")}
            rec[feature] = weighted_value(counts, anchors[feature])
            for lvl in ("Low", "Medium", "High"):
                rec[f"{feature}_{lvl.lower()}_pct"] = share(counts, lvl, ["Low", "Medium", "High"])
            rec[f"{feature}_samples"] = int(sum(counts.values()))

        # --- pH on the real pH scale ---
        ph_counts = {lvl: get(row, "Soil Ph", lvl) for lvl in PH_ANCHORS}
        rec["ph"] = weighted_value(ph_counts, PH_ANCHORS)
        for lvl in PH_ANCHORS:
            rec[f"ph_{lvl.lower()}_pct"] = share(ph_counts, lvl, list(PH_ANCHORS))
        rec["ph_samples"] = int(sum(ph_counts.values()))

        # --- organic carbon (display only) ---
        oc_counts = {lvl: get(row, "Organic Carbon", lvl) for lvl in OC_ANCHORS}
        rec["organic_carbon_pct"] = weighted_value(oc_counts, OC_ANCHORS)

        # --- micronutrients: % of samples deficient ---
        deficient = []
        for micro in MICRONUTRIENTS:
            counts = {
                "Deficient": get(row, micro, "Deficient"),
                "Sufficient": get(row, micro, "Sufficient"),
            }
            pct = share(counts, "Deficient", ["Deficient", "Sufficient"])
            rec[f"{micro.lower()}_deficient_pct"] = pct
            if pct is not None and pct >= 50:
                deficient.append(micro)
        rec["deficient_micronutrients"] = ",".join(deficient)

        # --- salinity ---
        ec_counts = {
            "Saline": get(row, "Electrical Conductivity", "Saline"),
            "Non Saline": get(row, "Electrical Conductivity", "Non Saline"),
        }
        rec["saline_pct"] = share(ec_counts, "Saline", ["Saline", "Non Saline"])

        rec["total_samples"] = int(row.sum())
        records.append(rec)

    out = pd.DataFrame(records)

    # Villages with no usable macro/pH readings cannot fill the form - drop them.
    before = len(out)
    out = out.dropna(subset=["N", "P", "K", "ph"])
    print(f"Dropped {before - len(out)} village-year rows with no usable N/P/K/pH samples")

    # Keep one row per village: newest surveyed year wins.
    out["_year_rank"] = out["year"].apply(
        lambda y: YEAR_PRIORITY.index(y) if y in YEAR_PRIORITY else len(YEAR_PRIORITY)
    )
    out = out.sort_values(["village_code", "_year_rank"]).drop_duplicates(
        subset=["village_code"], keep="first"
    )
    out = out.drop(columns=["_year_rank"]).reset_index(drop=True)

    return out


def main() -> None:
    df = load_raw()
    print(f"Coverage: {df.district_name.nunique()} districts, "
          f"{df.block_code.nunique()} blocks, {df.village_code.nunique():,} villages, "
          f"years {sorted(df.year.unique())}")

    anchors = compute_anchors()
    print("\nLevel -> feature-scale anchors (from crop_recommendation_base.csv percentiles):")
    for feature, a in anchors.items():
        print(f"  {feature}: " + ", ".join(f"{lvl}={val}" for lvl, val in a.items()))
    print(f"  ph: " + ", ".join(f"{lvl}={val}" for lvl, val in PH_ANCHORS.items()) + "  (agronomic)")
    print()

    profiles = build_profiles(df, anchors)
    print(f"\nFinal: {len(profiles):,} villages with a usable soil profile")
    print(profiles["year"].value_counts().to_string())

    print("\nDerived feature distribution across villages:")
    print(profiles[["N", "P", "K", "ph", "organic_carbon_pct"]].describe().round(2).to_string())

    VILLAGE_CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    profiles.to_csv(VILLAGE_CSV_OUT, index=False)
    print(f"\nWrote village soil table -> {VILLAGE_CSV_OUT}")

    # Compact nested lookup for the API: district -> block -> [villages]
    lookup: dict = {}
    for rec in profiles.to_dict("records"):
        d = lookup.setdefault(rec["district_name"], {})
        b = d.setdefault(rec["block_name"], [])
        b.append(
            {
                "village_name": rec["village_name"],
                "village_code": rec["village_code"],
                "year": rec["year"],
                "N": round(rec["N"]),
                "P": round(rec["P"]),
                "K": round(rec["K"]),
                "ph": round(rec["ph"], 2),
                "organic_carbon": (
                    round(rec["organic_carbon_pct"], 2)
                    if pd.notna(rec["organic_carbon_pct"]) else None
                ),
                "ph_acidic_pct": rec["ph_acidic_pct"],
                "n_low_pct": rec["N_low_pct"],
                "p_low_pct": rec["P_low_pct"],
                "k_low_pct": rec["K_low_pct"],
                "deficient_micronutrients": (
                    rec["deficient_micronutrients"].split(",")
                    if rec["deficient_micronutrients"] else []
                ),
                "samples": rec["total_samples"],
            }
        )
    for d in lookup.values():
        for name, villages in d.items():
            villages.sort(key=lambda v: v["village_name"])

    PROFILES_JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(PROFILES_JSON_OUT, "w") as f:
        json.dump(lookup, f, separators=(",", ":"))
    size_mb = PROFILES_JSON_OUT.stat().st_size / 1e6
    print(f"Wrote API lookup -> {PROFILES_JSON_OUT} ({size_mb:.1f} MB, "
          f"{len(lookup)} districts)")


if __name__ == "__main__":
    main()
