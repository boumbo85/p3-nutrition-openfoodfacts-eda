"""Build the 2026 France extract from the official Open Food Facts Parquet dump.

    python src/build_dataset.py --out data/off_fr_2026.csv

Why this script exists
----------------------
The 2022 extract (tag ``v1.0-2022-biochem``) is frozen: it predates the salt and
fruit/vegetable columns we need to fully reconstruct the Nutri-Score, and Open
Food Facts keeps **no dated historical dump**, so those inputs cannot be
back-filled onto the 2022 composition without mixing two record versions (a
temporal leak). This rebuild therefore starts from a *single* current vintage:
every field — composition, salt, fruit/veg %, official score — comes from the
same 2026 snapshot, so enrichment is leak-free by construction.

What it does
------------
Reads the official Parquet dump **remotely via DuckDB** (no multi-GB local
download), keeps only French-market products, and flattens the nested schema
into the same flat ``*_100g`` layout the 2022 pipeline (``eda.py``) expects —
plus the three newly available columns: ``salt_100g``, ``sodium_100g`` and
``fruits_veg_100g``. The nested 2026 schema differs from the 2022 CSV:

  * ``nutriments`` is a LIST of STRUCT(name, value, "100g", ...). We unnest it
    and pivot the handful of names we need into flat columns.
  * ``product_name`` is a LIST of STRUCT(lang, text). We take the French text,
    falling back to English then to the first available.
  * the food group is the first (root) tag of ``food_groups_tags`` — the 2026
    equivalent of the old ``pnns_groups_1`` — mapped back to readable labels.
  * the official grade is ``nutriscore_grade``; the official score is the
    ``nutrition-score-fr`` nutriment (kept as ``nutrition-score-fr_100g``).

Source: https://huggingface.co/datasets/openfoodfacts/product-database
License: Open Database License (ODbL) 1.0 — see data/README.md.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

PARQUET_URL = (
    "https://huggingface.co/datasets/openfoodfacts/product-database/"
    "resolve/main/food.parquet"
)

# Nutriment names (in the dump's `nutriments[].name`) → our flat column names.
# We read the per-100g value (`"100g"` field of the struct).
#
# Note (checked against the actual 2026 dump): the official Nutri-Score is the
# plain top-level column `nutriscore_score`, NOT a `nutrition-score-fr`
# nutriment (that one is near-empty). And the best-filled fruit/veg figure is
# `fruits-vegetables-nuts` (~44% on FR), not the `-estimate-from-ingredients`
# variant (near-empty here) — so we coalesce the candidates, best first.
NUTRIMENT_MAP = {
    "energy": "energy_100g",              # kJ/100g (OFF stores energy in kJ)
    "fat": "fat_100g",
    "saturated-fat": "saturated-fat_100g",
    "carbohydrates": "carbohydrates_100g",
    "sugars": "sugars_100g",
    "fiber": "fiber_100g",
    "proteins": "proteins_100g",
    "salt": "salt_100g",
    "sodium": "sodium_100g",
}

# Fruit/veg %: several conventions coexist; take the first non-null, best first.
_FRUITVEG_NAMES = [
    "fruits-vegetables-nuts",
    "fruits-vegetables-nuts-estimate-from-ingredients",
    "fruits-vegetables-nuts-estimate",
    "fruits-vegetables-legumes",
]


def _pivot_expr() -> str:
    """Build the MAX(CASE ...) pivot for each nutriment we keep (+ fruit/veg)."""
    lines = [
        f"        MAX(CASE WHEN n.name = '{src}' THEN n.\"100g\" END) AS \"{dst}\""
        for src, dst in NUTRIMENT_MAP.items()
    ]
    # One pivot column per fruit/veg candidate; coalesced in the outer SELECT.
    for i, name in enumerate(_FRUITVEG_NAMES):
        lines.append(
            f"        MAX(CASE WHEN n.name = '{name}' THEN n.\"100g\" END) "
            f"AS \"_fv{i}\""
        )
    return ",\n".join(lines)


def build_query(source: str, limit: int | None = None) -> str:
    """SQL that flattens the FR subset into the 2022-compatible flat schema.

    ``source`` is the Parquet path/URL. Reading a **local** file is strongly
    preferred: a remote scan streams the whole 8 GB dump even behind a LIMIT,
    because the France filter + unnest run before the limit applies.
    """
    limit_clause = f"LIMIT {limit}" if limit else ""
    return f"""
    WITH fr AS (
        SELECT
            code,
            -- French product name, fallback EN, fallback first available
            COALESCE(
                (SELECT pn.text FROM UNNEST(product_name) AS t(pn)
                 WHERE pn.lang = 'fr' AND pn.text IS NOT NULL LIMIT 1),
                (SELECT pn.text FROM UNNEST(product_name) AS t(pn)
                 WHERE pn.lang = 'en' AND pn.text IS NOT NULL LIMIT 1),
                (SELECT pn.text FROM UNNEST(product_name) AS t(pn)
                 WHERE pn.text IS NOT NULL LIMIT 1)
            ) AS product_name,
            brands,
            serving_size,
            nutriscore_grade AS nutrition_grade_fr,
            -- official Nutri-Score points: the plain top-level column
            nutriscore_score AS "nutrition-score-fr_100g",
            -- root food group (2026 equivalent of pnns_groups_1): the hierarchy
            -- is encoded by list order — the FIRST tag is the PNNS-1 root
            -- (e.g. ['en:sugary-snacks','en:biscuits-and-cakes'] → sugary-snacks)
            food_groups_tags[1] AS food_group_raw,
            nutriments
        FROM read_parquet('{source}')
        WHERE list_contains(countries_tags, 'en:france')
          AND nutriments IS NOT NULL
          AND no_nutrition_data IS NOT TRUE
          AND obsolete IS NOT TRUE
        {limit_clause}
    ),
    pivoted AS (
        SELECT
            code, product_name, brands, serving_size, nutrition_grade_fr,
            "nutrition-score-fr_100g", food_group_raw,
{_pivot_expr()}
        FROM fr, UNNEST(fr.nutriments) AS t(n)
        GROUP BY code, product_name, brands, serving_size,
                 nutrition_grade_fr, "nutrition-score-fr_100g", food_group_raw
    )
    SELECT
        code, product_name, brands, serving_size, nutrition_grade_fr,
        -- readable group label: strip the 'en:' prefix (hierarchy stays hyphenated)
        regexp_replace(food_group_raw, '^..:', '') AS pnns_groups_1,
        "energy_100g", "fat_100g", "saturated-fat_100g", "carbohydrates_100g",
        "sugars_100g", "fiber_100g", "proteins_100g",
        "salt_100g", "sodium_100g",
        -- fruit/veg %: first non-null candidate, best-filled first
        COALESCE({", ".join(f'"_fv{i}"' for i in range(len(_FRUITVEG_NAMES)))})
            AS "fruits_veg_100g",
        "nutrition-score-fr_100g"
    FROM pivoted
    """


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("data/off_fr_2026.csv"),
                    help="output CSV (flat, 2022-compatible schema)")
    ap.add_argument("--source", type=str, default="data/food.parquet",
                    help="Parquet path (local, preferred) or the HuggingFace URL. "
                         f"Remote default: {PARQUET_URL}")
    ap.add_argument("--limit", type=int, default=None,
                    help="cap rows (for a quick smoke test; omit for the full run)")
    args = ap.parse_args()

    source = PARQUET_URL if args.source in ("url", "remote") else args.source

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET preserve_insertion_order = false;")  # lower memory on the pivot

    args.out.parent.mkdir(parents=True, exist_ok=True)
    query = build_query(source, args.limit)
    print(f"Reading {source}\n  filter: countries_tags ∋ 'en:france'")
    con.execute(f"COPY ({query}) TO '{args.out}' (HEADER, DELIMITER ',')")

    n = con.execute(f"SELECT count(*) FROM read_csv('{args.out}')").fetchone()[0]
    print(f"Wrote {n:,} French products -> {args.out}")

    # Fill-rate report for the two newly recovered inputs (honesty check).
    for col in ("salt_100g", "sodium_100g", "fruits_veg_100g",
                "nutrition-score-fr_100g", "nutrition_grade_fr"):
        filled = con.execute(
            f"SELECT 100.0 * count(\"{col}\") / count(*) FROM read_csv('{args.out}')"
        ).fetchone()[0]
        print(f"  fill rate {col:28s}: {float(filled):5.1f}%")


if __name__ == "__main__":
    main()
