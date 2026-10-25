"""Pure, testable nutrition-data logic for the Open Food Facts P3 project.

The heart of P3 is *cleaning*: detecting impossible nutrient values, handling
missing data, and keeping only usable columns. That logic lives here, free of
plotting, so it can be unit-tested on tiny synthetic frames.
"""
from __future__ import annotations

import pandas as pd

# Per-100g nutrient columns the project keeps.
NUTRIENT_COLS = [
    "energy_100g",
    "fat_100g",
    "saturated-fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "fiber_100g",
    "proteins_100g",
]

# Physical bounds per 100g. Mass nutrients cannot exceed 100g/100g; energy is
# capped a bit above pure fat (~900 kcal ≈ 3700 kJ) with a safety margin.
MASS_MAX = 100.0
ENERGY_MAX_KJ = 3800.0


def drop_sparse_columns(df: pd.DataFrame, max_nan_ratio: float = 0.5) -> pd.DataFrame:
    """Drop columns with more than ``max_nan_ratio`` missing values.

    Open Food Facts has ~180 columns, most almost empty. Keeping a column that
    is 90% missing adds noise, not signal — the first cleaning step removes them.
    """
    keep = [c for c in df.columns if df[c].isna().mean() <= max_nan_ratio]
    return df[keep]


def flag_impossible_nutrients(df: pd.DataFrame) -> pd.Series:
    """Boolean mask of rows with physically impossible nutrient values.

    A per-100g mass nutrient above 100g is impossible; negative values are
    impossible; energy above ~3800 kJ/100g exceeds pure fat and is an error.
    These are data-entry mistakes, not real foods.
    """
    mask = pd.Series(False, index=df.index)
    for col in NUTRIENT_COLS:
        if col not in df.columns:
            continue
        vals = pd.to_numeric(df[col], errors="coerce")
        limit = ENERGY_MAX_KJ if col == "energy_100g" else MASS_MAX
        mask |= (vals < 0) | (vals > limit)
    return mask


def drop_impossible_nutrients(df: pd.DataFrame) -> pd.DataFrame:
    """Remove rows flagged by :func:`flag_impossible_nutrients`."""
    return df[~flag_impossible_nutrients(df)]


def sugar_consistency(df: pd.DataFrame) -> pd.Series:
    """Mask of rows where sugars exceed carbohydrates (impossible by definition).

    Sugars are a subset of carbohydrates, so ``sugars_100g`` can never exceed
    ``carbohydrates_100g``. A classic cross-field sanity check.
    """
    if "sugars_100g" not in df.columns or "carbohydrates_100g" not in df.columns:
        return pd.Series(False, index=df.index)
    s = pd.to_numeric(df["sugars_100g"], errors="coerce")
    c = pd.to_numeric(df["carbohydrates_100g"], errors="coerce")
    return (s > c + 1e-6).fillna(False)


def nutriscore_grade_counts(df: pd.DataFrame, col: str = "nutrition_grade_fr") -> dict:
    """Distribution of Nutri-Score grades (a–e), lowercased, NaN excluded."""
    if col not in df.columns:
        return {}
    s = df[col].dropna().astype(str).str.lower().str.strip()
    s = s[s.isin(list("abcde"))]
    return s.value_counts().sort_index().to_dict()


def completeness(df: pd.DataFrame, cols: list[str] | None = None) -> dict[str, float]:
    """Per-column fill rate (1 - NaN ratio) — the data-quality summary."""
    cols = cols or list(df.columns)
    return {c: float(1.0 - df[c].isna().mean()) for c in cols if c in df.columns}


# ──────────────────────────────────────────────────────────────────────────
# Statistical tests — do nutrients / Nutri-Score differ across food groups?
#
# The descriptive EDA shows *that* nutrients vary; these tests ask whether the
# variation is bigger than chance, and — more importantly — how *large* it is.
# With tens of thousands of rows almost any difference is "significant", so each
# test reports an effect size (eta² for ANOVA, Cramér's V for chi²) alongside
# the p-value. The effect size is the number that actually means something.
#
# Implemented in plain numpy/pandas (no scipy dependency): one-way ANOVA via the
# F-ratio of between/within variance, chi² via observed-vs-expected counts.
# ──────────────────────────────────────────────────────────────────────────

GROUP_COL = "pnns_groups_1"
# Placeholder categories that are not real food groups.
_NON_GROUPS = {"unknown", "", "nan"}


def _f_sf(f: float, df1: int, df2: int) -> float:
    """Upper-tail p-value of an F(df1, df2) distribution, via the regularised
    incomplete beta function (no scipy). Returns P(F >= f)."""
    import math

    if f <= 0 or df1 <= 0 or df2 <= 0:
        return 1.0
    x = df2 / (df2 + df1 * f)  # maps F to the Beta tail
    a, b = df2 / 2.0, df1 / 2.0

    def _betacf(a: float, b: float, x: float) -> float:
        # Lentz's continued fraction for the incomplete beta.
        fpmin, qab, qap, qam = 1e-300, a + b, a + 1.0, a - 1.0
        c, d = 1.0, 1.0 - qab * x / qap
        if abs(d) < fpmin:
            d = fpmin
        d = 1.0 / d
        h = d
        for m in range(1, 300):
            m2 = 2 * m
            aa = m * (b - m) * x / ((qam + m2) * (a + m2))
            d = 1.0 + aa * d
            if abs(d) < fpmin:
                d = fpmin
            c = 1.0 + aa / c
            if abs(c) < fpmin:
                c = fpmin
            d = 1.0 / d
            h *= d * c
            aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
            d = 1.0 + aa * d
            if abs(d) < fpmin:
                d = fpmin
            c = 1.0 + aa / c
            if abs(c) < fpmin:
                c = fpmin
            d = 1.0 / d
            delta = d * c
            h *= delta
            if abs(delta - 1.0) < 1e-12:
                break
        return h

    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - lbeta) / a
    ib = front * _betacf(a, b, x) if x < (a + 1.0) / (a + b + 2.0) else (
        1.0 - (math.exp(math.log(1.0 - x) * b + math.log(x) * a - lbeta) / b)
        * _betacf(b, a, 1.0 - x)
    )
    return float(min(max(ib, 0.0), 1.0))


def _chi2_sf(chi2: float, df: int) -> float:
    """Upper-tail p-value of a chi²(df) distribution via the regularised lower
    incomplete gamma (no scipy). Returns P(X >= chi2)."""
    import math

    if chi2 <= 0 or df <= 0:
        return 1.0
    a, x = df / 2.0, chi2 / 2.0
    if x < a + 1.0:  # series expansion for the lower incomplete gamma
        term, s = 1.0 / a, 1.0 / a
        for n in range(1, 500):
            term *= x / (a + n)
            s += term
            if abs(term) < abs(s) * 1e-12:
                break
        p = s * math.exp(-x + a * math.log(x) - math.lgamma(a))
        return float(min(max(1.0 - p, 0.0), 1.0))
    # continued fraction for the upper incomplete gamma
    fpmin = 1e-300
    b, c = x + 1.0 - a, 1.0 / fpmin
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < fpmin:
            d = fpmin
        c = b + an / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-12:
            break
    q = h * math.exp(-x + a * math.log(x) - math.lgamma(a))
    return float(min(max(q, 0.0), 1.0))


def food_groups(df: pd.DataFrame, col: str = GROUP_COL) -> pd.Series:
    """Clean food-group labels: trim, drop placeholders ('unknown'), NaN out."""
    if col not in df.columns:
        return pd.Series(dtype="object", index=df.index)
    s = df[col].astype("string").str.strip()
    return s.where(~s.str.lower().isin(_NON_GROUPS))


def anova_nutrient_by_group(
    df: pd.DataFrame, nutrient: str, group_col: str = GROUP_COL, min_group_n: int = 30
) -> dict:
    """One-way ANOVA: does ``nutrient`` differ across food groups?

    Returns F, p-value, degrees of freedom, group count, N used, and **eta²**
    (share of the nutrient's variance explained by the food group) — the effect
    size that tells you whether a significant result is also a meaningful one.
    """
    if nutrient not in df.columns:
        return {}
    groups = food_groups(df, group_col)
    y = pd.to_numeric(df[nutrient], errors="coerce")
    sub = pd.DataFrame({"y": y, "g": groups}).dropna()
    sizes = sub["g"].value_counts()
    keep = sizes[sizes >= min_group_n].index
    sub = sub[sub["g"].isin(keep)]
    k = sub["g"].nunique()
    n = len(sub)
    if k < 2 or n <= k:
        return {}
    grand = sub["y"].mean()
    gmean = sub.groupby("g")["y"]
    ss_between = float((gmean.count() * (gmean.mean() - grand) ** 2).sum())
    ss_total = float(((sub["y"] - grand) ** 2).sum())
    ss_within = ss_total - ss_between
    df1, df2 = k - 1, n - k
    ms_b, ms_w = ss_between / df1, ss_within / df2
    f = ms_b / ms_w if ms_w > 0 else float("inf")
    return {
        "nutrient": nutrient,
        "n": int(n),
        "n_groups": int(k),
        "F": round(f, 2),
        "p_value": _f_sf(f, df1, df2),
        "eta2": round(ss_between / ss_total, 4) if ss_total > 0 else None,
        "df_between": int(df1),
        "df_within": int(df2),
    }


def chi2_grade_by_group(
    df: pd.DataFrame,
    grade_col: str = "nutrition_grade_fr",
    group_col: str = GROUP_COL,
    min_group_n: int = 30,
) -> dict:
    """Chi² test of independence: is the Nutri-Score grade distribution linked
    to the food group? Reports chi², p-value, dof and **Cramér's V** (0 = no
    association, 1 = perfect) as the effect size."""
    if grade_col not in df.columns:
        return {}
    grades = df[grade_col].astype("string").str.lower().str.strip()
    grades = grades.where(grades.isin(list("abcde")))
    groups = food_groups(df, group_col)
    sub = pd.DataFrame({"grade": grades, "g": groups}).dropna()
    sizes = sub["g"].value_counts()
    keep = sizes[sizes >= min_group_n].index
    sub = sub[sub["g"].isin(keep)]
    if sub.empty or sub["g"].nunique() < 2 or sub["grade"].nunique() < 2:
        return {}
    obs = pd.crosstab(sub["g"], sub["grade"]).values.astype(float)
    n = obs.sum()
    exp = obs.sum(1, keepdims=True) * obs.sum(0, keepdims=True) / n
    chi2 = float(((obs - exp) ** 2 / exp).sum())
    r, c = obs.shape
    dof = (r - 1) * (c - 1)
    cramers_v = (chi2 / (n * (min(r, c) - 1))) ** 0.5
    return {
        "n": int(n),
        "n_groups": int(r),
        "chi2": round(chi2, 1),
        "p_value": _chi2_sf(chi2, dof),
        "dof": int(dof),
        "cramers_v": round(float(cramers_v), 4),
    }
