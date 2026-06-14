"""B0-K1 tests: Prospect stats_source / stats_confidence provenance.

Covers the six required cases:

  1. seed_db writes stats_source="seed_manual", stats_confidence=0.85.
  2. import_nba_prospects build_prospect() writes
     stats_source="nba_importer_heuristic", stats_confidence=0.30.
  3. importer does NOT downgrade a seed_manual row matched via normalized
     name (the Darius Acuff / Darius Acuff Jr. case).
  4. audit_projection_coverage surfaces stats_source/stats_confidence in
     the high-upside no-projection section.
  5. legacy Prospect rows with no stats_source do not crash (read as
     "unknown", confidence None).
  6. full backend suite still passes (verified separately via the run
     command, but a guard test here confirms the model is back-compatible).

None of these tests assert on final_score or selected_player -- B0-K1 is
purely metadata and must not change selection behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models import Prospect
from scripts import seed_db
from scripts.audit_projection_coverage import build_report
from scripts.import_nba_prospects import (
    STATS_CONFIDENCE,
    STATS_SOURCE,
    _apply_importer_stats_provenance,
    build_prospect,
    update_bio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_prospect(
    db: Session,
    *,
    name: str,
    position: str = "PG",
    upside: float = 80.0,
    stats_source: str | None = None,
    stats_confidence: float | None = None,
) -> Prospect:
    p = Prospect(
        year=2026,
        name=name,
        position=position,
        age=19.0,
        height="6-4",
        weight=190,
        school_or_league="Test U",
        ppg=14.0,
        rpg=4.0,
        apg=3.0,
        fg_pct=45.0,
        three_pct=35.0,
        ft_pct=75.0,
        stocks=1.5,
        archetype="Versatile",
        upside_score=upside,
        risk_score=25.0,
        stats_source=stats_source,
        stats_confidence=stats_confidence,
    )
    db.add(p)
    db.flush()
    return p


def _seed_tuple(name: str = "Seed Test Guard") -> tuple:
    """A minimal seed_db PROSPECTS-shaped tuple (16 fields)."""
    return (
        name, "PG", 19.0, "6-4", 185, "Test U",
        17.9, 3.1, 5.9, 43.7, 34.9, 83.7, 1.0, "Pressure rim guard",
        79, 39,
    )


def _nba_row(name: str = "Importer Test Guard") -> dict:
    """A minimal NBA.com row shape consumed by build_prospect/update_bio."""
    return {
        "displayName": name,
        "position": "Guard",
        "age": "19.5",
        "heightFeet": 6,
        "heightInches": 4,
        "weightLbs": 190,
        "school": "Test U",
        "status": "Freshman",
        "country": "USA",
        "profileLink": "",
    }


# ---------------------------------------------------------------------------
# Case 1: seed_db writes seed_manual / 0.85
# ---------------------------------------------------------------------------


def test_seed_db_writes_seed_manual_provenance(db_session: Session) -> None:
    prospect = seed_db._upsert_prospect(
        db_session, year=2026, prospect_data=_seed_tuple()
    )
    db_session.commit()

    assert prospect.stats_source == "seed_manual"
    assert prospect.stats_confidence == 0.85


def test_seed_db_upsert_overwrites_unknown_to_seed_manual(db_session: Session) -> None:
    """A reclaimed legacy row (no provenance) becomes seed_manual on re-seed."""
    legacy = _add_prospect(db_session, name="Reclaim Me")  # no stats_source
    assert legacy.stats_source is None
    db_session.commit()

    reclaimed = seed_db._upsert_prospect(
        db_session, year=2026, prospect_data=_seed_tuple(name="Reclaim Me")
    )
    db_session.commit()

    assert reclaimed.id == legacy.id
    assert reclaimed.stats_source == "seed_manual"
    assert reclaimed.stats_confidence == 0.85


# ---------------------------------------------------------------------------
# Case 2: importer build_prospect writes nba_importer_heuristic / 0.30
# ---------------------------------------------------------------------------


def test_importer_build_prospect_writes_heuristic_provenance() -> None:
    prospect = build_prospect(row=_nba_row(), board_index=1)
    assert prospect.stats_source == STATS_SOURCE
    assert prospect.stats_confidence == STATS_CONFIDENCE
    assert STATS_SOURCE == "nba_importer_heuristic"
    assert STATS_CONFIDENCE == 0.30


def test_importer_update_bio_tags_unknown_row_as_heuristic(
    db_session: Session,
) -> None:
    """update_bio on a legacy row (no provenance) tags it heuristic."""
    legacy = _add_prospect(db_session, name="Importer Match")  # no stats_source
    db_session.commit()

    update_bio(legacy, _nba_row(name="Importer Match"))

    assert legacy.stats_source == "nba_importer_heuristic"
    assert legacy.stats_confidence == 0.30


# ---------------------------------------------------------------------------
# Case 3: importer must NOT downgrade a seed_manual row
# ---------------------------------------------------------------------------


def test_importer_does_not_downgrade_seed_manual_row(db_session: Session) -> None:
    """The canonical Darius case: NBA.com "Darius Acuff" matches the seeded
    "Darius Acuff Jr." via normalized name.  update_bio must refresh bio
    fields but MUST NOT overwrite stats_source=seed_manual."""
    seeded = seed_db._upsert_prospect(
        db_session,
        year=2026,
        prospect_data=_seed_tuple(name="Darius Acuff Jr."),
    )
    db_session.commit()
    assert seeded.stats_source == "seed_manual"

    # NBA.com scrape later matches this row.
    update_bio(seeded, _nba_row(name="Darius Acuff"))

    assert seeded.stats_source == "seed_manual"
    assert seeded.stats_confidence == 0.85


def test_apply_provenance_helper_skips_seed_manual() -> None:
    """Unit-level guard: the helper itself is a no-op on seed_manual rows."""
    seeded = SimpleNamespace(stats_source="seed_manual", stats_confidence=0.85)
    _apply_importer_stats_provenance(seeded)
    assert seeded.stats_source == "seed_manual"
    assert seeded.stats_confidence == 0.85

    heuristic = SimpleNamespace(stats_source=None, stats_confidence=None)
    _apply_importer_stats_provenance(heuristic)
    assert heuristic.stats_source == "nba_importer_heuristic"
    assert heuristic.stats_confidence == 0.30


def test_apply_provenance_helper_overwrites_unknown_and_heuristic() -> None:
    """An existing heuristic or unknown row is (re)tagged heuristic -- the
    importer owns those rows."""
    unknown = SimpleNamespace(stats_source=None, stats_confidence=None)
    _apply_importer_stats_provenance(unknown)
    assert unknown.stats_source == "nba_importer_heuristic"

    existing_heuristic = SimpleNamespace(
        stats_source="nba_importer_heuristic", stats_confidence=0.30
    )
    _apply_importer_stats_provenance(existing_heuristic)
    assert existing_heuristic.stats_source == "nba_importer_heuristic"


# ---------------------------------------------------------------------------
# Case 4: audit surfaces stats_source / stats_confidence
# ---------------------------------------------------------------------------


def test_audit_high_upside_section_reports_stats_source(db_session: Session) -> None:
    _add_prospect(
        db_session, name="Seed High Upside", upside=82.0, stats_source="seed_manual",
        stats_confidence=0.85,
    )
    _add_prospect(
        db_session, name="Heuristic High Upside", upside=80.0,
        stats_source="nba_importer_heuristic", stats_confidence=0.30,
    )
    db_session.commit()

    report = build_report(db_session, min_upside=76.0, top_n=0)
    by_name = {e["name"]: e for e in report.high_upside_no_projection}

    assert "Seed High Upside" in by_name
    assert "Heuristic High Upside" in by_name
    assert by_name["Seed High Upside"]["stats_source"] == "seed_manual"
    assert by_name["Seed High Upside"]["stats_confidence"] == 0.85
    assert by_name["Heuristic High Upside"]["stats_source"] == "nba_importer_heuristic"
    assert by_name["Heuristic High Upside"]["stats_confidence"] == 0.30


# ---------------------------------------------------------------------------
# Case 5: legacy rows (no stats_source) read as "unknown", no crash
# ---------------------------------------------------------------------------


def test_audit_legacy_row_reads_as_unknown(db_session: Session) -> None:
    """A pre-B0-K1 prospect with stats_source=None must not crash the audit
    and must surface as stats_source='unknown' / confidence=None."""
    _add_prospect(db_session, name="Legacy Prospect", upside=78.0)  # no source
    db_session.commit()

    report = build_report(db_session, min_upside=76.0, top_n=0)
    by_name = {e["name"]: e for e in report.high_upside_no_projection}

    assert "Legacy Prospect" in by_name
    assert by_name["Legacy Prospect"]["stats_source"] == "unknown"
    assert by_name["Legacy Prospect"]["stats_confidence"] is None


def test_prospect_model_allows_null_stats_fields(db_session: Session) -> None:
    """Backward-compat: a Prospect created without stats_source/confidence
    persists and reads back as None (the pre-B0-K1 shape)."""
    p = Prospect(
        year=2026, name="Bare Prospect", position="PG", age=19.0, height="6-4",
        weight=190, school_or_league="Test U", ppg=10.0, rpg=2.0, apg=1.0,
        fg_pct=40.0, three_pct=30.0, ft_pct=70.0, stocks=0.5,
        archetype="x", upside_score=70.0, risk_score=40.0,
    )
    db_session.add(p)
    db_session.commit()
    db_session.expire_all()

    reloaded = db_session.get(Prospect, p.id)
    assert reloaded is not None
    assert reloaded.stats_source is None
    assert reloaded.stats_confidence is None
