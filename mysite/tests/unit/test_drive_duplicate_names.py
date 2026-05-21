"""Tests for drive_duplicate_names filename preference."""

from drive_duplicate_names import filename_preference_score


def test_prefers_underscore_ingest_name():
    spaced = "corrected_EC Signed Secretary Letter Rogers AA5529.pdf"
    underscored = "corrected_EC_Signed_Secretary_Letter_Rogers_AA5529.pdf"
    assert filename_preference_score(underscored) > filename_preference_score(spaced)
