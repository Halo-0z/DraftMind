"""Tests for the official withdrawal / availability guard (M4-CC, M4-CL).

Covers:
  * Each officially withdrawn player is detected as unavailable for 2026.
  * Pavle Backo / Pavle Bačko alias both match.
  * Name normalization: case, extra whitespace, hyphens, accents.
  * Non-listed players (e.g. AJ Dybantsa) are NOT filtered.
  * draft_year != 2026 does not trigger the guard.
  * filter_available_prospects returns a new list, never mutates inputs.
  * M4-CL: return-to-school / not-final-entrant players are unavailable.
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

    # --- M4-CL: return-to-school / not-final-entrant players ---

    def test_cayden_boozer_return_to_school(self) -> None:
        # M4-CL: Cayden Boozer returned to school — not draftable for 2026.
        assert is_officially_unavailable_for_draft("Cayden Boozer", draft_year=2026)

    def test_braylon_mullins_return_to_school(self) -> None:
        # M4-CL: Braylon Mullins returned to school — not draftable for 2026.
        assert is_officially_unavailable_for_draft("Braylon Mullins", draft_year=2026)

    def test_nikolas_khamenia_not_final_entrant(self) -> None:
        # M4-CL: Nikolas Khamenia not in NBA 6/15 final remaining early-entry list.
        assert is_officially_unavailable_for_draft("Nikolas Khamenia", draft_year=2026)

    def test_jasper_johnson_not_final_entrant(self) -> None:
        # M4-CL: Jasper Johnson not in NBA 6/15 final remaining early-entry list.
        assert is_officially_unavailable_for_draft("Jasper Johnson", draft_year=2026)

    def test_niko_bundalo_not_final_entrant(self) -> None:
        # M4-CL: Niko Bundalo not in NBA 6/15 final remaining early-entry list.
        # His previous safety anchor [24,34] is cancelled by M4-CL.
        assert is_officially_unavailable_for_draft("Niko Bundalo", draft_year=2026)

    def test_cayden_boozer_case_insensitive(self) -> None:
        assert is_officially_unavailable_for_draft("cayden boozer", draft_year=2026)
        assert is_officially_unavailable_for_draft("CAYDEN BOOZER", draft_year=2026)

    def test_niko_bundalo_extra_spaces(self) -> None:
        assert is_officially_unavailable_for_draft("  Niko   Bundalo ", draft_year=2026)

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

    # --- M4-CL: market-risk / draftable players are NOT filtered ---

    def test_darryn_peterson_not_filtered(self) -> None:
        assert not is_officially_unavailable_for_draft(
            "Darryn Peterson", draft_year=2026
        )

    def test_cameron_boozer_not_filtered(self) -> None:
        # Cameron Boozer (brother of Cayden) remains draftable.
        assert not is_officially_unavailable_for_draft(
            "Cameron Boozer", draft_year=2026
        )

    def test_aday_mara_not_filtered(self) -> None:
        assert not is_officially_unavailable_for_draft("Aday Mara", draft_year=2026)

    def test_dailyn_swain_not_filtered(self) -> None:
        assert not is_officially_unavailable_for_draft(
            "Dailyn Swain", draft_year=2026
        )

    def test_henri_veesaar_not_filtered(self) -> None:
        assert not is_officially_unavailable_for_draft(
            "Henri Veesaar", draft_year=2026
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

    def test_all_return_to_school_filtered(self) -> None:
        # M4-CL: all 5 return-to-school / not-final-entrant names filtered.
        prospects = [
            _make_prospect("Cayden Boozer", 1),
            _make_prospect("Braylon Mullins", 2),
            _make_prospect("Nikolas Khamenia", 3),
            _make_prospect("Jasper Johnson", 4),
            _make_prospect("Niko Bundalo", 5),
        ]
        available = filter_available_prospects(prospects, draft_year=2026)
        assert len(available) == 0

    def test_combined_withdrawn_and_return_to_school_filtered(self) -> None:
        # M4-CL: combined unavailable set (8 withdrawn + 5 return-to-school).
        prospects = [
            _make_prospect("Tounde Yessoufou", 1),
            _make_prospect("Isiah Harwell", 2),
            _make_prospect("Malachi Moreno", 3),
            _make_prospect("Bassala Bagayoko", 4),
            _make_prospect("Marc-Owen Fodzo Dada", 5),
            _make_prospect("Pavle Backo", 6),
            _make_prospect("Francesco Ferrari", 7),
            _make_prospect("Luigi Suigo", 8),
            _make_prospect("Cayden Boozer", 9),
            _make_prospect("Braylon Mullins", 10),
            _make_prospect("Nikolas Khamenia", 11),
            _make_prospect("Jasper Johnson", 12),
            _make_prospect("Niko Bundalo", 13),
            _make_prospect("AJ Dybantsa", 14),
            _make_prospect("Cameron Boozer", 15),
            _make_prospect("Aday Mara", 16),
        ]
        available = filter_available_prospects(prospects, draft_year=2026)
        names = [p.name for p in available]
        # 13 unavailable filtered out, 3 draftable remain.
        assert len(available) == 3
        assert "AJ Dybantsa" in names
        assert "Cameron Boozer" in names
        assert "Aday Mara" in names
        # None of the unavailable should slip through.
        for unavailable in (
            "Tounde Yessoufou",
            "Isiah Harwell",
            "Malachi Moreno",
            "Bassala Bagayoko",
            "Marc-Owen Fodzo Dada",
            "Pavle Backo",
            "Francesco Ferrari",
            "Luigi Suigo",
            "Cayden Boozer",
            "Braylon Mullins",
            "Nikolas Khamenia",
            "Jasper Johnson",
            "Niko Bundalo",
        ):
            assert unavailable not in names

    def test_return_to_school_not_filtered_for_other_year(self) -> None:
        # M4-CL: guard scoped to 2026; return-to-school names NOT filtered in 2025.
        prospects = [
            _make_prospect("Cayden Boozer", 1),
            _make_prospect("Niko Bundalo", 2),
        ]
        available = filter_available_prospects(prospects, draft_year=2025)
        assert len(available) == 2

    def test_empty_input(self) -> None:
        assert filter_available_prospects([], draft_year=2026) == []
