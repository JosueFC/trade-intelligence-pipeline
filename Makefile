.PHONY: setup probe backfill update sample build test dash
setup:    ; python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
probe:    ; python -m ingest.census_imports --probe
backfill: ; python -m ingest.census_imports --start 2023-01
update:   ; python -m ingest.census_imports --since-last
sample:   ; python -m scripts.make_sample_data
build:    ; cd dbt && dbt seed --profiles-dir . && dbt build --profiles-dir .
test:     ; python -m pytest -q tests
dash:     ; streamlit run dashboard/app.py
