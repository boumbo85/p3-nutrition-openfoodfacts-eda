"""Build a small, versioned demo sample for the Streamlit app.

The full extract (~20 MB) is gitignored, so the deployed demo needs a light,
committable slice. This keeps ~4,000 products that carry a name, an official
grade and a food group (so the 'healthier alternative' feature works), with
only the columns the app uses. Reproducible (fixed seed).

    python src/make_demo_sample.py --data data/physically_clean.csv \
        --out data/demo_sample.csv --n 4000
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

KEEP = [
    "product_name", "brands", "nutrition_grade_fr", "nutrition-score-fr_100g",
    "energy_100g", "fat_100g", "saturated-fat_100g", "carbohydrates_100g",
    "sugars_100g", "fiber_100g", "proteins_100g",
    "salt_100g", "sodium_100g", "fruits_veg_100g",   # 2026 enrichment inputs
    "pnns_groups_1",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/demo_sample.csv"))
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    df = pd.read_csv(args.data, low_memory=False)
    cols = [c for c in KEEP if c in df.columns]
    sub = df[cols].copy()

    # Keep usable, demo-friendly rows: real name + a real A–E grade + food group.
    # Products graded 'unknown'/'not-applicable' would show an empty official
    # badge in the demo, so they are excluded from the sample (not the analysis).
    grade = sub["nutrition_grade_fr"].astype("string").str.lower().str.strip()
    sub = sub[
        sub["product_name"].astype("string").str.len().ge(2)
        & grade.isin(list("abcde"))
        & sub["pnns_groups_1"].notna()
        & ~sub["pnns_groups_1"].astype("string").str.lower().isin(["unknown", "", "nan"])
    ]
    # Sample proportionally within each food group so every category keeps
    # enough products to offer a healthier alternative.
    n = min(args.n, len(sub))
    sample = (
        sub.groupby("pnns_groups_1", group_keys=False)[cols]
        .apply(lambda g: g.sample(max(1, round(n * len(g) / len(sub))), random_state=args.seed))
    )
    sample.to_csv(args.out, index=False)
    print(f"Demo sample: {len(sample):,} products × {len(cols)} cols -> {args.out}")
    print(sample["pnns_groups_1"].value_counts().to_string())


if __name__ == "__main__":
    main()
