"""
Record when key dataset sources were last refreshed so the public site can show
data-as-of dates (1170(d) log spreadsheet, race data Excel, letters/DB ingest).
"""

from __future__ import annotations

import datetime
import logging
from typing import Optional

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS dataset_source_refresh (
    source_key VARCHAR(32) NOT NULL PRIMARY KEY,
    refreshed_at DATETIME NOT NULL,
    detail VARCHAR(512) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def ensure_dataset_lineage_table(cursor) -> None:
    cursor.execute(CREATE_TABLE_SQL)


def touch_dataset_source(cursor, connection, source_key: str, detail: Optional[str] = None) -> None:
    """
    Upsert refreshed_at = UTC now for source_key. Commits the connection.
    source_key: main_log | race_data | letters_db
    """
    ensure_dataset_lineage_table(cursor)
    now = datetime.datetime.utcnow()
    cursor.execute(
        """
        INSERT INTO dataset_source_refresh (source_key, refreshed_at, detail)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            refreshed_at = VALUES(refreshed_at),
            detail = VALUES(detail)
        """,
        (source_key, now, (detail[:512] if detail else None)),
    )
    connection.commit()
