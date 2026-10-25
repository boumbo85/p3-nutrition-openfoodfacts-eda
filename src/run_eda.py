"""Reproducible P3 EDA — runs on the cleaned Open Food Facts extract.

Run from the repo root (cleaned CSV in ``data/``):

    python src/run_eda.py --data data/clean_df_col_nrj7.csv --out docs/figures --results results.json

Produces:
  1. a data-quality summary (fill rate per nutrient column),
  2. a sanity-check count of impossible rows still present,
  3. the Nutri-Score grade distribution,
  4. nutrient distributions + a correlation heatmap (the bivariate story).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import eda as E

# ── Portfolio dark theme — matches the data-science "house" (#38bdf8) ──────
BG = "#0b1020"        # night background
FG = "#e5e9f0"        # foreground text
GRID = "#243049"      # subtle grid / spines
ACCENT = "#38bdf8"    # data-science azure
SVG = True            # emit SVG (vector, dark) instead of raster screenshots

_DARK = {
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "text.color": FG, "axes.labelcolor": FG, "axes.titlecolor": FG,
    "xtick.color": FG, "ytick.color": FG,
    "axes.edgecolor": GRID, "grid.color": GRID,
    "font.size": 10, "svg.fonttype": "none",
}
plt.rcParams.update(_DARK)


def _save(fig, out: Path, name: str) -> None:
    """Save a figure as dark SVG (the portfolio uses vectors, not screenshots)."""
    ext = "svg" if SVG else "png"
    fig.savefig(out / f"{name}.{ext}", bbox_inches="tight")
    plt.close(fig)


def fig_grades(df: pd.DataFrame, out: Path) -> dict:
    counts = E.nutriscore_grade_counts(df)
    if counts:
        fig, ax = plt.subplots(figsize=(6, 4))
        # Nutri-Score official-ish ramp, kept legible on the dark background.
        colors = {"a": "#2ecc71", "b": "#a3d65c", "c": "#f5c518",
                  "d": "#f08a24", "e": "#e74c3c"}
        ax.bar(list(counts), list(counts.values()),
               color=[colors.get(g, "#888") for g in counts], edgecolor=BG)
        ax.set_title("Nutri-Score grade distribution")
        ax.set_xlabel("grade")
        ax.set_ylabel("number of products")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.3)
        _save(fig, out, "nutriscore_distribution")
    return counts


def fig_corr(df: pd.DataFrame, out: Path) -> dict:
    cols = [c for c in E.NUTRIENT_COLS if c in df.columns]
    num = df[cols].apply(pd.to_numeric, errors="coerce")
    corr = num.corr()
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(cols)))
    ax.set_yticks(range(len(cols)))
    ax.set_xticklabels([c.replace("_100g", "") for c in cols], rotation=45, ha="right")
    ax.set_yticklabels([c.replace("_100g", "") for c in cols])
    for i in range(len(cols)):
        for j in range(len(cols)):
            v = corr.values[i, j]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center",
                    fontsize=8, color="white" if abs(v) > 0.5 else "#0b1020")
    ax.set_title("Nutrient correlations (per 100g)")
    cb = fig.colorbar(im, ax=ax, fraction=0.046)
    cb.ax.yaxis.set_tick_params(color=FG)
    plt.setp(cb.ax.get_yticklabels(), color=FG)
    _save(fig, out, "nutrient_correlation")
    return {"energy_vs_fat": float(corr.loc["energy_100g", "fat_100g"])
            if "fat_100g" in corr.columns else None}


def fig_eta2(anova: dict, out: Path) -> None:
    """Horizontal bar chart of eta² (variance explained by food group) per nutrient."""
    items = [(k, v["eta2"]) for k, v in anova.items() if v.get("eta2") is not None]
    if not items:
        return
    items.sort(key=lambda kv: kv[1])
    labels = [k.replace("_100g", "") for k, _ in items]
    vals = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.barh(labels, vals, color=ACCENT, edgecolor=BG)
    ax.set_xlim(0, 1)
    ax.set_xlabel("eta² — variance explained by food group")
    ax.set_title("How well does the food group explain each nutrient?")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.3)
    for i, v in enumerate(vals):
        ax.text(v + 0.01, i, f"{v:.2f}", va="center", fontsize=8, color=FG)
    _save(fig, out, "anova_eta2")


def stats_tests(df: pd.DataFrame) -> dict:
    """One-way ANOVA per nutrient + chi² on Nutri-Score grade, all vs food group."""
    anova = {n: E.anova_nutrient_by_group(df, n) for n in E.NUTRIENT_COLS}
    anova = {n: r for n, r in anova.items() if r}
    return {
        "food_group_col": E.GROUP_COL,
        "n_with_food_group": int(E.food_groups(df).notna().sum()),
        "anova_nutrient_by_group": anova,
        "chi2_grade_by_group": E.chi2_grade_by_group(df),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("docs/figures"))
    ap.add_argument("--results", type=Path, default=Path("results.json"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    print("Loading cleaned extract...")
    df = pd.read_csv(args.data, low_memory=False)
    print(f"   {len(df):,} products, {df.shape[1]} columns")

    stats = stats_tests(df)
    fig_eta2(stats["anova_nutrient_by_group"], args.out)

    results = {
        "n_products": int(len(df)),
        "n_columns": int(df.shape[1]),
        "completeness": E.completeness(df, E.NUTRIENT_COLS + ["nutrition_grade_fr"]),
        "impossible_rows_remaining": int(E.flag_impossible_nutrients(df).sum()),
        "sugar_over_carbs_rows": int(E.sugar_consistency(df).sum()),
        "nutriscore_grades": fig_grades(df, args.out),
        "statistical_tests": stats,
    }
    results.update(fig_corr(df, args.out))

    args.results.write_text(json.dumps(results, indent=2))
    print(f"Done. Figures -> {args.out}, numbers -> {args.results}")
    print(json.dumps({k: results[k] for k in
                      ["n_products", "impossible_rows_remaining", "nutriscore_grades"]}, indent=2))


if __name__ == "__main__":
    main()
