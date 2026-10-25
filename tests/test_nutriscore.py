"""Unit tests for the Nutri-Score reconstruction — no CSV needed."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import nutriscore as N  # noqa: E402


def test_ladder_points_step_rule():
    # sugars ladder: ≤4.5 → 0 ; just above → 1 ; above 45 → 10
    assert N._ladder_points(0, N._SUGARS_G) == 0
    assert N._ladder_points(4.5, N._SUGARS_G) == 0      # boundary is inclusive-low
    assert N._ladder_points(4.6, N._SUGARS_G) == 1
    assert N._ladder_points(100, N._SUGARS_G) == 10


def test_negative_points_bounds():
    # all maxed → 30 ; all minimal → 0
    assert N.negative_points(9999, 100, 100) == 30
    assert N.negative_points(0, 0, 0) == 0


def test_protein_and_fibre_points():
    assert N.protein_points(0) == 0
    assert N.protein_points(9) == 5
    assert N.fibre_points(0) == 0
    assert N.fibre_points(5) == 5


def test_protein_exemption_rule():
    # High-negative food (N≥11): protein points must NOT be subtracted.
    # energy 9999→10, sugars 100→10, satfat 100→10  => N=30 ; protein 9 => 5 pts
    score = N.nutriscore_points(9999, 100, 100, 0, 9)
    assert score == 30            # protein 5 pts ignored because N≥11
    # Low-negative food (N<11): protein IS subtracted.
    # energy 300→0, sugars 0, satfat 0 => N=0 ; protein 9 => 5 ; fibre 5 => 5
    score2 = N.nutriscore_points(300, 0, 0, 5, 9)
    assert score2 == -10          # 0 - (5 + 5)


def test_points_to_grade_cutoffs():
    assert N.points_to_grade(-5) == "a"
    assert N.points_to_grade(-1) == "a"
    assert N.points_to_grade(0) == "b"
    assert N.points_to_grade(2) == "b"
    assert N.points_to_grade(3) == "c"
    assert N.points_to_grade(10) == "c"
    assert N.points_to_grade(11) == "d"
    assert N.points_to_grade(18) == "d"
    assert N.points_to_grade(19) == "e"


def test_reconstruct_and_validation_perfect_case():
    # Two rows whose official score equals our reconstruction exactly.
    df = pd.DataFrame({
        "energy_100g": [300, 9999],
        "sugars_100g": [0, 100],
        "saturated-fat_100g": [0, 100],
        "fiber_100g": [5, 0],
        "proteins_100g": [9, 9],
        "nutrition-score-fr_100g": [-10, 30],
        "nutrition_grade_fr": ["a", "e"],
    })
    v = N.validation(df)
    assert v["n"] == 2
    assert v["exact_score_agreement"] == 1.0
    assert v["mae_score"] == 0.0
    assert v["grade_agreement"] == 1.0


def test_bias_by_group_shape():
    # Use solid-food groups so the solid grid applies (recon score = 0 here),
    # keeping the expected error exact and independent of beverage routing.
    df = pd.DataFrame({
        "energy_100g": [300] * 200,
        "sugars_100g": [0] * 200,
        "saturated-fat_100g": [0] * 200,
        "fiber_100g": [0] * 200,
        "proteins_100g": [0] * 200,
        "nutrition-score-fr_100g": [5] * 200,     # official says 5, we'll say 0 → err -5
        "pnns_groups_1": ["Composite foods"] * 100 + ["Salty snacks"] * 100,
    })
    b = N.bias_by_group(df, min_group_n=50)
    assert set(b) == {"Composite foods", "Salty snacks"}
    assert b["Composite foods"]["mean_error"] == -5.0


def test_healthier_alternative():
    df = pd.DataFrame({
        "product_name": ["snack A", "snack B", "snack C", "veg X"],
        "pnns_groups_1": ["Salty snacks", "Salty snacks", "Salty snacks", "Fruits and vegetables"],
        "nutrition-score-fr_100g": [20, 5, 12, 1],
    }, index=[10, 11, 12, 13])
    alt = N.healthier_alternative(df, 10, n=2)
    # same group, lower score, best first -> B(5) then C(12)
    assert alt["product_name"].tolist() == ["snack B", "snack C"]
    # snack B (score 5) is already the best of its group -> no healthier option
    assert N.healthier_alternative(df, 11).empty


def test_beverage_grid_rates_soda_harshly():
    # A sugary soda (Coca-like): ~180 kJ, 10.6 g sugar, no fat/fibre/protein.
    # Solid grid would give ~2 pts -> B. Beverage grid must land it in D/E.
    solid = N.nutriscore_points(180, 10.6, 0, 0, 0)
    bev = N.beverage_points(180, 10.6, 0, 0, 0)
    assert bev > solid                       # drinks grid is stricter on sugar
    assert N.points_to_grade(bev, is_beverage=True) in ("d", "e")
    assert N.points_to_grade(solid) in ("a", "b")   # the old, too-kind result


def test_only_water_scores_A_on_beverage_grid():
    assert N.points_to_grade(0, is_beverage=True, is_water=True) == "a"
    # a zero-score drink that isn't water can't be A -> B
    assert N.points_to_grade(0, is_beverage=True, is_water=False) == "b"


def test_reconstruct_routes_beverages():
    df = pd.DataFrame({
        "product_name": ["Cola", "Cookie"],
        "pnns_groups_1": ["Beverages", "Sugary snacks"],
        "energy_100g": [180, 2000],
        "sugars_100g": [10.6, 30],
        "saturated-fat_100g": [0, 10],
        "fiber_100g": [0, 2],
        "proteins_100g": [0, 5],
        "nutrition-score-fr_100g": [14, 20],
        "nutrition_grade_fr": ["e", "e"],
    })
    out = N.reconstruct(df)
    # the cola must now be graded on the beverage scale (D or E, not B)
    assert out.loc[0, "recon_grade"] in ("d", "e")


# ── 2026 enrichment: sodium + fruit/veg points ──────────────────────────────

def test_sodium_points_from_salt():
    # salt 0 → sodium 0 mg → 0 pts. salt 2.5 g → 1000 mg → 10 pts (ladder maxes).
    assert N.sodium_points_from_salt(0) == 0
    assert N.sodium_points_from_salt(2.5) == 10          # 1000 mg sodium
    # salt 0.25 g → 100 mg sodium → just above 90 → 1 pt
    assert N.sodium_points_from_salt(0.25) == 1
    assert N.sodium_points_from_salt(None) == 0          # missing → 0, documented


def test_sodium_from_salt_matches_from_sodium():
    # salt 1 g == sodium 0.4 g; both must score identically.
    assert N.sodium_points_from_salt(1.0) == N.sodium_points_from_sodium(0.4)


def test_fruitveg_points_thresholds():
    assert N.fruitveg_points(0) == 0
    assert N.fruitveg_points(40) == 0        # boundary inclusive-low
    assert N.fruitveg_points(41) == 1
    assert N.fruitveg_points(61) == 2
    assert N.fruitveg_points(81) == 5
    assert N.fruitveg_points(None) == 0      # missing → 0


def test_full_score_salt_makes_salty_food_harsher():
    # A salty-but-not-sugary food: nutrients-only misses the salt penalty.
    nutrients_only = N.nutriscore_points(1500, 2, 3, 0, 8)
    full = N.nutriscore_points_full(1500, 2, 3, salt_g=2.0, fibre_g=0,
                                    protein_g=8, fruitveg_pct=0)
    assert full > nutrients_only            # salt adds negative points


def test_full_score_fruitveg_makes_produce_kinder():
    # A fruit/veg product: the bonus must lower (improve) the score.
    no_bonus = N.nutriscore_points_full(300, 8, 0, salt_g=0, fibre_g=2,
                                        protein_g=1, fruitveg_pct=0)
    with_bonus = N.nutriscore_points_full(300, 8, 0, salt_g=0, fibre_g=2,
                                          protein_g=1, fruitveg_pct=90)
    assert with_bonus < no_bonus


def test_reconstruct_full_and_validation_full():
    # Build rows whose full reconstruction equals the official score exactly.
    # Row A: low everything, fruit/veg 90% → bonus 5. Row B: salty snack.
    df = pd.DataFrame({
        "pnns_groups_1": ["fruits-and-vegetables", "salty-snacks"],
        "energy_100g": [300, 1500],
        "sugars_100g": [8, 2],
        "saturated-fat_100g": [0, 3],
        "salt_100g": [0.0, 2.0],
        "fiber_100g": [2, 0],
        "proteins_100g": [1, 8],
        "fruits_veg_100g": [90.0, 0.0],
        "nutrition_grade_fr": ["a", "d"],
    })
    exp_a = N.nutriscore_points_full(300, 8, 0, 0.0, 2, 1, 90.0)
    exp_b = N.nutriscore_points_full(1500, 2, 3, 2.0, 0, 8, 0.0)
    df["nutrition-score-fr_100g"] = [exp_a, exp_b]
    r = N.reconstruct_full(df)
    assert r.loc[0, "recon_score_full"] == exp_a
    v = N.validation_full(df)
    assert v["n"] == 2
    assert v["exact_score_agreement"] == 1.0
    assert v["signed_bias"] == 0.0


def test_fill_rates_reports_missing():
    df = pd.DataFrame({
        "salt_100g": [1.0, None, 2.0, None],
        "fruits_veg_100g": [None, None, 50.0, 10.0],
        "nutrition-score-fr_100g": [1, 2, 3, 4],
    })
    fr = N.fill_rates(df)
    assert fr["salt_100g"] == 0.5
    assert fr["fruits_veg_100g"] == 0.5
    assert fr["nutrition-score-fr_100g"] == 1.0
