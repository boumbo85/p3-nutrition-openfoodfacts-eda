# 🥗 Open Food Facts — Data Cleaning with Domain Expertise

[![CI](https://github.com/boumbo85/p3-nutrition-openfoodfacts-eda/actions/workflows/ci.yml/badge.svg)](https://github.com/boumbo85/p3-nutrition-openfoodfacts-eda/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://www.python.org/)
![status](https://img.shields.io/badge/status-completed-success)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

> **One question:** *can a crowdsourced nutrition database be trusted enough to power a food-scoring app?*
> This is a **data-cleaning project** on **Open Food Facts** — ~180 mostly-empty columns, duplicates, and values that are physically impossible. The twist: the cleaning is driven by **biochemistry**, not just column bounds. Mass balance, Atwater energy, subset hierarchies — the laws a real food must obey become the filters. The result is a smaller but trustworthy extract, and a measured verdict on the data.

**Stack:** `pandas` · `numpy` · `matplotlib` · `streamlit` · `Python` | **Status:** completed | **Year:** 2022 · rebuilt 2026

> 🇫🇷 *Version française plus bas — [aller à la version FR](#-version-française).*

---

## 1. The one-sentence sell

Most "clean" extracts pass column-by-column checks and still ship impossible foods. Using a biologist's reflexes, this project catches what per-column validation cannot — **1 product in 19 turns out to be physically impossible** — and keeps only the ~95% that a food-scoring app can safely display.

## 2. The 7 cleaning steps (and how far each goes here)

Data cleaning, done as a reproducible, tested pipeline — not eyeballed in a notebook.

| Step | What it does | In this project |
|---|---|---|
| 1. Duplicates | remove repeated records | code / name / serving-size dedup (legacy), + invalid-name removal |
| 2. Missing values | drop / impute / keep | columns >50% empty dropped; fibre-zeros diagnosed (see §5) |
| 3. Out-of-bounds | univariate physical limits | mass ≤ 100 g/100g, energy ≤ 3800 kJ |
| 4. Cross-field consistency | laws between variables | 6 biochemical checks — the heart of this rebuild (§4) |
| 5. Units | harmonise scales | kcal↔kJ mix-ups detected via Atwater |
| 6. Normalisation | types, case, whitespace | grade case, group trimming, invalid names |
| 7. Final validation | does the extract hold its contracts? | `physical_validity_report` + physically-clean extract |

## 3. Method & scope

Keep product identity + 7 per-100g nutrients + the Nutri-Score grade/score + the PNNS food group. Drop the ~170 near-empty columns. Then two cleaning layers:

- **Per-column bounds** (the obvious errors): a mass nutrient > 100 g/100g, energy above pure fat.
- **Cross-field biochemistry** (the hidden errors): the physical laws a food cannot break.

All logic lives in `src/eda.py` — pure, dependency-light (numpy/pandas, no scipy), unit-tested on tiny synthetic frames in CI without the dataset.

## 4. The biochemical validation — the differentiator

A dataset can clear every per-column check and still describe foods that cannot exist. These are the laws a biologist checks:

- **Subset hierarchies.** Saturated fat ≤ total fat; sugars ≤ carbohydrates. A subset can't exceed its set. → **215** sat-fat and **521** sugar violations.
- **Mass balance.** fat + carbohydrate + (fibre) + protein ≤ 100 g/100g; the rest is water, salt, ash. → **~1,350** impossible rows (tolerance +1 g for label rounding).
- **Atwater energy floor.** Each macro has a minimum energy density (fat 37, carb/protein 17, fibre 8 kJ/g), so declared energy can't fall far below the composition's energy. → **~2,300** rows with energy physically too low.
- **kcal↔kJ unit errors.** Energy logged in kcal reads ~4.18× too low — detected when it matches Atwater/4.184. → **~800** correctable unit mix-ups (flagged, not deleted).
- **Empty records.** 0 kJ with 0 fat/carb/protein/sugar isn't a food. → **~3,800** ghost rows.

**Total: 8,141 / 155,395 products (5.24%) are physically impossible — 1 in 19.** Removing them yields a **physically-clean extract of 147,254 products**.

### Thresholds are chosen, and defended
Soft parameters aren't magic numbers — each sits on a stable plateau:

- **Energy floor `slack = 0.7`.** Flagged share by slack: 0.5→0.6%, 0.6→0.9%, **0.7→1.5%**, 0.8→3.0%, 0.9→10.7%. Above 0.8 it starts flagging fibre-rich dry foods (cereals, bran) whose energy legitimately sits just under the naive floor; 0.7 is the elbow — strict, but not punishing real food.
- **Mass-balance `tol = 1 g`.** Count is flat between 0.5 g and 2 g (~1,300 rows), so the result is insensitive to the exact value; 1 g simply absorbs label rounding.

### One honest caveat: the fibre convention
Open Food Facts mixes two conventions (EU: fibre reported apart from carbs; US: fibre inside carbs). The mass-balance check adds fibre **per row only when `sugars+fibre > carbs`** (fibre demonstrably outside carbs), otherwise treats it as already counted. This is a **defensible heuristic, not a certainty** — the inequality could also be tripped by a data-entry error. It is applied conservatively (it only ever *removes* fibre from the sum, never invents a violation).

## 5. Diagnostics worth reporting (not every flag is a deletion)

- **`dry_matter_implausible` — a review signal, not an error count.** ~13k products leave implausibly little room for water, yet these are **flagged, never deleted**: pure oils/sugars are legitimately dry, so the signal is for review, not a verdict. Reported as a question, not a result.
- **Fibre zeros.** `fiber_100g` is 100% filled but **45% are exactly 0** — almost certainly imputed, not measured. Tested impact: treating those zeros as missing **does not move the Nutri-Score** (the formula caps fibre points fast), so it's a documented data-quality limit, not a correction worth making.
- **`nutrition-score-uk` ignored on purpose.** It correlates 0.98 with the French score and is identical for 97% of products — redundant, so the analysis keeps only the French one.

## 6. Does the food group drive nutrition? (statistical tests)

On the 26,870 products carrying a food group: one-way **ANOVA** shows the group explains **57–69%** of the variance in carbohydrates, energy and sugars (η²), far less for fibre (20%). **χ²** links the Nutri-Score grade to the group (Cramér's V = 0.40) — moderate: category matters, but isn't destiny. Implemented in pure numpy/pandas (F and χ² tail probabilities included).

## 7. Step back — a critique of the Nutri-Score label

With a clean extract carrying the official score, a natural question closes the project: **how much of the Nutri-Score can be rebuilt from nutrients alone, and where does it fail?** Re-implementing the 2017 FSAm-NPS formula and comparing to the official score:

- **84% of grades land within one grade**, but a **systematic bias of −4.18 points** (95% CI [−4.21, −4.16], n=112,748): the nutrients-only score is consistently *too lenient*.
- **The bias is structural, not a data artefact** — it barely moves on the physically-clean extract. Its cause is the two official inputs Open Food Facts doesn't provide here: **salt** (a penalty) and **fruit/vegetable %** (a bonus).
- The blind spots map onto the right foods: salty products (fish/meat/eggs, salty snacks) are judged too kindly without salt; fruit & vegetables too harshly without their bonus.

A reminder that even a public, well-designed label leans on inputs a dataset may not carry — and that knowing *which* inputs is a domain question, not a modelling one.

## 8. Interactive demo

`app/streamlit_app.py` — pick a product and see its **official vs. reconstructed grade**, the **nutrients driving the score**, and a **healthier alternative** from the same category. Runs on the physically-clean extract locally, and on a small versioned sample (`data/demo_sample.csv`, ~4k products) when deployed.

```bash
streamlit run app/streamlit_app.py
```

**Deploy on Streamlit Community Cloud (free):**
1. Push this repo to GitHub (the ~4k-product `data/demo_sample.csv` is versioned on purpose; the 20 MB extract is not).
2. Go to [share.streamlit.io](https://share.streamlit.io) → *New app* → pick this repo.
3. Main file path: `app/streamlit_app.py`. Deploy — you get a public URL for the portfolio.

## 9. Limits & critical review

- **Thresholds are expert choices**, justified by sensitivity plateaus (§4) but not by a formal cross-validation — acceptable for a cleaning project, stated plainly.
- **The fibre convention is inferred per row** (§4), the most contestable step; applied conservatively.
- **Statistical tests cover only the 17%** of products with a food group; they don't generalise to the ungraded majority.
- **Fibre zeros are imputed** (§5): any fibre-specific claim would need the raw, un-imputed field.
- Crowdsourced data skews toward **processed, branded products**.
- **Two Nutri-Score inputs are missing by construction — and deliberately not back-filled.** Salt/sodium and the fruit-vegetable % are absent from this 2022 extract, which is why the nutrients-only reconstruction carries a −4.18-point bias (§7). They are *not* recovered from a current Open Food Facts export: the database keeps no dated historical dump ([OFF support](https://support.openfoodfacts.org/help/fr-fr/12-donnees-api/105-comment-puis-je-acceder-aux-donnees-historiques)), so grafting 2024+ salt onto 2022 composition would mix two record versions — a temporal leak. This extract is therefore **frozen at its 2022 vintage** (tag `v1.0-2022-biochem`); the salt + fruit/veg enrichment lives in the single-vintage 2026 rebuild, where every field comes from the same snapshot.

## 10. Conclusion

A cleaning pipeline where **biochemistry does the filtering**: mass balance, Atwater energy and subset laws catch the 1-in-19 products that per-column checks miss, leaving 147k trustworthy foods — and a demo that shows what the cleaning buys. The step-back on the Nutri-Score turns the leftover error into an honest read on a real label's blind spots.

---

## 🗂️ Repository structure

```
p3-nutrition-openfoodfacts-eda/
├── src/
│   ├── eda.py              # cleaning + biochemical checks (pure, no scipy)
│   ├── run_eda.py          # reproducible EDA → dark SVG figures + results.json
│   ├── nutriscore.py       # Nutri-Score reconstruction + blind-spot analysis
│   ├── run_nutriscore.py   # reconstruction run → figures + results
│   └── make_clean_extract.py  # physically-clean extract + audit report
├── app/
│   └── streamlit_app.py    # interactive demo
├── tests/                  # pytest — cleaning, biochemistry, Nutri-Score
├── data/README.md          # source + license (data not versioned)
└── docs/figures/           # dark SVG charts
```

## ▶️ Reproduce

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# place the cleaned extract in data/ — see data/README.md
python src/make_clean_extract.py --data data/clean_df_col_nrj7.csv --out data/physically_clean.csv --report results_physical_audit.json
python src/run_nutriscore.py --data data/physically_clean.csv --out docs/figures --results results_nutriscore.json
streamlit run app/streamlit_app.py
```

## 🧪 Dev / tests

```bash
pip install -r requirements-dev.txt
ruff check src tests app
pytest -q          # runs on pure logic, no dataset needed
```

## 📦 Data

**[Open Food Facts](https://world.openfoodfacts.org/data)** — collaborative, free food database.
License **[ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)**. Raw (~GB) and cleaned extracts are **not** versioned — see [`data/README.md`](data/README.md).

---

# 🇫🇷 Version française

> **Une question :** *peut-on faire confiance à une base nutritionnelle collaborative au point d'en faire une app de scoring alimentaire ?*
> Projet de **nettoyage de données** sur **Open Food Facts** — ~180 colonnes presque vides, doublons, valeurs physiquement impossibles. La particularité : le nettoyage est guidé par la **biochimie**, pas seulement par des bornes. Bilan de masse, énergie d'Atwater, hiérarchies de sous-ensembles — les lois qu'un vrai aliment doit respecter deviennent les filtres. Résultat : un extrait plus petit mais fiable, et un verdict mesuré sur les données.

## 1. Le pitch en une phrase

La plupart des extraits « propres » passent les contrôles colonne par colonne et livrent quand même des aliments impossibles. Avec les réflexes d'une biologiste, ce projet attrape ce que la validation par colonne ne voit pas — **1 produit sur 19 est physiquement impossible** — et ne garde que les ~95 % qu'une app de scoring peut afficher sans mentir.

## 2. Les 7 étapes de nettoyage (et jusqu'où chacune va ici)

| Étape | Rôle | Dans ce projet |
|---|---|---|
| 1. Doublons | retirer les répétitions | dédup code/nom/portion (legacy) + noms invalides |
| 2. Valeurs manquantes | retirer / imputer / garder | colonnes >50 % vides retirées ; zéros de fibres diagnostiqués (§5) |
| 3. Hors-bornes | limites physiques univariées | masse ≤ 100 g/100g, énergie ≤ 3800 kJ |
| 4. Cohérence inter-variables | lois entre variables | 6 contrôles biochimiques — le cœur (§4) |
| 5. Unités | harmoniser les échelles | erreurs kcal↔kJ via Atwater |
| 6. Normalisation | types, casse, espaces | casse des grades, groupes, noms invalides |
| 7. Validation finale | l'extrait tient-il ses contraintes ? | `physical_validity_report` + extrait propre |

## 3. Méthode & périmètre

Garder l'identité produit + 7 nutriments pour 100g + grade/score Nutri-Score + groupe PNNS. Retirer les ~170 colonnes quasi vides. Puis deux couches : **bornes par colonne** (erreurs évidentes) et **biochimie inter-champs** (erreurs cachées). Toute la logique est dans `src/eda.py` — pure, sans scipy, testée en CI sans le jeu de données.

## 4. La validation biochimique — le différenciateur

Un jeu de données peut passer tous les contrôles par colonne et décrire des aliments impossibles. Les lois qu'une biologiste vérifie :

- **Hiérarchies de sous-ensembles.** Gras saturés ≤ lipides ; sucres ≤ glucides. → **215** et **521** violations.
- **Bilan de masse.** lipides + glucides + (fibres) + protéines ≤ 100 g/100g ; le reste = eau, sel, cendres. → **~1 350** lignes (tolérance +1 g pour l'arrondi).
- **Plancher énergétique d'Atwater.** Chaque macro a une densité énergétique minimale, donc l'énergie déclarée ne peut pas être très inférieure à celle de la composition. → **~2 300** lignes à l'énergie trop basse.
- **Erreurs d'unité kcal↔kJ.** Une énergie saisie en kcal est ~4,18× trop basse — détectée quand elle vaut Atwater/4,184. → **~800** erreurs corrigibles (signalées, pas supprimées).
- **Fiches vides.** 0 kJ avec 0 macro n'est pas un aliment. → **~3 800** fiches fantômes.

**Total : 8 141 / 155 395 produits (5,24 %) sont physiquement impossibles — 1 sur 19.** Après retrait : **extrait propre de 147 254 produits**.

### Les seuils sont choisis, et défendus
- **Plancher énergie `slack = 0,7`.** Part signalée selon slack : 0,5→0,6 %, 0,6→0,9 %, **0,7→1,5 %**, 0,8→3,0 %, 0,9→10,7 %. Au-delà de 0,8, on accuse à tort les aliments secs riches en fibres (céréales, son) ; 0,7 est le coude — strict sans punir le vrai aliment.
- **Bilan de masse `tol = 1 g`.** Compte stable entre 0,5 et 2 g (~1 300 lignes) : résultat insensible à la valeur exacte ; 1 g absorbe l'arrondi d'étiquette.

### Un bémol assumé : la convention des fibres
OFF mélange deux conventions (UE : fibres à part des glucides ; US : fibres incluses). Le bilan de masse ajoute les fibres **par ligne seulement si `sucres+fibres > glucides`** (fibres manifestement hors glucides), sinon les considère déjà comptées. C'est une **heuristique défendable, pas une certitude** — l'inégalité pourrait aussi venir d'une erreur de saisie. Appliquée prudemment (elle ne fait que *retirer* des fibres de la somme, jamais inventer une violation).

## 5. Des diagnostics à rapporter (tout flag n'est pas une suppression)

- **`dry_matter_implausible` — un signal de revue, pas un comptage d'erreurs.** ~13k produits laissent trop peu de place à l'eau, mais ils sont **signalés, jamais supprimés** : huiles et sucres purs sont légitimement secs. Présenté comme une question, pas un résultat.
- **Zéros de fibres.** `fiber_100g` est rempli à 100 % mais **45 % valent exactement 0** — sans doute imputés. Impact testé : traiter ces zéros comme manquants **ne change pas le Nutri-Score**, donc c'est une limite documentée, pas une correction utile.
- **`nutrition-score-uk` ignoré volontairement.** Corrélé à 0,98 au score français, identique à 97 % — redondant.

## 6. Le groupe alimentaire explique-t-il la composition ?

Sur les 26 870 produits avec groupe : l'**ANOVA** montre que le groupe explique **57–69 %** de la variance des glucides, de l'énergie et des sucres (η²), bien moins pour les fibres (20 %). Le **χ²** lie le grade au groupe (V de Cramér = 0,40) — modéré. En numpy/pandas pur.

## 7. Prise de recul — une critique du Nutri-Score

Avec un extrait propre portant le score officiel, une question clôt le projet : **quelle part du Nutri-Score peut-on reconstruire à partir des seuls nutriments, et où échoue-t-elle ?** En réimplémentant la formule 2017 et en comparant au score officiel :

- **84 % des grades tombent à un grade près**, mais un **biais systématique de −4,18 points** (IC95 % [−4,21 ; −4,16], n=112 748) : le score nutriments-seuls est trop clément.
- **Le biais est structurel, pas un artefact** — il bouge à peine sur l'extrait propre. Cause : les deux entrées officielles absentes d'OFF ici, le **sel** (pénalité) et le **% fruits/légumes** (bonus).
- Les angles morts tombent sur les bons aliments : les produits salés jugés trop cléments sans le sel, les fruits/légumes trop sévèrement sans leur bonus.

Un rappel qu'un label public bien conçu repose sur des entrées qu'un jeu de données peut ne pas porter — et que savoir *lesquelles* est une question métier, pas de modélisation.

## 8. Démo interactive

`app/streamlit_app.py` — choisir un produit et voir **grade officiel vs reconstruit**, les **nutriments qui pèsent**, et une **alternative plus saine** de la même catégorie. Tourne sur l'extrait propre.

## 9. Limites & regard critique

- **Seuils = choix d'expert**, justifiés par des plateaux de sensibilité (§4), pas par une validation croisée formelle — assumé pour un projet de nettoyage.
- **Convention des fibres inférée par ligne** (§4), l'étape la plus contestable ; appliquée prudemment.
- **Tests statistiques limités aux 17 %** de produits avec groupe.
- **Zéros de fibres imputés** (§5).
- Données biaisées vers les **produits transformés**.
- **Deux entrées du Nutri-Score manquent par construction — et ne sont volontairement pas rattrapées.** Le sel/sodium et le % fruits-légumes sont absents de cet extrait 2022, d'où le biais de −4,18 points de la reconstruction nutriments-seuls (§7). On ne va *pas* les chercher dans un export Open Food Facts courant : la base ne conserve aucun dump historique daté ([support OFF](https://support.openfoodfacts.org/help/fr-fr/12-donnees-api/105-comment-puis-je-acceder-aux-donnees-historiques)), donc greffer le sel de 2024+ sur une composition de 2022 mélangerait deux versions d'une même fiche — une fuite temporelle. Cet extrait est donc **figé à son millésime 2022** (tag `v1.0-2022-biochem`) ; l'enrichissement sel + fruits/légumes vit dans la refonte 2026 à millésime unique, où chaque champ vient du même instantané.

## 10. Conclusion

Un pipeline de nettoyage où **la biochimie fait le tri** : bilan de masse, énergie d'Atwater et lois de sous-ensembles attrapent le produit sur 19 que les contrôles par colonne manquent, laissant 147k aliments fiables — et une démo qui montre ce que le nettoyage apporte. La prise de recul sur le Nutri-Score transforme l'erreur résiduelle en lecture honnête des angles morts d'un vrai label.

---

<sub>Built under <b>AnastatsIA</b> · OpenClassrooms Data Scientist — Project 3 · standardized project format</sub>
