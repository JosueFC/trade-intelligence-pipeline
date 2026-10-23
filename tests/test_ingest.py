import json

import pytest

from ingest import census_imports as ci


def payload(rows=2, header=None):
    header = header or ci.EXPECTED_COLUMNS
    body = [["1000", "X", "8517", "d", "100", "10", "NO", "HS4", "DET"] for _ in range(rows)]
    return [header] + body


def test_months_between_crosses_year():
    assert ci.months_between("2024-11", "2025-02") == ["2024-11", "2024-12", "2025-01", "2025-02"]


def test_load_is_idempotent(tmp_path):
    con = ci.connect(tmp_path / "t.duckdb")
    ci.load_partition(con, "2025-01", "8517", payload(3))
    ci.load_partition(con, "2025-01", "8517", payload(3))  # rerun must not duplicate
    assert con.execute("select count(*) from raw.census_imports").fetchone()[0] == 3


def test_reload_replaces_partition_with_revised_data(tmp_path):
    con = ci.connect(tmp_path / "t.duckdb")
    ci.load_partition(con, "2025-01", "8517", payload(3))
    ci.load_partition(con, "2025-01", "8517", payload(5))  # revised month has more rows
    assert con.execute("select count(*) from raw.census_imports").fetchone()[0] == 5


def test_schema_drift_fails_and_leaves_table_untouched(tmp_path):
    con = ci.connect(tmp_path / "t.duckdb")
    ci.load_partition(con, "2025-01", "8517", payload(2))
    bad = payload(2, header=[c for c in ci.EXPECTED_COLUMNS if c != "UNIT_QY1"])
    with pytest.raises(ci.SchemaDrift):
        ci.load_partition(con, "2025-01", "8517", bad)
    assert con.execute("select count(*) from raw.census_imports").fetchone()[0] == 2


class FakeResp:
    def __init__(self, status, body=""):
        self.status_code, self.text = status, body
    def json(self):
        return json.loads(self.text)


class FakeSession:
    def __init__(self, resp): self.resp = resp
    def get(self, *a, **k): return self.resp


def test_fetch_empty_means_not_published():
    with pytest.raises(ci.NotPublishedYet):
        ci.fetch("2099-01", "8517", None, FakeSession(FakeResp(204)))


def test_fetch_returns_payload():
    data = payload(2)
    out = ci.fetch("2025-01", "8517", None, FakeSession(FakeResp(200, json.dumps(data))))
    assert out == data


def test_fetch_retries_after_timeout(monkeypatch):
    import requests
    monkeypatch.setattr(ci.time, "sleep", lambda *_: None)
    data = payload(2)

    class Flaky:
        calls = 0
        def get(self, *a, **k):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise requests.exceptions.ReadTimeout("slow")
            return FakeResp(200, json.dumps(data))

    assert ci.fetch("2025-01", "8517", None, Flaky()) == data
    assert Flaky.calls == 2


def test_resume_skips_old_partitions_but_refreshes_recent(tmp_path, monkeypatch):
    con = ci.connect(tmp_path / "t.duckdb")
    for m in ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]:
        ci.load_partition(con, m, "8517", payload(2))
    fetched = []
    monkeypatch.setattr(ci, "fetch", lambda m, h, k, s=None, retries=5: fetched.append(m) or payload(2))
    ci.run(["2025-01", "2025-02", "2025-03", "2025-04", "2025-05"], ["8517"], None, con, resume=True)
    assert fetched == ["2025-03", "2025-04", "2025-05"]


def test_one_failed_partition_is_logged_and_does_not_abort_the_run(tmp_path, monkeypatch):
    con = ci.connect(tmp_path / "t.duckdb")

    def flaky_fetch(month, hs4, key, session=None, retries=5):
        if (month, hs4) == ("2025-02", "6403"):
            raise RuntimeError("HTTP 500 boom")
        return payload(2)

    monkeypatch.setattr(ci, "fetch", flaky_fetch)
    res = ci.run(["2025-01", "2025-02", "2025-03"], ["8517", "6403"], None, con)
    assert res.rows == 10                       # 5 good partitions x 2 rows
    assert [(m, h) for m, h, _ in res.failures] == [("2025-02", "6403")]
    row = con.execute("select status, error from raw.ingest_log where status = 'failed'").fetchall()
    assert row and "boom" in row[0][1]
    assert ci.report(res) == 1                  # non-zero exit code so CI / the shell notices


def test_failed_partition_is_retried_by_resume(tmp_path, monkeypatch):
    con = ci.connect(tmp_path / "t.duckdb")
    calls = []

    def fetch_once_failing(month, hs4, key, session=None, retries=5):
        calls.append(month)
        if month == "2025-01" and calls.count("2025-01") == 1:
            raise RuntimeError("transient")
        return payload(2)

    monkeypatch.setattr(ci, "fetch", fetch_once_failing)
    months = ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"]
    first = ci.run(months, ["8517"], None, con, resume=True)
    assert len(first.failures) == 1
    second = ci.run(months, ["8517"], None, con, resume=True)
    assert second.failures == []
    assert con.execute("select count(*) from raw.census_imports where month = '2025-01'").fetchone()[0] == 2


def test_schema_drift_aborts_and_is_logged(tmp_path, monkeypatch):
    con = ci.connect(tmp_path / "t.duckdb")
    bad = payload(2, header=[c for c in ci.EXPECTED_COLUMNS if c != "UNIT_QY1"])
    monkeypatch.setattr(ci, "fetch", lambda *a, **k: bad)
    with pytest.raises(ci.SchemaDrift):
        ci.run(["2025-01", "2025-02"], ["8517"], None, con)
    assert con.execute("select count(*) from raw.ingest_log where status = 'failed'").fetchone()[0] == 1
