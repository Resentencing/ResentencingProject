"""
1170(d) tracking log vs database reconciliation.

Used by the backend Missing Letters page (mirrors frontend Tool Hub log reconcile).
"""

from __future__ import annotations

import datetime
import io
import os
import time
from pathlib import Path

import mysql.connector
import pandas as pd
from dbconnector import database_config

MYSITE_DIR = Path(__file__).resolve().parent
EXCEL_DIR = MYSITE_DIR / "Excel"
SHEET_NAME = "1170(d)(1)"

CDCR_COL = "CDC #"
CASE_COL = "Case #"
NAME_COL = "Inmate's Last Name"
CATEGORY_COL = "Category"
COUNTY_COL = "County"
INSTITUTION_COL = "Institution"
LETTER_CREATED_COL = "Date Letter Created"

_LOG_RECONCILE_CACHE: dict = {"data": None, "ts": 0.0}
_LOG_RECONCILE_TTL = 3600


def _pick_newest_excel_in_dir(excel_dir: str | Path, *, race: bool) -> str | None:
    excel_dir = str(excel_dir)
    if not os.path.isdir(excel_dir):
        return None
    best_path = None
    best_mtime = -1.0
    for fname in os.listdir(excel_dir):
        if not fname.lower().endswith((".xlsx", ".xls", ".csv")):
            continue
        is_race = "race" in fname.lower()
        if is_race != race:
            continue
        path = os.path.join(excel_dir, fname)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best_path = path
    return best_path


def _clean_id(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.upper()
        .replace({"NAN": "", "NONE": "", "N/A": "", "NA": ""})
    )


def _load_db_match_sets() -> tuple[set[str], set[str], set[tuple[str, str]], list[dict]]:
    conn = mysql.connector.connect(**database_config)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT UPPER(TRIM(cdcr_number)) AS cdcr, "
        "       UPPER(TRIM(case_number)) AS case_num, "
        "       UPPER(TRIM(convict_name)) AS cname, "
        "       UPPER(TRIM(county)) AS county "
        "FROM metadata "
        "WHERE cdcr_number IS NOT NULL OR case_number IS NOT NULL OR convict_name IS NOT NULL"
    )
    db_rows = cursor.fetchall()
    cursor.close()
    conn.close()

    db_cdcr = {r["cdcr"] for r in db_rows if r.get("cdcr")}
    db_case = {r["case_num"] for r in db_rows if r.get("case_num")}
    db_name_county: set[tuple[str, str]] = set()
    for r in db_rows:
        cname = (r.get("cname") or "").strip()
        county = (r.get("county") or "").strip()
        if cname and county:
            db_name_county.add((cname.split()[-1], county))
    return db_cdcr, db_case, db_name_county, db_rows


def _match_row(
    cdcr: str,
    case: str,
    name: str,
    county: str,
    db_cdcr: set[str],
    db_case: set[str],
    db_name_county: set[tuple[str, str]],
) -> tuple[bool, str | None]:
    if cdcr and cdcr in db_cdcr:
        return True, "cdcr"
    if case and case in db_case:
        return True, "case"
    log_last = name.strip().upper().split()[-1] if name.strip() else ""
    log_county = county.strip().upper() if county else ""
    if log_last and log_county and (log_last, log_county) in db_name_county:
        return True, "name+county"
    return False, None


def _read_tracking_log() -> tuple[pd.DataFrame, pd.DataFrame, str | None, str | None]:
    """
    Returns (df_all_with_ids, df_letters_only, log_path, error).
    df columns are normalized; identifier columns are uppercased.
    """
    log_path = _pick_newest_excel_in_dir(EXCEL_DIR, race=False)
    if not log_path or not os.path.exists(log_path):
        return pd.DataFrame(), pd.DataFrame(), None, "Tracking log not found"

    try:
        df = pd.read_excel(log_path, sheet_name=SHEET_NAME)
    except Exception as exc:
        return pd.DataFrame(), pd.DataFrame(), log_path, f"Could not read sheet '{SHEET_NAME}': {exc}"

    df.columns = [str(c).replace("\n", " ").strip() for c in df.columns]

    if CDCR_COL not in df.columns and CASE_COL not in df.columns:
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            log_path,
            f"Expected columns not found. Columns in sheet: {list(df.columns)}",
        )

    if CDCR_COL in df.columns:
        df[CDCR_COL] = _clean_id(df[CDCR_COL])
    else:
        df[CDCR_COL] = ""
    if CASE_COL in df.columns:
        df[CASE_COL] = _clean_id(df[CASE_COL])
    else:
        df[CASE_COL] = ""

    for col in (NAME_COL, CATEGORY_COL, COUNTY_COL, INSTITUTION_COL):
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().replace({"nan": "", "None": "", "NaN": ""})

    df = df[(df[CDCR_COL] != "") | (df[CASE_COL] != "")].copy()
    total_log_raw = len(df)

    if LETTER_CREATED_COL in df.columns:
        mask = (
            df[LETTER_CREATED_COL].notna()
            & (df[LETTER_CREATED_COL].astype(str).str.strip().str.upper() != "NAN")
            & (df[LETTER_CREATED_COL].astype(str).str.strip() != "")
        )
        df_letters = df[mask].copy()
    else:
        df_letters = df.copy()

    return df, df_letters, log_path, None


def load_log_reconcile(force: bool = False) -> dict:
    """Compare the 1170(d) tracking log against the database (JSON-serializable)."""
    now = time.time()
    if not force and _LOG_RECONCILE_CACHE["data"] and (now - _LOG_RECONCILE_CACHE["ts"]) < _LOG_RECONCILE_TTL:
        return _LOG_RECONCILE_CACHE["data"]

    _df_all, df, log_path, err = _read_tracking_log()
    if err:
        result = {"error": err, "log_filename": os.path.basename(log_path) if log_path else None}
        _LOG_RECONCILE_CACHE["data"] = result
        _LOG_RECONCILE_CACHE["ts"] = now
        return result

    db_cdcr, db_case, db_name_county, db_rows = _load_db_match_sets()
    total_log_raw = len(_df_all)
    total_log = len(df)

    matched = []
    missing = []

    for _, row in df.iterrows():
        cdcr = row.get(CDCR_COL, "")
        case = row.get(CASE_COL, "")
        name = row.get(NAME_COL, "") if NAME_COL in df.columns else ""
        category = row.get(CATEGORY_COL, "") if CATEGORY_COL in df.columns else ""
        county = row.get(COUNTY_COL, "") if COUNTY_COL in df.columns else ""
        institution = row.get(INSTITUTION_COL, "") if INSTITUTION_COL in df.columns else ""

        in_db, match_method = _match_row(cdcr, case, name, county, db_cdcr, db_case, db_name_county)
        entry = {
            "cdcr": cdcr,
            "case": case,
            "name": name,
            "category": category,
            "county": county,
            "institution": institution,
            "match_method": match_method,
            "in_db": in_db,
        }
        (matched if in_db else missing).append(entry)

    log_cdcrs = {r for r in df[CDCR_COL].values if r}
    log_cases = {r for r in df[CASE_COL].values if r}
    extra_in_db = sum(
        1
        for r in db_rows
        if (not r.get("cdcr") or r["cdcr"] not in log_cdcrs)
        and (not r.get("case_num") or r["case_num"] not in log_cases)
    )

    log_file_modified = None
    try:
        mtime = os.path.getmtime(log_path)
        log_file_modified = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).isoformat()
    except Exception:
        pass

    result = {
        "log_filename": os.path.basename(log_path),
        "log_file_modified": log_file_modified,
        "total_log": total_log,
        "total_log_raw": total_log_raw,
        "letter_created_filter": total_log != total_log_raw,
        "matched": len(matched),
        "match_by_cdcr": sum(1 for r in matched if r["match_method"] == "cdcr"),
        "match_by_case": sum(1 for r in matched if r["match_method"] == "case"),
        "match_by_name_county": sum(1 for r in matched if r["match_method"] == "name+county"),
        "missing_count": len(missing),
        "extra_in_db_count": extra_in_db,
        "missing": missing,
        "columns_detected": {
            "cdcr": CDCR_COL,
            "case": CASE_COL,
            "name": NAME_COL,
            "category": CATEGORY_COL,
            "county": COUNTY_COL,
            "institution": INSTITUTION_COL,
        },
    }
    _LOG_RECONCILE_CACHE["data"] = result
    _LOG_RECONCILE_CACHE["ts"] = now
    return result


def _annotate_log_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    db_cdcr, db_case, db_name_county, _ = _load_db_match_sets()
    in_db_list = []
    method_list = []
    for _, row in df.iterrows():
        cdcr = row.get(CDCR_COL, "")
        case = row.get(CASE_COL, "")
        name = row.get(NAME_COL, "") if NAME_COL in df.columns else ""
        county = row.get(COUNTY_COL, "") if COUNTY_COL in df.columns else ""
        in_db, method = _match_row(cdcr, case, name, county, db_cdcr, db_case, db_name_county)
        in_db_list.append("Yes" if in_db else "No")
        method_list.append(method or "")
    out = df.copy()
    out["In Database"] = in_db_list
    out["Match Method"] = method_list
    return out


def build_export_dataframe(*, missing_only: bool = True) -> tuple[pd.DataFrame, str | None]:
    """Full tracking-log columns (+ In Database / Match Method) for download."""
    _df_all, df, log_path, err = _read_tracking_log()
    if err:
        raise RuntimeError(err)

    export_df = _annotate_log_dataframe(df)

    if missing_only:
        export_df = export_df[export_df["In Database"] == "No"].copy()

    return export_df, os.path.basename(log_path) if log_path else None


def export_reconcile_xlsx(*, missing_only: bool = True) -> tuple[bytes, str]:
    """Return (xlsx bytes, suggested filename)."""
    export_df, log_name = build_export_dataframe(missing_only=missing_only)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Missing from DB")
        meta = pd.DataFrame(
            [
                {"Field": "Source log", "Value": log_name or ""},
                {"Field": "Exported (UTC)", "Value": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                {"Field": "Row count", "Value": len(export_df)},
                {"Field": "Filter", "Value": "Tracking log rows missing from database"},
            ]
        )
        meta.to_excel(writer, index=False, sheet_name="Export info")
    buf.seek(0)
    stamp = datetime.date.today().isoformat()
    fname = f"missing_letters_from_log_{stamp}.xlsx"
    return buf.getvalue(), fname
