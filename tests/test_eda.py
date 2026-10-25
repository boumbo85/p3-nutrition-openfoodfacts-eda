"""Unit tests for the pure nutrition-cleaning logic — no CSV needed."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import eda as E  # noqa: E402


def test_drop_sparse_columns():
    df = pd.DataFrame({
        "full": [1, 2, 3, 4],
        "half": [1, np.nan, 3, np.nan],       # 50% NaN -> kept (<=0.5)
        "mostly_empty": [1, np.nan, np.nan, np.nan],  # 75% NaN -> dropped
    })
    out = E.drop_sparse_columns(df, max_nan_ratio=0.5)
    assert "full" in out.columns
    assert "half" in out.columns
    assert "mostly_empty" not in out.columns


def test_flag_impossible_nutrients():
    df = pd.DataFrame({
        "fat_100g": [10, 150, -5, 30],          # 150 and -5 impossible
        "energy_100g": [500, 1000, 1200, 9999],  # 9999 > ENERGY_MAX_KJ
        "sugars_100g": [5, 10, 20, 15],
        "carbohydrates_100g": [50, 60, 70, 40],
    })
    mask = E.flag_impossible_nutrients(df)
    assert mask.tolist() == [False, True, True, True]


def test_sugar_consistency():
    df = pd.DataFrame({
        "sugars_100g": [5, 80, 10],
        "carbohydrates_100g": [50, 60, 70],   # row 1: sugars(80) > carbs(60)
    })
    mask = E.sugar_consistency(df)
    assert mask.tolist() == [False, True, False]


def test_nutriscore_grade_counts_normalises_case():
    df = pd.DataFrame({"nutrition_grade_fr": ["A", "a", "B", "z", np.nan, "e"]})
    counts = E.nutriscore_grade_counts(df)
    assert counts["a"] == 2
    assert counts["b"] == 1
    assert counts["e"] == 1
    assert "z" not in counts            # invalid grade dropped


def test_completeness():
    df = pd.DataFrame({"a": [1, 2, np.nan, 4], "b": [1, 2, 3, 4]})
    comp = E.completeness(df, ["a", "b"])
    assert np.isclose(comp["a"], 0.75)
    assert np.isclose(comp["b"], 1.0)


# ── statistical tests ──────────────────────────────────────────────────────

def test_food_groups_drops_placeholders():
    df = pd.DataFrame({"pnns_groups_1": ["Beverages", "unknown", "  Sugary snacks ", None]})
    g = E.food_groups(df)
    assert g.tolist()[0] == "Beverages"
    assert g.tolist()[1] is pd.NA or pd.isna(g.tolist()[1])
    assert g.tolist()[2] == "Sugary snacks"      # trimmed
    assert pd.isna(g.tolist()[3])


def test_f_sf_matches_known_value():
    # F(2, 27) = 3.35 -> upper-tail p ~ 0.0502 (classic table value).
    p = E._f_sf(3.3541, 2, 27)
    assert abs(p - 0.05) < 0.01


def test_chi2_sf_matches_known_value():
    # chi²(1) = 3.841 -> p ~ 0.05 ; chi²(2) = 5.991 -> p ~ 0.05.
    assert abs(E._chi2_sf(3.841, 1) - 0.05) < 0.005
    assert abs(E._chi2_sf(5.991, 2) - 0.05) < 0.005


def test_anova_detects_separated_groups():
    # Three clearly separated groups -> large F, tiny p, high eta².
    df = pd.DataFrame({
        "sugars_100g": [1, 2, 1, 2] + [50, 51, 49, 50] + [90, 91, 89, 90],
        "pnns_groups_1": ["low"] * 4 + ["mid"] * 4 + ["high"] * 4,
    })
    r = E.anova_nutrient_by_group(df, "sugars_100g", min_group_n=3)
    assert r["n_groups"] == 3
    assert r["p_value"] < 1e-6
    assert r["eta2"] > 0.99          # almost all variance is between-group


def test_anova_null_when_groups_identical():
    df = pd.DataFrame({
        "fat_100g": [10, 11, 9, 10, 11, 9],
        "pnns_groups_1": ["a", "a", "a", "b", "b", "b"],
    })
    r = E.anova_nutrient_by_group(df, "fat_100g", min_group_n=3)
    assert r["p_value"] > 0.3        # no real difference
    assert r["eta2"] < 0.2


def test_chi2_grade_by_group_association():
    # Group x grades almost one-to-one -> strong association, high Cramér's V.
    df = pd.DataFrame({
        "pnns_groups_1": ["snack"] * 6 + ["veg"] * 6,
        "nutrition_grade_fr": ["e"] * 5 + ["d"] + ["a"] * 5 + ["b"],
    })
    r = E.chi2_grade_by_group(df, min_group_n=3)
    assert r["p_value"] < 0.05
    assert r["cramers_v"] > 0.5
