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


def fig_two_step(v1: dict, v2: dict, out: Path) -> None:
    """The money shot: how adding salt + fruit/veg closes the gap to official.

    Grouped bars for the two metrics that matter most — grade agreement and
    off-by-one-grade rate — nutrients-only vs the full reconstruction.
    """
    labels = ["grade\nagreement", "grade\nwithin ±1", "exact score\nagreement"]
    step1 = [v1["grade_agreement"], v1["grade_within_one"], v1["exact_score_agreement"]]
    step2 = [v2["grade_agreement"], v2["grade_within_one"], v2["exact_score_agreement"]]
    x = range(len(labels))
    w = 0.38
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    b1 = ax.bar([i - w / 2 for i in x], [s * 100 for s in step1], w,
                label="nutrients only", color="#64748b", edgecolor=BG)
    b2 = ax.bar([i + w / 2 for i in x], [s * 100 for s in step2], w,
                label="+ salt + fruit/veg", color=ACCENT, edgecolor=BG)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("agreement with official grade (%)")
    ax.set_ylim(0, 100)
    ax.set_title("Recovering the two missing inputs closes the gap")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h + 1.5, f"{h:.0f}",
                    ha="center", va="bottom", fontsize=8, color=FG)
    _save(fig, out, "nutriscore_two_step")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("docs/figures"))
    ap.add_argument("--results", type=Path, default=Path("results_nutriscore.json"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.data, low_memory=False)
    print(f"Loaded {len(df):,} products")

    # Two-step validation: nutrients-only, then + salt + fruit/veg.
    val_step1 = N.validation(df)
    has_enrichment = {"salt_100g", "fruits_veg_100g"}.issubset(df.columns)
    val_step2 = N.validation_full(df) if has_enrichment else None
    bias = N.bias_by_group(df, min_group_n=100)
    fig_confusion(df, args.out)
    fig_bias(bias, args.out)
    if val_step2 is not None:
        fig_two_step(val_step1, val_step2, args.out)

    results = {
        "validation_nutrients_only": val_step1,
        "validation_full": val_step2,
        "fill_rates": N.fill_rates(df) if has_enrichment else None,
        "bias_by_group": bias,
    }
    args.results.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    print(f"\nDone. Figures -> {args.out}, numbers -> {args.results}")


if __name__ == "__main__":
    main()
