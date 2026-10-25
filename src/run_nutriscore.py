"""Nutri-Score blind-spot analysis — reproducible run (dark SVG + results).

    python src/run_nutriscore.py --data data/clean_df_col_nrj7.csv \
        --out docs/figures --results results_nutriscore.json

Reconstructs the FSAm-NPS score from the available nutrients, validates it
against the official `nutrition-score-fr_100g`, and maps the systematic error
per food group — the blind spots caused by the two inputs the extract lacks
(sodium, fruit/veg %). Produces:
  1. recon vs official grade confusion heatmap,
  2. mean signed score error per food group (the blind-spot map).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import nutriscore as N

# Portfolio dark theme — data-science "house" azure (#38bdf8).
BG, FG, GRID, ACCENT = "#0b1020", "#e5e9f0", "#243049", "#38bdf8"
plt.rcParams.update({
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "text.color": FG, "axes.labelcolor": FG, "axes.titlecolor": FG,
    "xtick.color": FG, "ytick.color": FG, "axes.edgecolor": GRID,
    "grid.color": GRID, "font.size": 10, "svg.fonttype": "none",
})
_GRADES = list("abcde")


def _save(fig, out: Path, name: str) -> None:
    fig.savefig(out / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)


def fig_confusion(df: pd.DataFrame, out: Path) -> None:
    r = N.reconstruct(df)
    off = r["nutrition_grade_fr"].astype("string").str.lower().str.strip()
    m = off.isin(_GRADES) & r["recon_grade"].isin(_GRADES)
    mat = pd.crosstab(off[m], r.loc[m, "recon_grade"]).reindex(
        index=_GRADES, columns=_GRADES, fill_value=0)
    pct = mat.div(mat.sum(1), axis=0).fillna(0).values
    fig, ax = plt.subplots(figsize=(5.5, 5))
    im = ax.imshow(pct, cmap="cividis", vmin=0, vmax=1)
    ax.set_xticks(range(5))
    ax.set_yticks(range(5))
    ax.set_xticklabels([g.upper() for g in _GRADES])
    ax.set_yticklabels([g.upper() for g in _GRADES])
    ax.set_xlabel("reconstructed grade (nutrients only)")
    ax.set_ylabel("official grade")
    ax.set_title("Where nutrients-only reconstruction lands")
    for i in range(5):
        for j in range(5):
            ax.text(j, i, f"{pct[i, j]*100:.0f}", ha="center", va="center",
                    fontsize=8, color="white" if pct[i, j] < 0.5 else BG)
    fig.colorbar(im, ax=ax, fraction=0.046, label="row-normalised share")
    _save(fig, out, "nutriscore_confusion")


def fig_bias(bias: dict, out: Path) -> None:
    items = sorted(bias.items(), key=lambda kv: kv[1]["mean_error"])
    labels = [k for k, _ in items]
    vals = [v["mean_error"] for _, v in items]
    colors = ["#e74c3c" if v < 0 else "#2ecc71" for v in vals]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.barh(labels, vals, color=colors, edgecolor=BG)
    ax.axvline(0, color=FG, lw=0.8)
    ax.set_xlabel("mean score error  (negative = formula too lenient without salt)")
    ax.set_title("Nutri-Score blind spots by food group")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.3)
    for i, v in enumerate(vals):
        ax.text(v + (0.1 if v >= 0 else -0.1), i, f"{v:+.1f}",
                va="center", ha="left" if v >= 0 else "right", fontsize=8, color=FG)
    _save(fig, out, "nutriscore_bias_by_group")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("docs/figures"))
    ap.add_argument("--results", type=Path, default=Path("results_nutriscore.json"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.data, low_memory=False)
    print(f"Loaded {len(df):,} products")

    val = N.validation(df)
    bias = N.bias_by_group(df, min_group_n=100)
    fig_confusion(df, args.out)
    fig_bias(bias, args.out)

    results = {"validation": val, "bias_by_group": bias}
    args.results.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    print(f"\nDone. Figures -> {args.out}, numbers -> {args.results}")


if __name__ == "__main__":
    main()
