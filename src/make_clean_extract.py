"""Produce the physically-clean extract + a biochemical audit report.

    python src/make_clean_extract.py --data data/clean_df_col_nrj7.csv \
        --out data/physically_clean.csv --report results_physical_audit.json

A nutritionist/biochemist's pass over the data: beyond per-column bounds, it
enforces the physical laws a real food must obey — subset hierarchies
(saturated fat ≤ fat, sugars ≤ carbs), mass balance (fat+carb+protein ≤ 100 g),
Atwater energy consistency, and non-empty records. Hard impossibilities are
dropped; Atwater outliers are flagged (kept) because we can't tell which field
is wrong. Writes the clean CSV and a JSON report of every violation count.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import eda as E


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/physically_clean.csv"))
    ap.add_argument("--report", type=Path, default=Path("results_physical_audit.json"))
    args = ap.parse_args()

    df = pd.read_csv(args.data, low_memory=False)
    before = len(df)

    report = E.physical_validity_report(df)

    clean = E.physically_clean(df)
    # Flag (don't drop) Atwater outliers that survive, for downstream review.
    clean = clean.copy()
    clean["atwater_flag"] = E.atwater_inconsistency(clean)
    after = len(clean)

    # Biochemical-only count: the physical-law violations, excluding empty
    # 'ghost' records and unusable names (data-entry artefacts). On crowdsourced
    # dumps the ghosts dominate the raw count, so this is the honest headline.
    n_biochem = int(E.biochemical_violation_mask(df).sum())

    # Bootstrap CIs around the flag rates — answers "how stable are the expert
    # thresholds?" with a distribution-free interval instead of a bare %.
    ci_hard = E.bootstrap_flag_rate(df, which="hard", n_boot=1000, seed=42)
    ci_biochem = E.bootstrap_flag_rate(df, which="biochemical", n_boot=1000, seed=42)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    clean.to_csv(args.out, index=False)

    summary = {
        **report,
        "n_after_clean": int(after),
        "n_removed": int(before - after),
        "pct_removed": round(100 * (before - after) / before, 2),
        "n_biochemical_violations": n_biochem,
        "pct_biochemical": round(100 * n_biochem / before, 3),
        "atwater_flagged_kept": int(clean["atwater_flag"].sum()),
        "bootstrap_hard_rate": ci_hard,
        "bootstrap_biochemical_rate": ci_biochem,
        "output_csv": str(args.out),
    }
    args.report.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"\nClean extract -> {args.out}  ({after:,} / {before:,} products kept)")


if __name__ == "__main__":
    main()
