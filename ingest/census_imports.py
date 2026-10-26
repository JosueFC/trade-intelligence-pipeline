"""Ingest monthly US import data (by country, by HS code) from the Census international trade API.

Design:
  * Raw landing zone: every API response is saved untouched under data/raw/ before anything else.
  * Idempotent loads: each (month, hs4) partition is deleted and re-inserted in ONE transaction,
    so reruns and backfills never create duplicates.
  * Schema contract: the response header is checked against EXPECTED_COLUMNS; drift fails loudly.
  * Incremental mode: --since-last re-pulls the latest loaded month (Census revises recent months)
    and loads every month after it; months the API has not published yet are logged and skipped.

The partition key is named hs4 for history, but it holds whatever HS prefix is configured
(4 or 6 digits).

Field names were verified against the API's variable list with `--probe` (Oct 2026).
Re-run `--probe` if the API ever rejects a request; the schema check will also flag drift.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd
import requests
import yaml

BASE_URL = "https://api.census.gov/data/timeseries/intltrade/imports/hs"
DB_PATH = Path(os.environ.get("TRADE_DB", "data/trade.duckdb"))
RAW_DIR = Path(os.environ.get("TRADE_RAW_DIR", "data/raw"))

# Columns requested from the API. Verify with --probe.
EXPECTED_COLUMNS = [
    "CTY_CODE",
    "CTY_NAME",
    "I_COMMODITY",
    "I_COMMODITY_SDESC",
    "GEN_VAL_MO",      # general imports, value in USD for the month
    "GEN_QY1_MO",      # general imports, quantity 1 for the month
    "UNIT_QY1",        # unit of quantity 1 (KG, NO, ...)
    "COMM_LVL",
    "SUMMARY_LVL",   # DET = a single country, CGP = a country grouping (excluded downstream)
]

DDL = """
CREATE SCHEMA IF NOT EXISTS raw;
CREATE TABLE IF NOT EXISTS raw.census_imports (
    month        VARCHAR NOT NULL,   -- YYYY-MM
    hs4          VARCHAR NOT NULL,   -- the category requested (partition key)
    cty_code     VARCHAR,
    cty_name     VARCHAR,
    i_commodity  VARCHAR,
    commodity_desc VARCHAR,
    gen_val_mo   VARCHAR,            -- kept as text in raw; typed in dbt staging
    gen_qy1_mo   VARCHAR,
    unit_qy1     VARCHAR,
    comm_lvl     VARCHAR,
    summary_lvl  VARCHAR,            -- DET = country, CGP = country grouping
    _ingested_at TIMESTAMP DEFAULT now()
);
CREATE TABLE IF NOT EXISTS raw.ingest_log (
    month VARCHAR, hs4 VARCHAR, n_rows BIGINT, status VARCHAR, error VARCHAR,
    _logged_at TIMESTAMP DEFAULT now()
);
"""


class SchemaDrift(RuntimeError):
    pass


class NotPublishedYet(RuntimeError):
    pass


def connect(path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute(DDL)
    con.execute("ALTER TABLE raw.ingest_log ADD COLUMN IF NOT EXISTS error VARCHAR")  # older databases
    return con


def load_categories(path: str | Path) -> list[str]:
    """Read category prefixes from the config as text, rejecting codes that would break ingestion."""
    cfg = yaml.safe_load(Path(path).read_text())
    codes = [str(c["hs4"]).strip() for c in cfg["categories"]]
    for code in codes:
        if not code.isdigit() or len(code) not in (4, 6):
            raise ValueError(f"Category {code!r} must be a 4- or 6-digit HS code (quote it in the YAML)")
    if len(set(codes)) != len(codes):
        raise ValueError(f"Duplicate categories in config: {codes}")
    for a in codes:
        for b in codes:
            if a != b and b.startswith(a):
                raise ValueError(f"Category {a} already contains {b}; the same rows would load twice")
    return codes


def months_between(start: str, end: str) -> list[str]:
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fetch(month: str, hs4: str, api_key: str | None, session: requests.Session | None = None,
          retries: int = 5) -> list[list[str]]:
    """Return the API's JSON table (first row = header). Raises NotPublishedYet if no data."""
    s = session or requests.Session()
    params = {
        "get": ",".join(EXPECTED_COLUMNS),
        "time": month,
        "COMM_LVL": "HS10",          # quantities only exist at HS10 detail (verified with probe)
        "I_COMMODITY": f"{hs4}*",    # wildcard: every HS10 code under this HS4 category
        "SUMMARY_LVL": "DET",   # individual countries, not groupings (a world-total row still comes back)
    }
    if api_key:
        params["key"] = api_key
    for attempt in range(retries):
        try:
            # HS10 wildcard queries are big (~3,000 rows) and the server can be slow: allow 3 minutes.
            resp = s.get(BASE_URL, params=params, timeout=(15, 180))
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            wait = 5 * 2 ** attempt
            print(f"  {month} {hs4}: {type(e).__name__}, retry {attempt + 1}/{retries} in {wait}s")
            time.sleep(wait)
            continue
        if resp.status_code == 204 or (resp.status_code == 200 and not resp.text.strip()):
            raise NotPublishedYet(f"{month} {hs4}: empty response")
        if resp.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** attempt * 2)
            continue
        if resp.status_code == 400 and "unknown variable" in resp.text.lower():
            raise SchemaDrift(f"API rejected a requested field: {resp.text[:300]}")
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} for {month} {hs4}: {resp.text[:300]}")
        data = resp.json()
        if len(data) <= 1:
            raise NotPublishedYet(f"{month} {hs4}: header only")
        return data
    raise RuntimeError(f"Gave up after {retries} retries for {month} {hs4}")


def check_schema(header: list[str]) -> None:
    missing = [c for c in EXPECTED_COLUMNS if c not in header]
    if missing:
        raise SchemaDrift(f"Missing expected columns {missing}; got {header}")


def save_raw(month: str, hs4: str, payload: list[list[str]]) -> Path:
    p = RAW_DIR / "census_imports" / f"month={month}" / f"hs4={hs4}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload))
    return p


def load_partition(con: duckdb.DuckDBPyConnection, month: str, hs4: str,
                   payload: list[list[str]]) -> int:
    """Idempotent: delete the (month, hs4) partition and insert fresh rows in one transaction."""
    header, rows = payload[0], payload[1:]
    check_schema(header)
    idx = {c: header.index(c) for c in EXPECTED_COLUMNS}
    records = [
        (month, hs4, r[idx["CTY_CODE"]], r[idx["CTY_NAME"]], r[idx["I_COMMODITY"]],
         r[idx["I_COMMODITY_SDESC"]], r[idx["GEN_VAL_MO"]], r[idx["GEN_QY1_MO"]],
         r[idx["UNIT_QY1"]], r[idx["COMM_LVL"]], r[idx["SUMMARY_LVL"]])
        for r in rows
    ]
    df = pd.DataFrame(records, columns=[
        "month", "hs4", "cty_code", "cty_name", "i_commodity", "commodity_desc",
        "gen_val_mo", "gen_qy1_mo", "unit_qy1", "comm_lvl", "summary_lvl"])
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM raw.census_imports WHERE month = ? AND hs4 = ?", [month, hs4])
        con.register("df_part", df)
        con.execute(
            "INSERT INTO raw.census_imports (month, hs4, cty_code, cty_name, i_commodity, "
            "commodity_desc, gen_val_mo, gen_qy1_mo, unit_qy1, comm_lvl, summary_lvl) "
            "SELECT month, hs4, cty_code, cty_name, i_commodity, commodity_desc, gen_val_mo, "
            "gen_qy1_mo, unit_qy1, comm_lvl, summary_lvl FROM df_part")
        con.unregister("df_part")
        con.execute("INSERT INTO raw.ingest_log (month, hs4, n_rows, status) VALUES (?,?,?,?)",
                    [month, hs4, len(records), "ok"])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(records)


def last_loaded_month(con) -> str | None:
    row = con.execute("SELECT max(month) FROM raw.census_imports").fetchone()
    return row[0] if row else None


def probe() -> None:
    """Print the API's real variable names so EXPECTED_COLUMNS can be verified."""
    r = requests.get(f"{BASE_URL}/variables.json", timeout=60)
    r.raise_for_status()
    variables = r.json().get("variables", {})
    print(f"{len(variables)} variables at {BASE_URL}\n")
    for name in sorted(variables):
        label = variables[name].get("label", "")
        mark = "  <-- requested" if name in EXPECTED_COLUMNS else ""
        print(f"{name:28s} {label}{mark}")
    absent = [c for c in EXPECTED_COLUMNS if c not in variables]
    print("\nRequested but NOT in API:", absent or "none")


def already_loaded(con, month: str, hs4: str) -> bool:
    n = con.execute("SELECT count(*) FROM raw.ingest_log WHERE month = ? AND hs4 = ? AND status = 'ok'",
                    [month, hs4]).fetchone()[0]
    return n > 0


@dataclass
class RunResult:
    rows: int = 0
    failures: list[tuple[str, str, str]] = field(default_factory=list)   # (month, category, error)


def log_status(con, month: str, hs4: str, status: str, error: str | None = None) -> None:
    con.execute("INSERT INTO raw.ingest_log (month, hs4, n_rows, status, error) VALUES (?,?,?,?,?)",
                [month, hs4, 0, status, error])


def run(months: list[str], hs_codes: list[str], api_key: str | None,
        con: duckdb.DuckDBPyConnection, stop_on_unpublished: bool = False,
        resume: bool = False) -> RunResult:
    """Load every month x category partition.

    resume=True skips partitions already loaded, except the 3 newest months (Census revises those).
    A failed partition is logged to raw.ingest_log (status 'failed' + error) and the run continues,
    so one bad request no longer aborts a 130-request backfill. Schema drift is the exception: it
    would affect every partition, so it is logged and then re-raised.
    """
    result = RunResult()
    session = requests.Session()
    recent = set(months[-3:])
    for month in months:
        for hs4 in hs_codes:
            if resume and month not in recent and already_loaded(con, month, hs4):
                print(f"already loaded, skipping {month} hs4={hs4}")
                continue
            try:
                payload = fetch(month, hs4, api_key, session)
                save_raw(month, hs4, payload)
                n = load_partition(con, month, hs4, payload)
            except NotPublishedYet as e:
                print(f"skip: {e}")
                log_status(con, month, hs4, "not_published")
                if stop_on_unpublished:
                    return result
                continue
            except SchemaDrift as e:
                log_status(con, month, hs4, "failed", f"SchemaDrift: {e}")
                result.failures.append((month, hs4, f"SchemaDrift: {e}"))
                raise
            except Exception as e:  # noqa: BLE001 - we log everything and keep going
                msg = f"{type(e).__name__}: {e}"[:500]
                print(f"FAILED {month} hs4={hs4}: {msg}")
                log_status(con, month, hs4, "failed", msg)
                result.failures.append((month, hs4, msg))
                continue
            result.rows += n
            print(f"loaded {month} hs4={hs4}: {n} rows")
    return result


def report(result: RunResult) -> int:
    """Print a summary and return a process exit code (1 if anything failed)."""
    print(f"\ndone: {result.rows} rows loaded, {len(result.failures)} partition(s) failed")
    for month, hs4, err in result.failures:
        print(f"  FAILED {month} {hs4}: {err}")
    if result.failures:
        print("Rerun the same command with --resume to retry only what is missing.")
    return 1 if result.failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--probe", action="store_true", help="print API variables and exit")
    ap.add_argument("--start", help="first month YYYY-MM (backfill)")
    ap.add_argument("--end", help="last month YYYY-MM (default: this month)")
    ap.add_argument("--since-last", action="store_true", help="load months after the latest loaded one")
    ap.add_argument("--resume", action="store_true",
                    help="skip month/category partitions already loaded (safe to rerun after a failure)")
    ap.add_argument("--config", default="config/categories.yml")
    args = ap.parse_args(argv)

    if args.probe:
        probe()
        return 0

    hs_codes = load_categories(args.config)
    api_key = os.environ.get("CENSUS_API_KEY")
    today = dt.date.today()
    end = args.end or f"{today.year:04d}-{today.month:02d}"
    con = connect()

    if args.since_last:
        last = last_loaded_month(con)
        if last is None:
            sys.exit("Nothing loaded yet; run a backfill first with --start YYYY-MM")
        # Re-pull the last loaded month too: Census revises recent months.
        months = months_between(last, end)
        print(f"incremental: {months[0]} .. {end}")
        return report(run(months, hs_codes, api_key, con, stop_on_unpublished=False))
    if not args.start:
        sys.exit("Provide --start YYYY-MM (or --since-last / --probe)")
    return report(run(months_between(args.start, end), hs_codes, api_key, con, resume=args.resume))


if __name__ == "__main__":
    raise SystemExit(main())