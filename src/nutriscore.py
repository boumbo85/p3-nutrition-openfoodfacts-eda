"""Nutri-Score reconstruction & blind-spot analysis (2017 'general food' grid).

The 2026 step-up for P3. The dataset ships the *official* Nutri-Score
(`nutrition-score-fr_100g`) and grade (`nutrition_grade_fr`) — a ground truth.
Here we re-implement the public 2017 formula from the nutrients we have and ask
a sharper question than "can we predict the score" (trivially yes, it's a
formula): **where does the formula have blind spots, and which food groups does
it systematically mis-rank?**

Honest scope — two official inputs are NOT in the cleaned extract:
  * sodium / salt  (a *negative* input: its absence makes our score too low)
  * fruit/vegetable/nut %  (a *positive* input: its absence makes our score too high)
So our reconstruction is deliberately partial. The point is not a perfect
re-score; it is to *measure* how far nutrients-only gets us and to turn the
residual error into a documented critique of the label. Everything here is pure
numpy/pandas (no scipy), unit-testable on tiny frames, matching eda.py's style.

Official 2017 'general food' point grid (per 100 g):
  Negative points N (0–10 each):
    energy_kJ : >3350 →10, then thresholds every 335 kJ down to ≤335 →0
    sugars_g  : >45 →10, steps of 4.5 g down to ≤4.5 →0
    sat_fat_g : >10 →10, steps of 1 g down to ≤1 →0
    (sodium mg: not available here — see blind spot #1)
  Positive points P:
    fibre_g   : >4.7 →5 … ≤0.9 →0   (AOAC thresholds)
    protein_g : >8.0 →5 … ≤1.6 →0
    (fruit/veg %: not available here — see blind spot #2)
  Final score = N − P, with the official rule: if N ≥ 11 and fruit/veg points < 5,
  protein points are NOT subtracted. We flag where that rule is likely to bite.
Grade cutoffs (solid foods): ≤ -1 → a, 0–2 → b, 3–10 → c, 11–18 → d, ≥19 → e.
"""
from __future__ import annotations

import pandas as pd

# ── Official 2017 threshold ladders (upper bound of each band) ──────────────
# Index i => points i; a value strictly above the i-th bound scores i+1.
_ENERGY_KJ = [335, 670, 1005, 1340, 1675, 2010, 2345, 2680, 3015, 3350]
_SUGARS_G = [4.5, 9, 13.5, 18, 22.5, 27, 31, 36, 40, 45]
_SATFAT_G = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
_FIBRE_G = [0.9, 1.9, 2.8, 3.7, 4.7]          # AOAC ladder, 0..5 points
_PROTEIN_G = [1.6, 3.2, 4.8, 6.4, 8.0]        # 0..5 points

GROUP_COL = "pnns_groups_1"


def _ladder_points(value: float, bounds: list[float]) -> int:
    """Points = number of bounds the value strictly exceeds (official step rule)."""
    if value is None or pd.isna(value):
        return 0
    pts = 0
    for b in bounds:
        if value > b:
            pts += 1
        else:
            break
    return pts


def negative_points(energy_kj: float, sugars_g: float, satfat_g: float) -> int:
    """Sum of the three *available* negative inputs (0–30). Sodium is omitted —
    blind spot #1: without salt, salty-but-low-sugar foods score too kindly."""
    return (
        _ladder_points(energy_kj, _ENERGY_KJ)
        + _ladder_points(sugars_g, _SUGARS_G)
        + _ladder_points(satfat_g, _SATFAT_G)
    )


def protein_points(protein_g: float) -> int:
    return _ladder_points(protein_g, _PROTEIN_G)


def fibre_points(fibre_g: float) -> int:
    return _ladder_points(fibre_g, _FIBRE_G)


def nutriscore_points(
    energy_kj: float,
    sugars_g: float,
    satfat_g: float,
    fibre_g: float,
    protein_g: float,
) -> int:
    """Reconstructed FSAm-NPS score from nutrients only (no sodium, no fruit/veg).

    Applies the official protein-exemption rule: when N ≥ 11 (and fruit/veg
    points < 5, which we cannot observe, so we assume the common case), protein
    points are not subtracted. Fruit/veg points are treated as 0 (blind spot #2).
    """
    n = negative_points(energy_kj, sugars_g, satfat_g)
    fib = fibre_points(fibre_g)
    prot = protein_points(protein_g)
    fruit_veg_pts = 0  # not in the data — blind spot #2
    if n >= 11 and fruit_veg_pts < 5:
        return n - (fib + fruit_veg_pts)       # protein NOT subtracted
    return n - (fib + prot + fruit_veg_pts)


# ── Beverage grid (2017) — drinks follow a *different* ladder & cutoffs ─────
# Nutri-Score rates beverages on their own scale: energy and sugars use lower,
# drink-specific thresholds, and only water can score A. Ignoring this is why a
# solid-grid reconstruction rates a sugary soda far too kindly (B instead of E).
_BEV_ENERGY_KJ = [30, 90, 150, 210, 240, 270, 300, 330, 360]   # 0..10 points
_BEV_SUGARS_G = [1.5, 3, 4.5, 6, 7.5, 9, 10.5, 12, 13.5]        # 0..10 points


def beverage_points(energy_kj: float, sugars_g: float, satfat_g: float,
                    fibre_g: float, protein_g: float) -> int:
    """Reconstructed Nutri-Score for a beverage (2017 drink grid).

    Negative points use the drink-specific energy & sugar ladders (much stricter
    than for solids); positive points (fibre, protein) are capped as usual. The
    protein-exemption rule applies the same way.
    """
    n = (_ladder_points(energy_kj, _BEV_ENERGY_KJ)
         + _ladder_points(sugars_g, _BEV_SUGARS_G)
         + _ladder_points(satfat_g, _SATFAT_G))
    fib = fibre_points(fibre_g)
    prot = protein_points(protein_g)
    if n >= 11:
        return n - fib
    return n - (fib + prot)


# Solid-food grade cutoffs (upper bound of each grade band).
_GRADE_BANDS = [(-1, "a"), (2, "b"), (10, "c"), (18, "d")]
# Beverage grade cutoffs: only water scores A; sugary drinks reach E fast.
_BEV_GRADE_BANDS = [(1, "b"), (5, "c"), (9, "d")]


def points_to_grade(points: float, is_beverage: bool = False, is_water: bool = False) -> str:
    """Map a score to a Nutri-Score grade, using the beverage scale if needed.

    Beverages: only water gets A; otherwise ≤1→B, 2–5→C, 6–9→D, ≥10→E.
    """
    if points is None or pd.isna(points):
        return ""
    if is_beverage:
        if is_water:
            return "a"
        for upper, grade in _BEV_GRADE_BANDS:
            if points <= upper:
                return grade
        return "e"
    for upper, grade in _GRADE_BANDS:
        if points <= upper:
            return grade
    return "e"


# ── Vectorised application + validation against the official ground truth ───
_NUM = ["energy_100g", "sugars_100g", "saturated-fat_100g", "fiber_100g", "proteins_100g"]


def _is_beverage(df: pd.DataFrame) -> pd.Series:
    """True where the product is a beverage (uses the drink Nutri-Score grid)."""
    if GROUP_COL not in df.columns:
        return pd.Series(False, index=df.index)
    g = df[GROUP_COL].astype("string").str.lower().str.strip()
    return g.eq("beverages").fillna(False)


def _is_water(df: pd.DataFrame) -> pd.Series:
    """True for plain water (scores A on the beverage grid): ~0 energy & sugar."""
    e = pd.to_numeric(df.get("energy_100g"), errors="coerce").fillna(0)
    s = pd.to_numeric(df.get("sugars_100g"), errors="coerce").fillna(0)
    return _is_beverage(df) & (e <= 10) & (s <= 0.5)


def reconstruct(df: pd.DataFrame) -> pd.DataFrame:
    """Add `recon_score` and `recon_grade`, routing beverages to the drink grid."""
    cols = {c: pd.to_numeric(df[c], errors="coerce") for c in _NUM if c in df.columns}
    out = df.copy()
    bev = _is_beverage(df).tolist()
    scores = []
    for is_bev, e, s, sf, fi, pr in zip(
        bev, cols["energy_100g"], cols["sugars_100g"], cols["saturated-fat_100g"],
        cols["fiber_100g"], cols["proteins_100g"], strict=False,
    ):
        scores.append(beverage_points(e, s, sf, fi, pr) if is_bev
                      else nutriscore_points(e, s, sf, fi, pr))
    out["recon_score"] = scores
    water = _is_water(df).tolist()
    out["recon_grade"] = [
        points_to_grade(sc, is_beverage=b, is_water=w)
        for sc, b, w in zip(scores, bev, water, strict=False)
    ]
    return out


def validation(df: pd.DataFrame) -> dict:
    """Compare reconstruction to the official score/grade (ground-truth rows only).

    Returns exact-score agreement, mean absolute error, signed bias (are we
    systematically too generous or too harsh — the fingerprint of the missing
    inputs), and grade agreement / off-by-one-grade rate.
    """
    r = reconstruct(df)
    off = pd.to_numeric(r.get("nutrition-score-fr_100g"), errors="coerce")
    grade = r.get("nutrition_grade_fr")
    grade = grade.astype("string").str.lower().str.strip() if grade is not None else None
    m = off.notna() & r["recon_score"].notna()
    if grade is not None:
        m &= grade.isin(list("abcde"))
    sub = r[m]
    off_m = off[m]
    diff = sub["recon_score"] - off_m            # signed: + = we are harsher
    grade_ok = (sub["recon_grade"] == grade[m]).mean() if grade is not None else None
    _ord = {g: i for i, g in enumerate("abcde")}
    off_by1 = None
    if grade is not None:
        d = (sub["recon_grade"].map(_ord) - grade[m].map(_ord)).abs()
        off_by1 = float((d <= 1).mean())
    return {
        "n": int(m.sum()),
        "exact_score_agreement": float((diff == 0).mean()),
        "mae_score": float(diff.abs().mean()),
        "signed_bias": float(diff.mean()),
        "grade_agreement": None if grade_ok is None else float(grade_ok),
        "grade_within_one": off_by1,
    }


def healthier_alternative(df: pd.DataFrame, idx, n: int = 3) -> pd.DataFrame:
    """Suggest healthier products from the same food group as row ``idx``.

    'Healthier' = a better (lower) official Nutri-Score within the same
    ``pnns_groups_1`` category. Returns up to ``n`` candidates sorted by score.
    Pure selection logic (no UI), so it is unit-testable.
    """
    if GROUP_COL not in df.columns or "nutrition-score-fr_100g" not in df.columns:
        return df.iloc[0:0]
    row = df.loc[idx]
    group = row.get(GROUP_COL)
    score = pd.to_numeric(pd.Series([row.get("nutrition-score-fr_100g")]), errors="coerce").iloc[0]
    if pd.isna(group) or pd.isna(score):
        return df.iloc[0:0]
    same = df[df[GROUP_COL] == group].copy()
    same["_s"] = pd.to_numeric(same["nutrition-score-fr_100g"], errors="coerce")
    better = same[(same["_s"] < score) & (same.index != idx)].dropna(subset=["_s"])
    return better.sort_values("_s").head(n).drop(columns="_s")


def bias_by_group(df: pd.DataFrame, min_group_n: int = 100) -> dict:
    """Mean signed score error per food group — the blind-spot map.

    A group whose mean error is far from the overall bias is one the
    nutrients-only formula systematically mis-ranks (typically because the
    missing sodium / fruit-veg inputs matter most there).
    """
    r = reconstruct(df)
    off = pd.to_numeric(r.get("nutrition-score-fr_100g"), errors="coerce")
    g = r.get(GROUP_COL)
    if g is None:
        return {}
    g = g.astype("string").str.strip()
    g = g.where(~g.str.lower().isin({"unknown", "", "nan"}))
    m = off.notna() & r["recon_score"].notna() & g.notna()
    sub = pd.DataFrame({"err": (r["recon_score"] - off)[m], "g": g[m]})
    sizes = sub["g"].value_counts()
    keep = sizes[sizes >= min_group_n].index
    sub = sub[sub["g"].isin(keep)]
    res = (
        sub.groupby("g")["err"].agg(["mean", "count"])
        .sort_values("mean")
    )
    return {
        grp: {"mean_error": round(float(row["mean"]), 2), "n": int(row["count"])}
        for grp, row in res.iterrows()
    }
