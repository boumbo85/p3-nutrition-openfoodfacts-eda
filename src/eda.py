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


# ──────────────────────────────────────────────────────────────────────────
# Biochemical consistency — physical laws a real food must obey.
#
# Per-column bounds (above) catch "sugar = 900 g". These cross-field checks
# catch foods that look fine column-by-column yet break a physical law:
#   * a subset cannot exceed its set (saturated fat ≤ fat, sugars ≤ carbs),
#   * the macronutrients cannot weigh more than the food (mass balance),
#   * declared energy must match the Atwater energy of the composition.
# These are the checks a nutritionist/biochemist would run before trusting
# the table — and the ones the 2022 pass never did.
# ──────────────────────────────────────────────────────────────────────────

# Atwater factors, kJ per gram (FAO): carbohydrate & protein 17, fat 37,
# fibre 8. Used to recompute energy from the composition.
_ATWATER_KJ = {"carb": 17.0, "protein": 17.0, "fat": 37.0, "fibre": 8.0}


def _num0(df: pd.DataFrame, col: str) -> pd.Series:
    """Numeric column with NaN→0 (absent column → all zeros)."""
    if col not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df[col], errors="coerce").fillna(0)

# Mass-balance tolerance: labels round to the gram, so allow +1 g/100g of
# rounding slack before calling fat+carb+protein > 100 a physical impossibility.
MASS_BALANCE_TOL = 1.0


def satfat_consistency(df: pd.DataFrame) -> pd.Series:
    """Mask of rows where saturated fat exceeds total fat (impossible).

    Saturated fat is a subset of total fat, so ``saturated-fat_100g`` can never
    exceed ``fat_100g``. The mirror of :func:`sugar_consistency`, missing from
    the original cleaning pass.
    """
    if "saturated-fat_100g" not in df.columns or "fat_100g" not in df.columns:
        return pd.Series(False, index=df.index)
    sat = pd.to_numeric(df["saturated-fat_100g"], errors="coerce")
    fat = pd.to_numeric(df["fat_100g"], errors="coerce")
    return (sat > fat + 1e-6).fillna(False)


def mass_balance_violation(df: pd.DataFrame, tol: float = MASS_BALANCE_TOL) -> pd.Series:
    """Mask of rows where fat + carbohydrates + fibre + protein exceed 100 g/100g.

    These are physical fractions of the product, so their sum cannot exceed the
    product's own mass (the remainder is water, salt and ash).

    **Fibre is counted only when it is clearly reported separately** from
    carbohydrates. Open Food Facts is crowdsourced and mixes both conventions
    (EU: fibre apart from carbs; US: fibre inside carbs). Empirically, 95% of
    the rows where adding fibre would create a violation satisfy
    ``sugars+fibre ≤ carbs`` — i.e. fibre is already inside the carbohydrate
    figure there, so adding it would double-count. We therefore add fibre
    per-row only when ``sugars+fibre > carbs`` (fibre demonstrably outside
    carbs); otherwise fibre is treated as already included. A ``tol`` of 1 g
    absorbs label rounding.
    """
    need = ["fat_100g", "carbohydrates_100g", "proteins_100g"]
    if not all(c in df.columns for c in need):
        return pd.Series(False, index=df.index)
    fat = _num0(df, "fat_100g")
    carb = _num0(df, "carbohydrates_100g")
    prot = _num0(df, "proteins_100g")
    fib = _num0(df, "fiber_100g")
    sug = _num0(df, "sugars_100g")
    # fibre outside carbs only where sugars+fibre exceeds carbs
    fibre_outside = (sug + fib) > (carb + 1e-6)
    total = fat + carb + prot + fib.where(fibre_outside, 0.0)
    return (total > 100.0 + tol).fillna(False)


def dry_matter_implausible(df: pd.DataFrame, min_water: float = 1.0) -> pd.Series:
    """Mask of rows leaving physically implausibly little room for water.

    Almost every food contains water (even dried goods keep a few %). If
    fat+carb+fibre+protein already fills 100 g/100g, there is *no room* for the
    water a real food must contain. We flag rows whose dry-matter sum exceeds
    ``100 - min_water`` g (default: less than 1 g of water left) — stricter than
    the mass-balance check, catching 'suspiciously bone-dry' compositions a
    plain >100 g test lets through (e.g. a yoghurt logged at 98 g of macros).
    """
    cols = ["fat_100g", "carbohydrates_100g", "fiber_100g", "proteins_100g"]
    present = [c for c in cols if c in df.columns]
    if not present:
        return pd.Series(False, index=df.index)
    dry = sum(_num0(df, c) for c in present)
    hard = mass_balance_violation(df)
    # Exclude legitimately dry single-component foods (oil, sugar, pure starch):
    # if one macro alone is ≥ 90 g, the low water content is real, not an error.
    pure = pd.Series(False, index=df.index)
    for c in ["fat_100g", "carbohydrates_100g", "proteins_100g"]:
        pure |= _num0(df, c) >= 90.0
    return ((dry > 100.0 - min_water) & ~hard & ~pure).fillna(False)


def atwater_energy_kj(df: pd.DataFrame) -> pd.Series:
    """Energy (kJ/100g) recomputed from composition via Atwater factors."""
    def col(c: str) -> pd.Series:
        return pd.to_numeric(df[c], errors="coerce").fillna(0) if c in df.columns \
            else pd.Series(0.0, index=df.index)
    return (
        _ATWATER_KJ["carb"] * col("carbohydrates_100g")
        + _ATWATER_KJ["protein"] * col("proteins_100g")
        + _ATWATER_KJ["fat"] * col("fat_100g")
        + _ATWATER_KJ["fibre"] * col("fiber_100g")
    )


def atwater_inconsistency(df: pd.DataFrame, rel_tol: float = 0.5) -> pd.Series:
    """Mask of rows whose declared energy disagrees with its Atwater energy.

    The declared ``energy_100g`` should match the energy recomputed from the
    macronutrients. A relative gap beyond ``rel_tol`` (default 50%) means either
    the energy or a macro is wrong — we cannot tell which, so these are *flagged*
    for review rather than assumed-correct. Rows with no declared energy or an
    all-zero composition are not flagged (nothing to compare).
    """
    if "energy_100g" not in df.columns:
        return pd.Series(False, index=df.index)
    e = pd.to_numeric(df["energy_100g"], errors="coerce")
    pred = atwater_energy_kj(df)
    valid = e.notna() & (e > 0) & (pred > 0)
    rel = (e - pred).abs() / e.where(e > 0)
    return (valid & (rel > rel_tol)).fillna(False)


def energy_below_floor(df: pd.DataFrame, slack: float = 0.7) -> pd.Series:
    """Mask of rows whose declared energy is below the incompressible minimum.

    Every macronutrient has a minimum energy density (fat 37, carb/protein 17,
    fibre 8 kJ/g), so the declared energy cannot fall far below the Atwater sum.
    We flag only energies below ``slack`` × that minimum (default 0.7, i.e. more
    than 30% too low) — a conservative threshold that keeps genuine
    impossibilities while sparing fibre-rich dry foods (cereals, bran) whose
    energy legitimately sits just under the naive fat+carb+protein floor because
    fibre and the spread in Atwater factors are not exactly known. kcal↔kJ unit
    errors are excluded (they are correctable, not impossible).
    """
    if "energy_100g" not in df.columns:
        return pd.Series(False, index=df.index)
    e = pd.to_numeric(df["energy_100g"], errors="coerce")
    floor = atwater_energy_kj(df)  # includes fibre energy — fewer false positives
    below = e.notna() & (floor > 0) & (e < slack * floor)
    return (below & ~unit_error_kcal_as_kj(df)).fillna(False)


def unit_error_kcal_as_kj(df: pd.DataFrame, rel_tol: float = 0.25) -> pd.Series:
    """Mask of rows whose energy was likely entered in kcal but stored as kJ.

    A classic Open Food Facts data-entry error: 1 kcal = 4.184 kJ, so an energy
    mistakenly logged in kcal reads ~4.18× too low. We flag rows where the
    declared energy is close to Atwater/4.184 (within ``rel_tol``) **and** far
    from the correct Atwater value — the signature of a kcal↔kJ mix-up rather
    than random noise. A very 'metier' check: only someone who knows the dataset
    spots it.
    """
    if "energy_100g" not in df.columns:
        return pd.Series(False, index=df.index)
    e = pd.to_numeric(df["energy_100g"], errors="coerce")
    pred_kj = atwater_energy_kj(df)
    valid = e.notna() & (e > 0) & (pred_kj > 0)
    looks_kcal = (e - pred_kj / 4.184).abs() / pred_kj < rel_tol
    not_kj = (e - pred_kj).abs() / pred_kj > rel_tol
    return (valid & looks_kcal & not_kj).fillna(False)


def empty_product(df: pd.DataFrame) -> pd.Series:
    """Mask of 'ghost' rows: energy and every macronutrient are zero.

    A real food is almost never 0 kJ with 0 fat/carb/protein/sugar — even
    flavoured water carries traces. These are empty records, not foods.
    """
    cols = ["energy_100g", "fat_100g", "carbohydrates_100g", "proteins_100g", "sugars_100g"]
    present = [c for c in cols if c in df.columns]
    if not present:
        return pd.Series(False, index=df.index)
    mask = pd.Series(True, index=df.index)
    for c in present:
        mask &= pd.to_numeric(df[c], errors="coerce").fillna(0) == 0
    return mask


# Spreadsheet-export artefacts and null-like strings that are not real names.
_INVALID_NAMES = {
    "#error!", "#ref!", "#value!", "#name?", "#n/a", "#div/0!",
    "nan", "null", "none", "unknown", "n/a", "na", "",
}


def invalid_product_name(df: pd.DataFrame, col: str = "product_name") -> pd.Series:
    """Mask of rows whose product name is not a usable name.

    Catches spreadsheet-export artefacts (``#Error!``, ``#REF!``), null-like
    strings, blanks, names shorter than 2 characters, and names made only of
    digits/punctuation. Marginal in count but a clean normalisation step: a
    record you cannot name is not a usable product.
    """
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    s = df[col].astype("string").str.strip()
    low = s.str.lower()
    bad = low.isin(_INVALID_NAMES) | low.isna()
    bad |= s.str.len() < 2
    bad |= s.str.fullmatch(r"[\d\W]+", na=False)   # only digits / punctuation
    return bad.fillna(True)


def fiber_zero_rate(df: pd.DataFrame) -> float:
    """Share of rows with fibre exactly 0 — the imputation smell.

    ``fiber_100g`` is 100% filled, which is suspicious for a field that is
    usually missing. A high exact-zero rate signals missing values imputed as 0,
    which biases any fibre-based analysis (and the Nutri-Score fibre points).
    """
    if "fiber_100g" not in df.columns:
        return 0.0
    f = pd.to_numeric(df["fiber_100g"], errors="coerce")
    n = f.notna().sum()
    return float((f == 0).sum() / n) if n else 0.0


def physical_validity_report(df: pd.DataFrame) -> dict:
    """Count every biochemical violation — the audit a nutritionist would run."""
    checks = {
        # hard impossibilities (dropped from the clean extract)
        "impossible_bounds": flag_impossible_nutrients(df),
        "sugars_over_carbs": sugar_consistency(df),
        "satfat_over_fat": satfat_consistency(df),
        "mass_balance_over_100": mass_balance_violation(df),
        "energy_below_floor": energy_below_floor(df),
        "empty_product": empty_product(df),
        "invalid_name": invalid_product_name(df),
        # soft signals (flagged for review, kept)
        "atwater_inconsistent": atwater_inconsistency(df),
        "unit_error_kcal_as_kj": unit_error_kcal_as_kj(df),
        "dry_matter_implausible": dry_matter_implausible(df),
    }
    any_hard = (
        checks["impossible_bounds"] | checks["sugars_over_carbs"]
        | checks["satfat_over_fat"] | checks["mass_balance_over_100"]
        | checks["energy_below_floor"] | checks["empty_product"]
        | checks["invalid_name"]
    )
    return {
        "n_total": int(len(df)),
        "counts": {k: int(v.sum()) for k, v in checks.items()},
        "n_hard_violations": int(any_hard.sum()),
        "fiber_zero_rate": round(fiber_zero_rate(df), 4),
    }


def physically_clean(df: pd.DataFrame) -> pd.DataFrame:
    """Return the physically-valid extract.

    Drops *hard* impossibilities (out-of-bounds values, subset violations,
    mass-balance > 100 g, empty records). Atwater inconsistencies are NOT
    dropped here — they are flagged by :func:`atwater_inconsistency` for review,
    since we cannot know whether the energy or a macro is the wrong field.
    """
    drop = (
        flag_impossible_nutrients(df)
        | sugar_consistency(df)
        | satfat_consistency(df)
        | mass_balance_violation(df)
        | energy_below_floor(df)
        | empty_product(df)
        | invalid_product_name(df)
    )
    return df[~drop].copy()


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
