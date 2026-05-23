"""
1170(d) tracking log vs letter PDFs on disk.

Used by the backend Missing Letters page. Compares approved-and-sent log rows
against PDFs in the archive, upload queue (uploads/), and post-OCR staging
(processed/). Matching uses CDCR # / case # parsed from filenames. A letter
counts as present if we have the PDF anywhere in those folders, even when it
is not yet in MySQL.
"""

from __future__ import annotations

import datetime
import io
import os
import time
from pathlib import Path

import pandas as pd
from tagextraction import CASE_FILENAME_PATTERN, CDCR_FILENAME_PATTERN

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
SECRETARY_SENT_COL = "Date Letter Sent to Secretary's Office"
SECRETARY_DECISION_COL = "Secretary's Decision"

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


def _column_filled(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    return (
        df[col].notna()
        & (df[col].astype(str).str.strip().str.upper() != "NAN")
        & (df[col].astype(str).str.strip() != "")
    )


def _letter_created_mask(df: pd.DataFrame) -> pd.Series:
    """Rows where a letter was actually generated (Date Letter Created filled)."""
    if LETTER_CREATED_COL not in df.columns:
        return pd.Series(True, index=df.index)
    return _column_filled(df, LETTER_CREATED_COL)


def _approved_and_sent_mask(df: pd.DataFrame) -> pd.Series:
    """
    Actionable letters-to-request scope (professor / PRA baseline).

    Matches Letter Rebuild approved-scope: letter created, sent to Secretary,
    and Secretary's Decision = Approved. Excludes declined / no-letter rows that
    still have Date Letter Created filled (~400+ false \"missing\" otherwise).
    """
    mask = _letter_created_mask(df)
    if SECRETARY_SENT_COL in df.columns:
        mask &= _column_filled(df, SECRETARY_SENT_COL)
    if SECRETARY_DECISION_COL in df.columns:
        mask &= (
            df[SECRETARY_DECISION_COL].astype(str).str.strip().str.lower() == "approved"
        )
    return mask


def _clean_id(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.upper()
        .replace({"NAN": "", "NONE": "", "N/A": "", "NA": ""})
    )


def _resolve_pdf_dirs() -> list[Path]:
    """
    All folders scanned for letter PDFs:

    - ARCHIVE_DIR (processed letters)
    - mysite/uploads/ (Drive / queue_pdfs ingest queue)
    - mysite/processed/ (post-OCR, pre-archive)
    - LOG_RECONCILE_EXTRA_DIRS (optional, os.pathsep-separated)
    """
    dirs: list[Path] = []
    seen: set[str] = set()

    def _add(path: Path) -> None:
        resolved = str(path.resolve())
        if resolved in seen:
            return
        if path.is_dir():
            seen.add(resolved)
            dirs.append(path)

    primary = os.getenv("ARCHIVE_DIR", "/home/RSCAP/shared/archive_directory")
    primary_path = Path(primary)
    if not primary_path.is_absolute():
        primary_path = MYSITE_DIR / primary
    _add(primary_path)
    if not dirs:
        _add(MYSITE_DIR.parent / "shared" / "archive_directory")

    # Queue and staging (same paths as process_uploads.py)
    _add(MYSITE_DIR / "uploads")
    _add(MYSITE_DIR / "processed")

    extra = os.getenv("LOG_RECONCILE_EXTRA_DIRS", "").strip()
    if extra:
        for part in extra.split(os.pathsep):
            part = part.strip()
            if part:
                _add(Path(part))

    return dirs


# Back-compat alias for tests / callers
_resolve_archive_dirs = _resolve_pdf_dirs


def _ids_from_pdf_basename(fname: str) -> tuple[set[str], set[str]]:
    base_u = fname.upper()
    if base_u.endswith(".PDF"):
        base_u = base_u[:-4]
    cdcrs = {m.group(1).upper() for m in CDCR_FILENAME_PATTERN.finditer(base_u)}
    cases: set[str] = set()
    for m in CASE_FILENAME_PATTERN.finditer(base_u):
        cand = m.group(1).upper()
        if cand not in cdcrs:
            cases.add(cand)
    return cdcrs, cases


def _count_archive_pdfs_not_on_log(
    log_cdcrs: set[str], log_cases: set[str], archive_dirs: list[Path]
) -> int:
    """PDFs in archive whose CDCR/case does not appear on the approved-and-sent log."""
    extra = 0
    for adir in archive_dirs:
        for root, _, files in os.walk(adir):
            for fname in files:
                if not fname.lower().endswith(".pdf"):
                    continue
                cdcrs, cases = _ids_from_pdf_basename(fname)
                on_log = bool(cdcrs and any(c in log_cdcrs for c in cdcrs))
                on_log = on_log or bool(cases and any(c in log_cases for c in cases))
                if not on_log:
                    extra += 1
    return extra


def _load_archive_match_sets() -> tuple[set[str], set[str], int, list[str], str | None]:
    """
    Scan archive directories for PDFs; collect CDCR # and case # from filenames.

    Returns (file_cdcr, file_case, pdf_count, scanned_dir_strings, error).
    """
    archive_dirs = _resolve_pdf_dirs()
    if not archive_dirs:
        return set(), set(), 0, [], "No letter PDF folders found (set ARCHIVE_DIR or add PDFs under uploads/)"

    file_cdcr: set[str] = set()
    file_case: set[str] = set()
    pdf_count = 0
    scanned: list[str] = []

    for adir in archive_dirs:
        scanned.append(str(adir))
        for root, _, files in os.walk(adir):
            for fname in files:
                if not fname.lower().endswith(".pdf"):
                    continue
                pdf_count += 1
                cdcrs, cases = _ids_from_pdf_basename(fname)
                file_cdcr |= cdcrs
                file_case |= cases

    if pdf_count == 0:
        return (
            file_cdcr,
            file_case,
            0,
            scanned,
            "No PDFs found in archive, uploads/, or processed/ (add letters or set ARCHIVE_DIR)",
        )

    return file_cdcr, file_case, pdf_count, scanned, None


def _match_row(
    cdcr: str,
    case: str,
    file_cdcr: set[str],
    file_case: set[str],
) -> tuple[bool, str | None]:
    if cdcr and cdcr in file_cdcr:
        return True, "cdcr"
    if case and case in file_case:
        return True, "case"
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
    df_letters = df[_approved_and_sent_mask(df)].copy()

    return df, df_letters, log_path, None


def load_log_reconcile(force: bool = False) -> dict:
    """Compare the 1170(d) tracking log against letter PDFs on disk (JSON-serializable)."""
    now = time.time()
    if not force and _LOG_RECONCILE_CACHE["data"] and (now - _LOG_RECONCILE_CACHE["ts"]) < _LOG_RECONCILE_TTL:
        return _LOG_RECONCILE_CACHE["data"]

    _df_all, df, log_path, err = _read_tracking_log()
    if err:
        result = {"error": err, "log_filename": os.path.basename(log_path) if log_path else None}
        _LOG_RECONCILE_CACHE["data"] = result
        _LOG_RECONCILE_CACHE["ts"] = now
        return result

    file_cdcr, file_case, pdf_count, archive_dirs, archive_err = _load_archive_match_sets()
    archive_dirs_paths = [Path(d) for d in archive_dirs]
    if archive_err:
        result = {
            "error": archive_err,
            "log_filename": os.path.basename(log_path),
            "archive_dirs": archive_dirs,
            "archive_pdf_count": pdf_count,
        }
        _LOG_RECONCILE_CACHE["data"] = result
        _LOG_RECONCILE_CACHE["ts"] = now
        return result

    total_log_raw = len(_df_all)
    total_letter_created = int(_letter_created_mask(_df_all).sum())
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

        have_pdf, match_method = _match_row(cdcr, case, file_cdcr, file_case)
        entry = {
            "cdcr": cdcr,
            "case": case,
            "name": name,
            "category": category,
            "county": county,
            "institution": institution,
            "match_method": match_method,
            "have_pdf": have_pdf,
        }
        (matched if have_pdf else missing).append(entry)

    log_cdcrs = {r for r in df[CDCR_COL].values if r}
    log_cases = {r for r in df[CASE_COL].values if r}
    extra_archive_pdfs = _count_archive_pdfs_not_on_log(log_cdcrs, log_cases, archive_dirs_paths)

    log_file_modified = None
    try:
        mtime = os.path.getmtime(log_path)
        log_file_modified = datetime.datetime.fromtimestamp(mtime, tz=datetime.timezone.utc).isoformat()
    except Exception:
        pass

    result = {
        "log_filename": os.path.basename(log_path),
        "log_file_modified": log_file_modified,
        "compare_target": "letter_pdfs_on_disk",
        "archive_dirs": archive_dirs,
        "pdf_dirs": archive_dirs,
        "archive_pdf_count": pdf_count,
        "pdf_count": pdf_count,
        "total_log": total_log,
        "total_log_raw": total_log_raw,
        "total_letter_created": total_letter_created,
        "letter_created_filter": total_letter_created != total_log_raw,
        "request_scope_filter": "approved_and_sent",
        "request_scope_description": (
            "Date Letter Created filled; Date Letter Sent to Secretary's Office filled; "
            "Secretary's Decision = Approved"
        ),
        "matched": len(matched),
        "match_by_cdcr": sum(1 for r in matched if r["match_method"] == "cdcr"),
        "match_by_case": sum(1 for r in matched if r["match_method"] == "case"),
        "match_by_name_county": 0,
        "missing_count": len(missing),
        "extra_archive_pdf_count": extra_archive_pdfs,
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
    file_cdcr, file_case, _, _, archive_err = _load_archive_match_sets()
    if archive_err:
        raise RuntimeError(archive_err)

    have_pdf_list = []
    method_list = []
    for _, row in df.iterrows():
        cdcr = row.get(CDCR_COL, "")
        case = row.get(CASE_COL, "")
        have_pdf, method = _match_row(cdcr, case, file_cdcr, file_case)
        have_pdf_list.append("Yes" if have_pdf else "No")
        method_list.append(method or "")
    out = df.copy()
    out["Have PDF on disk"] = have_pdf_list
    out["Match Method"] = method_list
    return out


def build_export_dataframe(*, missing_only: bool = True) -> tuple[pd.DataFrame, str | None]:
    """Full tracking-log columns (+ Have PDF / Match Method) for download."""
    _df_all, df, log_path, err = _read_tracking_log()
    if err:
        raise RuntimeError(err)

    export_df = _annotate_log_dataframe(df)

    if missing_only:
        export_df = export_df[export_df["Have PDF on disk"] == "No"].copy()

    return export_df, os.path.basename(log_path) if log_path else None


def export_reconcile_xlsx(*, missing_only: bool = True) -> tuple[bytes, str]:
    """Return (xlsx bytes, suggested filename)."""
    export_df, log_name = build_export_dataframe(missing_only=missing_only)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Missing PDFs")
        meta = pd.DataFrame(
            [
                {"Field": "Source log", "Value": log_name or ""},
                {"Field": "Exported (UTC)", "Value": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                {"Field": "Row count", "Value": len(export_df)},
                {
                    "Field": "Filter",
                    "Value": (
                        "Approved-and-sent scope (letter created + sent to Secretary + "
                        "Secretary approved), no matching PDF on disk "
                        "(archive + uploads queue + processed; CDCR/case from filename)"
                    ),
                },
            ]
        )
        meta.to_excel(writer, index=False, sheet_name="Export info")
    buf.seek(0)
    stamp = datetime.date.today().isoformat()
    fname = f"missing_letters_from_log_{stamp}.xlsx"
    return buf.getvalue(), fname
