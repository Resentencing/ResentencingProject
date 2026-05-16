"""
Tests for Database Dashboard and related admin routes.
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from OCRWebApp import (  # noqa: E402
    _latest_consistency_check_stamp,
    _load_dashboard_recent_activity,
    app,
)


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


def test_dashboard_redirects_when_not_logged_in(client):
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 302


def test_dashboard_renders_when_logged_in(client):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        (100,),  # total pdfs
        (92,),  # distinct with metadata
        (5,),  # missing_no_row
        (3,),  # needs_refresh
    ]
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_cursor)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_ctx

    with client.session_transaction() as sess:
        sess["logged_in"] = True
    with patch("OCRWebApp.pymysql.connect", return_value=mock_conn):
        with patch("OCRWebApp._load_dashboard_recent_activity", return_value=[]):
            with patch("OCRWebApp._latest_consistency_check_stamp", return_value="2026-01-01_12-00-00"):
                r = client.get("/dashboard")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert "100" in body
    assert "92" in body
    assert "8" in body  # missing_total 5+3


def test_dashboard_survives_db_error(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    with patch("OCRWebApp.pymysql.connect", side_effect=RuntimeError("db down")):
        with patch("OCRWebApp._load_dashboard_recent_activity", return_value=[]):
            with patch("OCRWebApp._latest_consistency_check_stamp", return_value="Never"):
                r = client.get("/dashboard")
    assert r.status_code == 200
    assert b"Database unavailable" in r.data


def test_dashboard_stats_requires_login(client):
    r = client.get("/dashboard_stats")
    assert r.status_code == 401


def test_dashboard_stats_json(client):
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [(200,), (180,), (10,), (4,)]
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_cursor)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_ctx

    with client.session_transaction() as sess:
        sess["logged_in"] = True
    with patch("OCRWebApp.pymysql.connect", return_value=mock_conn):
        with patch("OCRWebApp._latest_consistency_check_stamp", return_value="Never"):
            r = client.get("/dashboard_stats")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total_files"] == 200
    assert data["with_metadata"] == 180
    assert data["missing_metadata_count"] == 10
    assert data["needs_refresh_count"] == 4
    assert data["missing_total"] == 14


def test_missing_metadata_page(client):
    mock_cursor = MagicMock()
    mock_cursor.fetchall.side_effect = [
        [("a.pdf", "/path/a.pdf", 1)],
        [("b.pdf", "/path/b.pdf", "Auto-recovered note")],
    ]
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_cursor)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_ctx

    with client.session_transaction() as sess:
        sess["logged_in"] = True
    with patch("OCRWebApp.pymysql.connect", return_value=mock_conn):
        r = client.get("/missing_metadata")
    assert r.status_code == 200
    assert b"a.pdf" in r.data and b"b.pdf" in r.data


def test_run_consistency_check_requires_login(client):
    r = client.post("/run_consistency_check")
    assert r.status_code == 401


def test_run_consistency_check_success(client):
    proc = MagicMock()
    proc.returncode = 0
    proc.stderr = ""
    proc.stdout = "ok"
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    with patch("OCRWebApp.subprocess.run", return_value=proc) as m_run:
        r = client.post("/run_consistency_check")
    assert r.status_code == 200
    assert r.get_json()["success"] is True
    m_run.assert_called_once()
    assert m_run.call_args[0][0][1] == "fileconsistencycheck.py"


def test_latest_consistency_stamp_from_temp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        with patch.dict(os.environ, {"LOG_DIR": tmp}):
            assert _latest_consistency_check_stamp() == "Never"
            with open(
                os.path.join(tmp, "FileConsistencyCheck_2026-05-15_09-00-56.log"),
                "w",
            ) as f:
                f.write("ok")
            assert _latest_consistency_check_stamp() == "2026-05-15_09-00-56"


def test_load_dashboard_activity_parses_log():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "upload_safety.log")
        line = "2026-05-15 10:00:01,123 - upload_safety - INFO - Enhanced Upload: SUCCESS - done"
        with open(path, "w", encoding="utf-8") as f:
            f.write(line + "\n")
        with patch.dict(os.environ, {"LOG_DIR": tmp}):
            acts = _load_dashboard_recent_activity(max_items=5)
    assert len(acts) == 1
    assert acts[0]["type"] == "SUCCESS"
    assert "Enhanced Upload" in acts[0]["description"]
