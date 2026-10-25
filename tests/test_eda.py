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


# ── biochemical consistency (physical-reality checks) ──────────────────────

def test_satfat_consistency():
    df = pd.DataFrame({
        "saturated-fat_100g": [5, 40, 10],
        "fat_100g": [50, 30, 10],          # row 1: sat(40) > fat(30)
    })
    assert E.satfat_consistency(df).tolist() == [False, True, False]


def test_mass_balance_violation_includes_fibre():
    # fibre counts toward the mass (EU/OFF convention, confirmed empirically).
    df = pd.DataFrame({
        "fat_100g": [10, 60, 30],
        "carbohydrates_100g": [20, 30, 40],
        "fiber_100g": [0, 5, 0],           # row1: 60+30+5+20 = 115 > 101
        "proteins_100g": [5, 20, 25],      # row0: 35 ok ; row2: 95 ok
    })
    assert E.mass_balance_violation(df).tolist() == [False, True, False]


def test_mass_balance_tolerance_absorbs_rounding():
    # 100.5 g is within the +1 g rounding tolerance -> not flagged.
    df = pd.DataFrame({
        "fat_100g": [40.5], "carbohydrates_100g": [40.0],
        "fiber_100g": [0.0], "proteins_100g": [20.0],
    })
    assert E.mass_balance_violation(df).tolist() == [False]


def test_dry_matter_implausible():
    # row1: 30+40+4.5+25 = 99.5 g dry -> only 0.5 g water left -> implausible,
    # yet <= 101 so NOT a hard mass-balance violation. row0: 55 g -> fine.
    df = pd.DataFrame({
        "fat_100g": [5, 30],
        "carbohydrates_100g": [40, 40],
        "fiber_100g": [0, 4.5],
        "proteins_100g": [10, 25],
    })
    assert E.dry_matter_implausible(df, min_water=1.0).tolist() == [False, True]


def test_energy_below_floor():
    # 50 g fat forces >= 37*50*0.9 = 1665 kJ. Row0 energy 1200 is below the
    # floor AND not a kcal mix-up (Atwater 1850 -> /4.184 = 442, far from 1200),
    # so it is a genuine floor violation. Row1 (2000) is fine.
    df = pd.DataFrame({
        "energy_100g": [1200, 2000],
        "fat_100g": [50, 50],
        "carbohydrates_100g": [0, 0],
        "proteins_100g": [0, 0],
        "fiber_100g": [0, 0],
    })
    assert E.energy_below_floor(df).tolist() == [True, False]


def test_unit_error_kcal_as_kj():
    # Composition -> Atwater ~795 kJ. If logged as 190 (~795/4.184), it's kcal.
    df = pd.DataFrame({
        "energy_100g": [190, 795],         # row0: kcal mistake ; row1: correct kJ
        "fat_100g": [10, 10],
        "carbohydrates_100g": [20, 20],
        "proteins_100g": [5, 5],
        "fiber_100g": [0, 0],
    })
    assert E.unit_error_kcal_as_kj(df).tolist() == [True, False]


def test_atwater_energy_and_inconsistency():
    # Composition: 10g fat, 20g carb, 5g protein, 0 fibre
    #   -> 37*10 + 17*(20+5) = 370 + 425 = 795 kJ
    df = pd.DataFrame({
        "energy_100g": [795, 3000, 0],      # row0 matches ; row1 way too high ; row2 no energy
        "fat_100g": [10, 10, 10],
        "carbohydrates_100g": [20, 20, 20],
        "proteins_100g": [5, 5, 5],
        "fiber_100g": [0, 0, 0],
    })
    pred = E.atwater_energy_kj(df)
    assert abs(pred.iloc[0] - 795) < 1e-6
    incon = E.atwater_inconsistency(df, rel_tol=0.5)
    assert incon.tolist() == [False, True, False]   # row2 has no energy -> not flagged


def test_empty_product():
    df = pd.DataFrame({
        "energy_100g": [0, 500],
        "fat_100g": [0, 1],
        "carbohydrates_100g": [0, 1],
        "proteins_100g": [0, 1],
        "sugars_100g": [0, 1],
    })
    assert E.empty_product(df).tolist() == [True, False]


def test_fiber_zero_rate():
    df = pd.DataFrame({"fiber_100g": [0, 0, 2, 4]})
    assert np.isclose(E.fiber_zero_rate(df), 0.5)


def test_physically_clean_drops_hard_violations_not_atwater():
    df = pd.DataFrame({
        "energy_100g": [795, 795, 795],
        "fat_100g": [10, 60, 10],           # row1 part of a mass-balance violation
        "saturated-fat_100g": [5, 5, 5],
        "carbohydrates_100g": [20, 30, 20],
        "sugars_100g": [5, 5, 5],
        "proteins_100g": [5, 20, 5],        # row1: 60+30+20 = 110 -> dropped
        "fiber_100g": [0, 0, 0],
    })
    out = E.physically_clean(df)
    assert len(out) == 2                    # the mass-balance row removed


def test_physical_validity_report_shape():
    df = pd.DataFrame({
        "energy_100g": [795, 0],
        "fat_100g": [10, 0],
        "saturated-fat_100g": [5, 0],
        "carbohydrates_100g": [20, 0],
        "sugars_100g": [5, 0],
        "proteins_100g": [5, 0],
        "fiber_100g": [0, 0],
    })
    rep = E.physical_validity_report(df)
    assert rep["n_total"] == 2
    assert rep["counts"]["empty_product"] == 1
    assert "n_hard_violations" in rep


def test_invalid_product_name():
    df = pd.DataFrame({"product_name": [
        "Organic Oat Groats",   # valid
        "#Error!",              # spreadsheet artefact
        "  null ",              # null-like
        "1848",                 # digits only
        "a",                    # too short
        "",                     # blank
    ]})
    assert E.invalid_product_name(df).tolist() == [False, True, True, True, True, True]


def test_biochemical_mask_excludes_empty_and_names():
    # An empty 'ghost' row is a hard violation but NOT a biochemical one.
    df = pd.DataFrame({
        "product_name": ["Milk", "ghost"],
        "energy_100g": [300, 0],
        "fat_100g": [3, 0],
        "saturated-fat_100g": [2, 0],
        "carbohydrates_100g": [5, 0],
        "sugars_100g": [5, 0],
        "proteins_100g": [3, 0],
        "fiber_100g": [0, 0],
    })
    assert E.hard_violation_mask(df).tolist() == [False, True]        # ghost dropped
    assert E.biochemical_violation_mask(df).tolist() == [False, False]  # not biochem


def test_bootstrap_flag_rate_is_reproducible_and_brackets_point():
    # 10% of rows are impossible (sugars > carbs). The CI must bracket 0.10
    # and be identical across runs with the same seed.
    n = 500
    df = pd.DataFrame({
        "sugars_100g": [80.0 if i < 50 else 5.0 for i in range(n)],
        "carbohydrates_100g": [60.0] * n,     # first 50 rows: sugars > carbs
    })
    r1 = E.bootstrap_flag_rate(df, which="hard", n_boot=200, seed=7)
    r2 = E.bootstrap_flag_rate(df, which="hard", n_boot=200, seed=7)
    assert r1 == r2                                   # reproducible (seed fixed)
    assert abs(r1["point_pct"] - 10.0) < 1e-6
    assert r1["ci_low_pct"] < 10.0 < r1["ci_high_pct"]