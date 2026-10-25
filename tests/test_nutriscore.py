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
    df = pd.DataFrame({
        "energy_100g": [300] * 200,
        "sugars_100g": [0] * 200,
        "saturated-fat_100g": [0] * 200,
        "fiber_100g": [0] * 200,
        "proteins_100g": [0] * 200,
        "nutrition-score-fr_100g": [5] * 200,     # official says 5, we'll say 0 → err -5
        "pnns_groups_1": ["Beverages"] * 100 + ["Salty snacks"] * 100,
    })
    b = N.bias_by_group(df, min_group_n=50)
    assert set(b) == {"Beverages", "Salty snacks"}
    assert b["Beverages"]["mean_error"] == -5.0


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
