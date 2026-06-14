"""Tests for app.utils.nameutils (B0-J1 normalized-name duplicate guard)."""

from __future__ import annotations

from app.utils.nameutils import (
    find_duplicate_name_groups,
    group_by_normalized_name,
    normalized_name,
)


class TestNormalizedName:
    def test_darius_acuff_jr_collapses_to_darius_acuff(self) -> None:
        # The exact B0-J regression: NBA.com lists "Darius Acuff" while the
        # local seed has "Darius Acuff Jr.".  They must normalize equal.
        assert normalized_name("Darius Acuff Jr.") == normalized_name("Darius Acuff")
        assert normalized_name("Darius Acuff Jr.") == "darius acuff"

    def test_suffixes_stripped(self) -> None:
        for suffix in ("Jr.", "Jr", "Sr.", "Sr", "II", "III", "IV"):
            base = "Test Player"
            assert normalized_name(f"{base} {suffix}") == "test player", suffix

    def test_punctuation_and_apostrophes_stripped(self) -> None:
        # Ja'Kobi / Ja’Kobi / Ja-Kobi all collapse.
        assert normalized_name("Ja’Kobi Gillespie") == "jakobi gillespie"
        assert normalized_name("Ja'Kobi Gillespie") == "jakobi gillespie"
        assert normalized_name("Ja-Kobi Gillespie") == "jakobi gillespie"
        # Initial-with-period style names keep their letters, drop the dots.
        assert normalized_name("A.J. Dybantsa") == "aj dybantsa"

    def test_case_and_whitespace_collapsed(self) -> None:
        assert normalized_name("  DARRYN   peterson ") == "darryn peterson"

    def test_empty_and_none(self) -> None:
        assert normalized_name("") == ""
        assert normalized_name(None) == ""

    def test_does_not_strip_firstname_junior(self) -> None:
        # Regression guard: a player whose actual first name is "Junior"
        # must NOT have it stripped (the suffix regex is anchored at EOL and
        # requires a leading space).
        assert normalized_name("Junior Smith") == "junior smith"


class TestGroupByNormalizedName:
    def test_groups_variants(self) -> None:
        names = ["Darius Acuff Jr.", "Darius Acuff", "Mikel Brown Jr."]
        groups = group_by_normalized_name(names)
        assert groups["darius acuff"] == ["Darius Acuff Jr.", "Darius Acuff"]
        assert groups["mikel brown"] == ["Mikel Brown Jr."]

    def test_preserves_original_order(self) -> None:
        # Two display variants of the same identity, in a specific order.
        names = ["Darius Acuff Jr.", "Darius Acuff"]
        groups = group_by_normalized_name(names)
        assert groups["darius acuff"] == ["Darius Acuff Jr.", "Darius Acuff"]


class TestFindDuplicateNameGroups:
    def test_returns_only_groups_with_distinct_variants(self) -> None:
        names = [
            "Darius Acuff Jr.", "Darius Acuff",  # duplicate
            "Mikel Brown Jr.", "mikel brown jr.",  # same display after lower, NOT a dup variant
            "Solo Player",
        ]
        dupes = find_duplicate_name_groups(names)
        # Only the darius acuff group has >1 distinct display variant.
        assert list(dupes.keys()) == ["darius acuff"]
        assert set(dupes["darius acuff"]) == {"Darius Acuff Jr.", "Darius Acuff"}

    def test_no_duplicates_returns_empty(self) -> None:
        names = ["Alpha Beta", "Gamma Delta"]
        assert find_duplicate_name_groups(names) == {}
