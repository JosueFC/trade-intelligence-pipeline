# Supplier trade-intelligence pipeline

**Business question:** which supplier countries are gaining or losing share and price
competitiveness in a product category, and when should a buyer reconsider sourcing?

```
Census trade API --> data/raw/ (untouched JSON) --> DuckDB raw.census_imports
   --> dbt staging --> intermediate --> marts (supplier share, price alerts) --> Streamlit dashboard
        GitHub Actions: tests on every push, monthly scheduled ingest
```

## Run it on your computer

Requires Python 3.10+ and git. Windows: use PowerShell and replace `source .venv/bin/activate`
with `.venv\Scripts\activate`; `make` targets are shortcuts for the commands shown.

### Step 1: set up (once)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: dry run on synthetic data (no API needed, about 2 minutes)
Proves your machine works and shows you the finished dashboard before touching real data.
```bash
python -m pytest -q tests                 # all tests should pass
python -m scripts.make_sample_data        # loads ~1,300 fake rows
cd dbt && dbt seed --profiles-dir . && dbt build --profiles-dir . && cd ..
streamlit run dashboard/app.py
```
Expect 1 warning from `assert_data_is_fresh` (sample data ends Dec 2025). That is the freshness
test working. The injected price spike (India, HS 6403, Nov 2025) should appear under "Price alerts".

### Step 3: switch to real data
1. (Recommended) Get a free Census API key at https://api.census.gov/data/key_signup.html, then
   `export CENSUS_API_KEY=your_key`.
2. **Field names are verified.** `python -m ingest.census_imports --probe` confirmed all requested
   fields exist. Re-run it if the API ever rejects a request.
3. Edit `config/categories.yml` to the HS4 categories you care about (use your RC Imports categories).
4. Start from a clean database, then backfill:
   ```bash
   rm data/trade.duckdb
   python -m ingest.census_imports --start 2023-01
   cd dbt && dbt seed --profiles-dir . && dbt build --profiles-dir . && cd ..
   streamlit run dashboard/app.py
   ```
5. Monthly updates: `python -m ingest.census_imports --since-last` then `dbt build`.

### Things to check once real data is loaded
- **Aggregate rows.** Requests ask for `SUMMARY_LVL=DET` (individual countries) and staging also filters
  on it. Still run `select distinct cty_code, cty_name from raw.census_imports order by 1` once and add
  any leftover non-country codes to `dbt/seeds/aggregate_country_codes.csv`.
- **Units.** Quantity units differ by product (KG, NO, ...). Unit price is only comparable within one
  category and unit; check `quantity_unit` before trusting a price alert.
- **Alert threshold.** `price_alert_z` in `dbt/dbt_project.yml` (default 4). Lower = more alerts, more noise.

## Put it on GitHub
```bash
git init && git add . && git commit -m "Trade-intelligence pipeline"
# create an empty repo on GitHub, then:
git remote add origin <your-repo-url> && git push -u origin main
```
Add `CENSUS_API_KEY` under Settings > Secrets and variables > Actions. `ci.yml` runs on every push;
`ingest.yml` runs monthly (and on demand from the Actions tab).

## Category definitions
`dbt/seeds/category_labels.csv` gives each requested code a readable name for the dashboard.
`dbt/seeds/category_allowlist.csv` restricts a category to specific HS10 products. Example: 630790 is
a catch-all ("other made-up textile articles"), so only the face-mask and respirator lines are kept.
Categories absent from the allowlist keep every product. A dbt test fails if a restricted category
contains a product that is not on its list.

## Data grain and unit prices (important)
The API reports quantities only at HS10 detail, so ingestion pulls every HS10 code under each HS4
category (wildcard `6403*`) and the models roll up to HS4. Supplier shares use full import value.
Unit prices use only lines reporting the category's dominant unit (pairs, kilograms, ...), and a
supplier's average price partly reflects its mix of HS10 products. Say so in your write-up; it shows
you understand the limits of the data.

## Design decisions to explain in interviews
- **Raw landing zone** keeps every API response so any model can be rebuilt without re-calling the API.
  The monthly GitHub Actions job saves it (with the database) as a run artifact and restores it next run.
- **Idempotent loads:** each month x category partition is deleted and re-inserted in one transaction;
  reruns and backfills cannot duplicate rows. Re-pulling the newest 3 months on each run handles
  Census revisions.
- **Failure handling:** a failed partition is logged to `raw.ingest_log` (status and error) and the run
  continues, then exits non-zero with a summary; rerunning with `--resume` retries only what is missing.
  Schema drift is the one error that stops the run, because it would affect every partition.
- **Schema contract:** header drift fails loudly instead of silently loading wrong columns.
- **Tests that can fail** (each was checked by breaking the data on purpose):
  - *Reconciliation:* the sum of country values must match the API's own "TOTAL FOR ALL COUNTRIES"
    row within 1% (catches a dropped country, a bad filter or a partial load). Warns for now.
  - *Duplicate source rows* in staging fail the build.
  - *dbt unit tests* prove that quantities in different units are never added together and that rows
    without a unit or quantity are never priced.
  - Allowlist, not-null and freshness checks; pytest covers loading, retries, resume and failures.
- **Synthetic data includes the messy cases:** a country that disappears, a null unit, a unit switch,
  a zero-value row and an injected price spike.
- **Known limitations / next steps:**
  - Persistence uses Actions artifacts (kept 90 days; the job runs monthly). A production version would
    use MotherDuck, BigQuery or Snowflake plus object storage for the raw files, and an orchestrator.
  - The price-alert rule is a z-score against a trailing 12 months, which is fragile when the history
    itself contains spikes. A changepoint method would detect sustained level shifts better.
  - Quantity-unit reporting in the source data is noisy for some categories (masks), so unit prices
    there should be read with the trade-value threshold on the dashboard.
