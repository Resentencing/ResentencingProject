"""
Basename normalization for Google Drive duplicate filenames.

Used by ``preprocess_pdf`` (archive reuse) and ``cleanup_metadata_duplicates``.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional


def upload_basename_variants(filename: str) -> List[str]:
    """
    Ordered unique basenames (e.g. for matching ``corrected_<name>.pdf`` in archive/DB).

    Handles ``Copy of Foo.pdf``, ``Copy_of_Foo.pdf``, ``Copy (2) of Foo.pdf``,
    and trailing ``Foo (1).pdf``.
    """
    if not filename:
        return []
    variants: List[str] = []
    seen: set[str] = set()

    def add(nm: str) -> None:
        if nm and nm not in seen:
            seen.add(nm)
            variants.append(nm)

    add(os.path.basename(filename))
    if not filename.lower().endswith(".pdf"):
        return variants
    stem = filename[:-4]
    patterns = (
        r"(?i)^copy[_ -]of[_ -]+(.+)$",
        r"(?i)^copy\s*\(\d+\)\s*of\s+(.+)$",
    )
    for pat in patterns:
        m = re.match(pat, stem)
        if m:
            inner = (m.group(1) or "").strip()
            if inner:
                add(inner + ".pdf")
    m_trail = re.match(r"(?i)^(.+?)\s+\(\d+\)\s*$", stem)
    if m_trail:
        add(m_trail.group(1).strip() + ".pdf")

    return variants


def filename_preference_score(filename: str) -> tuple:
    """
    Higher is better when picking one PDF row for the same CDCR.

    Prefer underscore ingest names over legacy spaced Drive names.
    """
    base = os.path.basename(filename or "")
    return (base.count("_"), -base.count(" "), len(base))


def canonical_corrected_pdf_filename(filename: str) -> Optional[str]:
    """
    If ``filename`` is ``corrected_<Drive-duplicate-style>.pdf``, return the
    canonical ``corrected_<stripped>.pdf`` basename; else ``None``.

    Example: ``corrected_Copy_of_Letter.pdf`` → ``corrected_Letter.pdf``
    """
    if not filename:
        return None
    base = os.path.basename(filename)
    if not base.lower().endswith(".pdf") or not base.startswith("corrected_"):
        return None
    inner = base[len("corrected_") :]
    vars_ = upload_basename_variants(inner)
    if len(vars_) < 2:
        return None
    return f"corrected_{vars_[1]}"
