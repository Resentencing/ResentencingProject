"""Tests for log vs database reconciliation."""
import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from log_reconcile import _match_row, load_log_reconcile  # noqa: E402


def test_match_row_db_sets():
    db_cdcr = {"D63289"}
    db_case = {"13CF3862"}
    db_name_county = {("SMITH", "LOS ANGELES")}
    assert _match_row("D63289", "", "", "", db_cdcr, db_case, db_name_county) == (True, "cdcr")
    assert _match_row("", "13CF3862", "", "", db_cdcr, db_case, db_name_county) == (True, "case")
    assert _match_row("", "", "John Smith", "Los Angeles", db_cdcr, db_case, db_name_county) == (
        True,
        "name+county",
    )
    assert _match_row("ZZ99999", "", "", "", db_cdcr, db_case, db_name_county) == (False, None)


def test_load_log_reconcile_matches_database(tmp_path, monkeypatch):
    excel_dir = tmp_path / "Excel"
    excel_dir.mkdir()
    log_path = excel_dir / "tracking.xlsx"
    df = pd.DataFrame(
        {
            "CDC #": ["AB1111", "ZZ9999"],
            "Case #": ["", ""],
            "Inmate's Last Name": ["Smith", "Nobody"],
            "Category": ["Gun Enhancements", "Gun Enhancements"],
            "County": ["Los Angeles", "Los Angeles"],
            "Institution": ["", ""],
            "Date Letter Created": ["2020-01-01", "2020-01-01"],
            "Date Letter Sent to Secretary's Office": ["2020-02-01", "2020-02-01"],
            "Secretary's Decision": ["Approved", "Approved"],
        }
    )
    df.to_excel(log_path, sheet_name="1170(d)(1)", index=False)

    import log_reconcile as lr

    monkeypatch.setattr(lr, "EXCEL_DIR", excel_dir)
    monkeypatch.setattr(lr, "_LOG_RECONCILE_CACHE", {"data": None, "ts": 0.0})

    with patch.object(
        lr,
        "_load_db_match_sets",
        return_value=({"AB1111"}, set(), set(), []),
    ):
        data = load_log_reconcile(force=True)

    assert not data.get("error"), data.get("error")
    assert data["total_log"] == 2
    assert data["matched"] == 1
    assert data["missing_count"] == 1
    assert data["missing"][0]["cdcr"] == "ZZ9999"
