"""Nutri-Score explorer — interactive demo for the P3 project.

Pick a product and see, side by side:
  * its official Nutri-Score grade vs the grade reconstructed from nutrients,
  * the nutrients that drive the score (the official points breakdown),
  * a healthier alternative from the same food category.

Run locally:
    streamlit run app/streamlit_app.py

The heavy lifting lives in ``src/nutriscore.py`` and ``src/eda.py`` (pure,
unit-tested) — this file is only the UI layer. Loads the physically-clean
extract so every product shown has passed the biochemical validation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import nutriscore as N  # noqa: E402

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
# Prefer the full clean extract locally; fall back to the small versioned
# sample that ships with the repo (so the deployed demo works without the
# gitignored 20 MB file).
_CANDIDATES = ["physically_clean.csv", "clean_df_col_nrj7.csv", "demo_sample.csv"]
GRADE_COLORS = {"a": "#2ecc71", "b": "#a3d65c", "c": "#f5c518", "d": "#f08a24", "e": "#e74c3c"}


@st.cache_data
def load() -> pd.DataFrame:
    for name in _CANDIDATES:
        p = _DATA_DIR / name
        if p.exists():
            df = pd.read_csv(p, low_memory=False)
            df = df[df["product_name"].astype("string").str.len() >= 2]
            return N.reconstruct(df)
    st.error("No dataset found in data/ (expected demo_sample.csv at least).")
    st.stop()


def grade_badge(grade: str) -> str:
    g = str(grade).lower().strip()
    color = GRADE_COLORS.get(g, "#888")
    return (f"<span style='background:{color};color:#0b1020;font-weight:700;"
            f"padding:4px 14px;border-radius:8px;font-size:1.6rem'>{g.upper()}</span>")


def points_table(row: pd.Series) -> pd.DataFrame:
    """The official points breakdown — what drives this product's score."""
    def num(c):
        return pd.to_numeric(pd.Series([row.get(c)]), errors="coerce").iloc[0]
    neg = {
        "Energy": N._ladder_points(num("energy_100g"), N._ENERGY_KJ),
        "Sugars": N._ladder_points(num("sugars_100g"), N._SUGARS_G),
        "Saturated fat": N._ladder_points(num("saturated-fat_100g"), N._SATFAT_G),
    }
    pos = {
        "Fibre": N.fibre_points(num("fiber_100g")),
        "Protein": N.protein_points(num("proteins_100g")),
    }
    rows = [{"Component": k, "Effect": "penalty (+)", "Points": v} for k, v in neg.items()]
    rows += [{"Component": k, "Effect": "bonus (−)", "Points": v} for k, v in pos.items()]
    return pd.DataFrame(rows)


def main() -> None:
    st.set_page_config(page_title="Nutri-Score explorer", page_icon="🥗", layout="wide")
    st.title("🥗 Nutri-Score explorer")
    st.caption("Official grade vs. nutrients-only reconstruction — and a healthier swap. "
               "Built on the physically-clean Open Food Facts extract (P3).")

    df = load()

    with st.sidebar:
        st.header("Pick a product")
        query = st.text_input("Search by name", "")
        pool = df
        if query.strip():
            pool = df[df["product_name"].astype("string").str.contains(query, case=False, na=False)]
        if pool.empty:
            st.warning("No product matches.")
            st.stop()
        choice = st.selectbox(
            "Product",
            pool.index,
            format_func=lambda i: str(pool.loc[i, "product_name"])[:60],
        )

    row = df.loc[choice]
    st.subheader(str(row["product_name"]))

    c1, c2, c3 = st.columns(3)
    official = str(row.get("nutrition_grade_fr", "")).lower().strip()
    recon = str(row.get("recon_grade", "")).lower().strip()
    with c1:
        st.markdown("**Official grade**")
        st.markdown(grade_badge(official), unsafe_allow_html=True)
    with c2:
        st.markdown("**Reconstructed (nutrients only)**")
        st.markdown(grade_badge(recon), unsafe_allow_html=True)
    with c3:
        off_s = pd.to_numeric(pd.Series([row.get("nutrition-score-fr_100g")]), errors="coerce").iloc[0]
        delta = None if pd.isna(off_s) else int(row["recon_score"] - off_s)
        st.metric("Reconstructed score", int(row["recon_score"]),
                  delta=None if delta is None else f"{delta:+d} vs official",
                  help="Positive = our nutrients-only score is harsher than the official one "
                       "(usually because salt and fruit/veg % are missing).")

    st.divider()
    left, right = st.columns([1, 1])
    with left:
        st.markdown("#### What drives the score")
        st.dataframe(points_table(row), hide_index=True, use_container_width=True)
    with right:
        st.markdown("#### A healthier option, same category")
        alt = N.healthier_alternative(df, choice, n=3)
        if alt.empty:
            st.info("Already among the best in its category — no healthier swap found.")
        else:
            show = alt[["product_name", "nutrition_grade_fr", "nutrition-score-fr_100g"]].copy()
            show.columns = ["Product", "Grade", "Official score"]
            st.dataframe(show, hide_index=True, use_container_width=True)

    st.divider()
    st.caption("Reconstruction uses the public 2017 FSAm-NPS grid. It omits salt and "
               "fruit/vegetable %, which Open Food Facts does not provide here — the source "
               "of the systematic gap with the official grade.")


if __name__ == "__main__":
    main()
