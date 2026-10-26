# Supplier trade-intelligence pipeline
[![ci](https://github.com/JosueFC/trade-intelligence-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/JosueFC/trade-intelligence-pipeline/actions/workflows/ci.yml)

**Business question:** which supplier countries are gaining or losing share and price
competitiveness in a product category, and when should a buyer reconsider sourcing?

The pipeline tracks US imports of three categories: polyethylene film and sheet (a proxy for stretch
film), disposable rubber gloves (nitrile and latex) and face masks and respirators (including N95).

```
Census trade API --> data/raw/ (untouched JSON) --> DuckDB raw.census_imports
   --> dbt staging --> intermediate --> marts (supplier share, price alerts) --> Streamlit dashboard
        GitHub Actions: tests on every push, monthly scheduled ingest
```

## What the data shows
January to August of each year, share of US import value (Census data, loaded through this pipeline).
Each row compares 2023 with 2026, except gloves, which compare 2024 (the year before China's drop) with 2026:

| Category | China share | Other changes | Concentration (HHI) |
| --- | --- | --- | --- |
| Disposable rubber gloves | 26.7% (2024) to 1.3% (2026) | Malaysia 46.1% to 58.2%; Vietnam 3.1% to 11.1% | 3,220 to 3,904 (more concentrated) |
| Polyethylene film and sheet | 5.7% (2023) to 4.0% (2026) | Canada 55.6% to 48.3%; Vietnam 2.6% to 10.5% | 3,225 to 2,561 (less concentrated) |
| Face masks and respirators | 38.0% (2023) to 15.8% (2026) | Mexico 46.5% to 53.3%; Thailand 3.0% to 11.3% | 3,643 to 3,317 |

Glove buyers who moved away from China now depend on Malaysia for 58% of supply. Mask totals are
small ($76-94M a year), so those shares are noisy. The data shows when shares moved, not why: tariff
causes are not verified here.

## Run it

Requires Python 3.10+. The commands below are for bash. On Windows PowerShell, activate with
`.venv\Scripts\activate`, run the commands on separate lines instead of joining them with `&&`, set the
key with `$env:CENSUS_API_KEY="your_key"`, and delete the database with
`Remove-Item data\trade.duckdb* -ErrorAction SilentlyContinue`. The `make` targets are shortcuts for
the commands shown.

### 1. Set up
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Dry run on synthetic data (no API key needed, about 2 minutes)
```bash
python -m pytest -q tests
python -m scripts.make_sample_data        # loads ~3,700 synthetic rows
cd dbt && dbt seed --profiles-dir . && dbt build --profiles-dir . && cd ..
streamlit run dashboard/app.py
```
The build ends with one expected warning from `assert_data_is_fresh`, because the sample data stops
in December 2025. The injected price spike (India, HS 6403, November 2025) appears under "Price alerts".

### 3. Real data
1. Optional but recommended: get a free [Census API key](https://api.census.gov/data/key_signup.html)
   and `export CENSUS_API_KEY=your_key`.
2. Choose categories in `config/categories.yml`.
3. Backfill from a clean database:
   ```bash
   rm -f data/trade.duckdb
   python -m ingest.census_imports --start 2023-01
   cd dbt && dbt seed --profiles-dir . && dbt build --profiles-dir . && cd ..
   streamlit run dashboard/app.py
   ```
4. Monthly updates: `python -m ingest.census_imports --since-last`, then `dbt build`.
5. If the API ever rejects a request, `python -m ingest.census_imports --probe` lists its current
   field names.

In GitHub Actions, `ci.yml` runs lint, tests and a dbt build on synthetic data on every push, and needs
no secret. `ingest.yml` loads real data monthly (and on demand) and needs the `CENSUS_API_KEY`
repository secret (Settings > Secrets and variables > Actions).

Two settings you may want to change: `price_alert_z` in `dbt/dbt_project.yml` (z-score cutoff for
price alerts, default 4; lower means more alerts and more noise), and the trade-value slider in the
dashboard.

## Category definitions
Categories are HS code prefixes (4 or 6 digits); ingestion pulls every HS10 product line under each
prefix. `dbt/seeds/category_labels.csv` gives each prefix a readable name for the dashboard.
`dbt/seeds/category_allowlist.csv` restricts a category to specific HS10 products. For example, 630790
is a catch-all ("other made-up textile articles"), so only its five face-mask and respirator lines are
kept, and 4015 is limited to its two disposable-glove lines. Categories absent from the allowlist keep
every product, and a dbt test fails if a restricted category contains a product that is not on its list.

Two limits of the tariff schedule affect how results should be read. Stretch film has no code of its
own, so 392010 covers all polyethylene film and sheet. Nitrile cannot be separated from latex under
4015, so "gloves" means disposable rubber gloves.

## Data grain and unit prices
The API reports quantities only at HS10 detail, so ingestion pulls every HS10 code under each category
(for example the wildcard `4015*`) and the models roll up to category level. Supplier shares use full
import value. Unit prices use only lines reporting the category's dominant quantity unit (pairs,
kilograms, ...), so a supplier's average price partly reflects its mix of HS10 products. Price alerts
avoid that problem by comparing each HS10 product with its own history.

## Design decisions
- **Raw landing zone:** every API response is kept, so any model can be rebuilt without calling the API
  again. The monthly Actions job saves the raw files and the database as a run artifact and restores
  them on the next run.
- **Idempotent loads:** each month x category partition is deleted and re-inserted in one transaction,
  so reruns and backfills cannot duplicate rows. Census revises recent months, so `--since-last` re-pulls
  the last loaded month and `--resume` re-pulls the newest 3 months.
- **Failure handling:** a failed partition is logged to `raw.ingest_log` with its error and the run
  continues, then exits non-zero with a summary; `--resume` retries only what is missing. Schema drift
  stops the run, because it would affect every partition.
- **Schema contract:** header drift fails loudly instead of silently loading the wrong columns.
- **Tests that can fail** (the dbt tests run on deliberately messy sample data):
  - *Reconciliation:* the sum of country values must match the API's own "TOTAL FOR ALL COUNTRIES"
    row within 1%, which catches a dropped country, a bad filter or a partial load (warning for now).
  - *Duplicate source rows* in staging fail the build.
  - *dbt unit tests* prove that quantities in different units are never added together and that rows
    without a unit or quantity are never priced.
  - Allowlist, not-null and freshness checks; pytest covers loading, retries, resume and failures.
- **Synthetic data includes the messy cases:** a country that disappears, a null unit, a unit switch,
  a zero-value row and an injected price spike.

## Known limitations and next steps
- Persistence uses Actions artifacts (kept 90 days; the job runs monthly). A production version would
  use MotherDuck, BigQuery or Snowflake, object storage for the raw files, and an orchestrator.
- The price-alert rule is a z-score against the trailing 12 months, which is fragile when that history
  itself contains spikes. A changepoint method would detect sustained level shifts better.
- Census records country of origin, not the company that sold the goods, so transshipment through a
  third country is invisible.
- The monthly ingest workflow (artifact save and restore) has not yet run against the real API.
- Quantity-unit reporting is noisy for some categories (masks), so unit prices there should be read
  with the dashboard's trade-value threshold.
