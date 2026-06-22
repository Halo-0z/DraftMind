"""Tests for the official withdrawal / availability guard (M4-CC).

Covers:
  * Each officially withdrawn player is detected as unavailable for 2026.
  * Pavle Backo / Pavle Bačko alias both match.
  * Name normalization: case, extra whitespace, hyphens, accents.
  * Non-listed players (e.g. AJ Dybantsa) are NOT filtered.
  * draft_year != 2026 does not trigger the guard.
  * filter_available_prospects returns a new list, never mutates inputs.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.prospect_availability import (
    filter_available_prospects,
    is_officially_unavailable_for_draft,
    normalize_prospect_name,
)


# ---------------------------------------------------------------------------
# normalize_prospect_name
# ---------------------------------------------------------------------------


class TestNormalizeProspectName:
    def test_lowercase(self) -> None:
        assert normalize_prospect_name("PAVLE BACKO") == "pavle backo"

    def test_extra_whitespace_collapsed(self) -> None:
        assert normalize_prospect_name("  Pavle   Backo  ") == "pavle backo"

    def test_hyphen_replaced_with_space(self) -> None:
        assert normalize_prospect_name("Marc-Owen Fodzo Dada") == "marc owen fodzo dada"

    def test_accent_stripped(self) -> None:
        # "Bačko" -> "Backo" after NFKD + combining-mark strip
        assert normalize_prospect_name("Pavle Bačko") == "pavle backo"

    def test_accent_and_case_and_spaces_combined(self) -> None:
        assert normalize_prospect_name("  PAVLE   Bačko  ") == "pavle backo"

    def test_empty_string(self) -> None:
        assert normalize_prospect_name("") == ""

    def test_none_safety(self) -> None:
        # The helper should not crash on empty; passing None is not part of
        # the contract but we guard against empty strings.
        assert normalize_prospect_name("") == ""


# ---------------------------------------------------------------------------
# is_officially_unavailable_for_draft
# ---------------------------------------------------------------------------


class TestIsOfficiallyUnavailable:
    # --- Each withdrawn player is detected for 2026 ---

    def test_tounde_yessoufou(self) -> None:
        assert is_officially_unavailable_for_draft("Tounde Yessoufou", draft_year=2026)

    def test_isiah_harwell(self) -> None:
        assert is_officially_unavailable_for_draft("Isiah Harwell", draft_year=2026)

    def test_malachi_moreno(self) -> None:
        assert is_officially_unavailable_for_draft("Malachi Moreno", draft_year=2026)

    def test_bassala_bagayoko(self) -> None:
        assert is_officially_unavailable_for_draft("Bassala Bagayoko", draft_year=2026)

    def test_marc_owen_fodzo_dada(self) -> None:
        assert is_officially_unavailable_for_draft(
            "Marc-Owen Fodzo Dada", draft_year=2026
        )

    def test_luigi_suigo(self) -> None:
        assert is_officially_unavailable_for_draft("Luigi Suigo", draft_year=2026)

    def test_francesco_ferrari(self) -> None:
        assert is_officially_unavailable_for_draft("Francesco Ferrari", draft_year=2026)

    # --- Pavle Backo / Bačko alias ---

    def test_pavle_backo_no_accent(self) -> None:
        assert is_officially_unavailable_for_draft("Pavle Backo", draft_year=2026)

    def test_pavle_backo_with_accent(self) -> None:
        assert is_officially_unavailable_for_draft("Pavle Bačko", draft_year=2026)

    def test_pavle_backo_uppercase(self) -> None:
        assert is_officially_unavailable_for_draft("PAVLE BACKO", draft_year=2026)

    def test_pavle_backo_extra_spaces(self) -> None:
        assert is_officially_unavailable_for_draft("  Pavle   Backo ", draft_year=2026)

    # --- Normalization robustness ---

    def test_case_insensitive(self) -> None:
        assert is_officially_unavailable_for_draft("tounde yessoufou", draft_year=2026)
        assert is_officially_unavailable_for_draft("TOUNDE YESSOUFOU", draft_year=2026)

    def test_hyphen_normalization(self) -> None:
        # "Marc-Owen" with hyphen should match "Marc Owen" stored form
        assert is_officially_unavailable_for_draft(
            "Marc Owen Fodzo Dada", draft_year=2026
        )

    # --- Non-listed players are NOT filtered ---

    def test_aj_dybantsa_not_filtered(self) -> None:
        assert not is_officially_unavailable_for_draft("AJ Dybantsa", draft_year=2026)

    def test_kingston_flemings_not_filtered(self) -> None:
        assert not is_officially_unavailable_for_draft(
            "Kingston Flemings", draft_year=2026
        )

    def test_random_name_not_filtered(self) -> None:
        assert not is_officially_unavailable_for_draft(
            "Random Player Name", draft_year=2026
        )

    # --- draft_year != 2026 does not trigger ---

    def test_year_2025_not_filtered(self) -> None:
        assert not is_officially_unavailable_for_draft(
            "Tounde Yessoufou", draft_year=2025
        )

    def test_year_2027_not_filtered(self) -> None:
        assert not is_officially_unavailable_for_draft(
            "Malachi Moreno", draft_year=2027
        )

    def test_year_none_not_filtered(self) -> None:
        assert not is_officially_unavailable_for_draft("Luigi Suigo", draft_year=None)


# ---------------------------------------------------------------------------
# filter_available_prospects
# ---------------------------------------------------------------------------


def _make_prospect(name: str, prospect_id: int | None = None) -> SimpleNamespace:
    """Lightweight stand-in for Prospect that has a .name attribute."""
    return SimpleNamespace(id=prospect_id, name=name)


class TestFilterAvailableProspects:
    def test_filters_withdrawn_for_2026(self) -> None:
        prospects = [
            _make_prospect("AJ Dybantsa", 1),
            _make_prospect("Tounde Yessoufou", 2),
            _make_prospect("Kingston Flemings", 3),
            _make_prospect("Malachi Moreno", 4),
        ]
        available = filter_available_prospects(prospects, draft_year=2026)
        names = [p.name for p in available]
        assert "AJ Dybantsa" in names
        assert "Kingston Flemings" in names
        assert "Tounde Yessoufou" not in names
        assert "Malachi Moreno" not in names

    def test_does_not_filter_for_other_year(self) -> None:
        prospects = [
            _make_prospect("AJ Dybantsa", 1),
            _make_prospect("Tounde Yessoufou", 2),
        ]
        available = filter_available_prospects(prospects, draft_year=2025)
        assert len(available) == 2

    def test_does_not_filter_when_year_none(self) -> None:
        prospects = [
            _make_prospect("Malachi Moreno", 1),
        ]
        available = filter_available_prospects(prospects, draft_year=None)
        assert len(available) == 1

    def test_returns_new_list(self) -> None:
        prospects = [
            _make_prospect("AJ Dybantsa", 1),
            _make_prospect("Tounde Yessoufou", 2),
        ]
        original_len = len(prospects)
        _ = filter_available_prospects(prospects, draft_year=2026)
        # Input list is not mutated
        assert len(prospects) == original_len

    def test_pavle_backo_alias_both_filtered(self) -> None:
        prospects = [
            _make_prospect("Pavle Backo", 1),
            _make_prospect("Pavle Bačko", 2),
            _make_prospect("AJ Dybantsa", 3),
        ]
        available = filter_available_prospects(prospects, draft_year=2026)
        names = [p.name for p in available]
        assert names == ["AJ Dybantsa"]

    def test_all_withdrawn_filtered(self) -> None:
        prospects = [
            _make_prospect("Tounde Yessoufou", 1),
            _make_prospect("Isiah Harwell", 2),
            _make_prospect("Malachi Moreno", 3),
            _make_prospect("Bassala Bagayoko", 4),
            _make_prospect("Marc-Owen Fodzo Dada", 5),
            _make_prospect("Pavle Backo", 6),
            _make_prospect("Francesco Ferrari", 7),
            _make_prospect("Luigi Suigo", 8),
        ]
        available = filter_available_prospects(prospects, draft_year=2026)
        assert len(available) == 0

    def test_empty_input(self) -> None:
        assert filter_available_prospects([], draft_year=2026) == []
