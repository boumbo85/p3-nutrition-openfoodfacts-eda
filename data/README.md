# Data — Open Food Facts

The data is **not versioned** here (the raw export is several GB; the cleaned
extract is ~20 MB). Fetch it and place it in this `data/` folder.

## Source & license

**Open Food Facts** — collaborative, free food products database.
https://world.openfoodfacts.org/data

**License: [Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/).**
The database is made available under the ODbL; its contents under the Database
Contents License. Free to use, share and adapt with attribution and share-alike.

## Files

- **Raw** — `fr.openfoodfacts.org.products.csv` (tab-separated, several GB),
  downloadable from the link above. Used by `notebooks/01_cleaning.ipynb`.
- **Cleaned extract** — `clean_df_col_nrj7.csv` (~20 MB, 155,395 products ×
  17 columns), produced by the cleaning notebook and consumed by
  `src/run_eda.py`. Regenerate it from the raw export, or request it.
