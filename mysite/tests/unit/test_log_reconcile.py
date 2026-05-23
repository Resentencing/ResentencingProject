"""Tests for log vs archive PDF reconciliation."""
import os
import sys
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from log_reconcile import (  # noqa: E402
    _ids_from_pdf_basename,
    _match_row,
    load_log_reconcile,
)


def test_ids_from_pdf_basename_cdcr_and_case():
    cdcrs, cases = _ids_from_pdf_basename("corrected_EC Signed Secretary Letter Rogers AA5529.pdf")
    assert "AA5529" in cdcrs
    cdcrs2, cases2 = _ids_from_pdf_basename("667(a)-AT9822-Mattos.pdf")
    assert "AT9822" in cdcrs2


def test_match_row_prefers_cdcr():
    files_cdcr = {"D63289"}
    files_case = set()
    assert _match_row("D63289", "", files_cdcr, files_case) == (True, "cdcr")
    assert _match_row("XXXXX", "13CF3862", files_cdcr, {"13CF3862"}) == (True, "case")
    assert _match_row("ZZ99999", "", files_cdcr, files_case) == (False, None)


def test_load_log_reconcile_matches_archive_pdf(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "Letter_SMITH_AB1111.pdf").write_bytes(b"%PDF-1.4")

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
    monkeypatch.setenv("ARCHIVE_DIR", str(archive))

    data = load_log_reconcile(force=True)
    assert not data.get("error"), data.get("error")
    assert data["total_log"] == 2
    assert data["matched"] == 1
    assert data["missing_count"] == 1
    assert data["missing"][0]["cdcr"] == "ZZ9999"
    assert data["compare_target"] == "letter_pdfs_on_disk"


def test_load_log_reconcile_matches_queue_pdf_only(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    archive.mkdir()
    queue = tmp_path / "uploads"
    queue.mkdir()
    (queue / "Letter_JONES_CD2222.pdf").write_bytes(b"%PDF-1.4")

    excel_dir = tmp_path / "Excel"
    excel_dir.mkdir()
    log_path = excel_dir / "tracking.xlsx"
    df = pd.DataFrame(
        {
            "CDC #": ["CD2222", "ZZ9999"],
            "Case #": ["", ""],
            "Inmate's Last Name": ["Jones", "Nobody"],
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
    monkeypatch.setattr(lr, "MYSITE_DIR", tmp_path)
    monkeypatch.setattr(lr, "_LOG_RECONCILE_CACHE", {"data": None, "ts": 0.0})
    monkeypatch.setenv("ARCHIVE_DIR", str(archive))

    data = load_log_reconcile(force=True)
    assert not data.get("error"), data.get("error")
    assert data["matched"] == 1
    assert data["missing_count"] == 1
