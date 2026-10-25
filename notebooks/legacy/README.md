# Legacy notebooks — 2022 exploratory work

These are the **original 2022 notebooks**, kept for transparency. They show the
raw exploration: column pruning, impossible-value handling, de-duplication,
and the first univariate/bivariate analysis.

They are *not* the reference implementation. The clean, tested, reproducible
pipeline lives in [`../../src/`](../../src) (`eda.py` + `run_eda.py`), runs in CI,
and regenerates every number in the main README from `results.json`.

Why keep them? The gap between this exploratory draft and the 2026 `src/`
rewrite is the point — it shows how the project matured from notebook to
tested, auditable code.

---

# Notebooks historiques — exploration 2022

Ce sont les **notebooks d'origine (2022)**, conservés par transparence. Ils
montrent l'exploration brute : élagage des colonnes, traitement des valeurs
impossibles, dédoublonnage, première analyse univariée/bivariée.

Ce n'est *pas* l'implémentation de référence. Le pipeline propre, testé et
reproductible est dans [`../../src/`](../../src) (`eda.py` + `run_eda.py`),
tourne en CI et regénère chaque chiffre du README principal depuis `results.json`.

Pourquoi les garder ? L'écart entre ce brouillon et la réécriture `src/` de 2026
est justement ce qui raconte la maturation du projet : du notebook au code testé
et auditable.
