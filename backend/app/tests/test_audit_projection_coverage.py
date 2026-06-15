"""Tests for scripts.audit_projection_coverage (B0-J1 data-quality audit)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Prospect, ProspectDraftProjection
from scripts.audit_projection_coverage import build_report


def _add_prospect(
    db: Session,
    *,
    name: str,
    upside: float = 80.0,
    ppg: float = 14.0,
    stats_source: str | None = None,
    stats_confidence: float | None = None,
) -> Prospect:
    p = Prospect(
        year=2026,
        name=name,
        position="PG",
        age=19.0,
        height="6-4",
        weight=190,
        school_or_league="Test U",
        ppg=ppg,
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


def test_audit_lists_high_upside_no_projection(db_session: Session) -> None:
    """A prospect with upside >= min_upside and no projection must show up."""
    _add_prospect(db_session, name="High Upside No Proj", upside=82.0)
    _add_prospect(db_session, name="Low Upside No Proj", upside=60.0)
    with_proj = _add_prospect(db_session, name="Has Proj", upside=85.0)
    db_session.add(
        ProspectDraftProjection(
            prospect_id=with_proj.id,
            year=2026,
            expected_pick=1,
            draft_range_min=1,
            draft_range_max=3,
            tier=1,
            source="consensus_reference",
            confidence=0.8,
        )
    )
    db_session.commit()

    report = build_report(db_session, min_upside=76.0, top_n=0)

    names = [e["name"] for e in report.high_upside_no_projection]
    assert "High Upside No Proj" in names
    assert "Has Proj" not in names  # has projection, excluded
    assert "Low Upside No Proj" not in names  # below threshold
    # conftest pre-seeds 2 prospects for 2026 (Mikel Brown Jr., Braylon
    # Mullins), so the pool is the 3 we added + those 2.
    assert report.totals["prospects"] == 5
    assert report.totals["with_projection"] == 1
    assert report.totals["without_projection"] == 4


def test_audit_lists_duplicate_name_groups(db_session: Session) -> None:
    """Jr./suffixless variants of the same identity must be flagged."""
    _add_prospect(db_session, name="Darius Acuff Jr.")
    _add_prospect(db_session, name="Darius Acuff")
    db_session.commit()

    report = build_report(db_session, min_upside=76.0, top_n=0)

    assert any(
        g["normalized"] == "darius acuff" and len(g["members"]) == 2
        for g in report.duplicate_name_groups
    )


def test_audit_lists_duplicate_stats_fingerprints(db_session: Session) -> None:
    """Two prospects with identical ppg/rpg/apg/fg/3pt/ft/stocks must be
    flagged as template-copy candidates (the B0-J Christian Anderson / Noam
    Yaacov finding)."""
    # Same stats fingerprint (all fields equal) -> template-copy signal.
    _add_prospect(
        db_session, name="Guard A", upside=80.0, ppg=14.2,
    )
    _add_prospect(
        db_session, name="Guard B", upside=78.0, ppg=14.2,
    )
    db_session.commit()

    report = build_report(db_session, min_upside=76.0, top_n=0)

    assert len(report.duplicate_stats_groups) >= 1
    group = report.duplicate_stats_groups[0]
    member_names = {m["name"] for m in group["members"]}
    assert {"Guard A", "Guard B"} <= member_names
    assert group["stats"]["ppg"] == 14.2


def test_audit_clean_pool_reports_no_duplicate_problems(
    db_session: Session,
) -> None:
    """Adding a single distinct prospect must not produce any duplicate
    name/stats groups.  (The conftest pre-seeds Mikel Brown Jr. and Braylon
    Mullins, so we only assert the duplicate-focused sections are clean for
    the row we add, not that the whole pool is empty.)"""
    _add_prospect(db_session, name="Distinct Solo Player", upside=80.0, ppg=20.0)
    db_session.commit()

    report = build_report(db_session, min_upside=76.0, top_n=0)

    # No duplicate *name* groups involve the distinct prospect we added.
    solo_norm = "distinct solo player"
    assert all(g["normalized"] != solo_norm for g in report.duplicate_name_groups)
    # And the distinct prospect is not part of any duplicate stats group.
    for g in report.duplicate_stats_groups:
        member_names = {m["name"] for m in g["members"]}
        assert "Distinct Solo Player" not in member_names


# ---------------------------------------------------------------------------
# B0-K1a: selected_top_n_no_projection must read stats provenance from the
# ORM Prospect, not from the pydantic schema object (which has no
# stats_source / stats_confidence fields).  Without this fix the section
# reported "unknown" for prospects whose ORM row carries a real source.
# ---------------------------------------------------------------------------


def test_selected_top_n_reads_stats_source_from_orm_not_schema(
    db_session: Session,
) -> None:
    """A prospect selected in the first N picks whose ORM row carries
    stats_source="nba_importer_heuristic" must surface that source in the
    selected_top_n_no_projection section, NOT "unknown".

    The simulation returns a pydantic schema ProspectRead that has no
    stats_source field; the audit must re-query the ORM Prospect by id and
    read the real provenance.  We seed a high-upside prospect (outranks the
    conftest's Mikel Brown Jr. upside=86) so he is selected at pick #2.
    """
    selected = _add_prospect(
        db_session,
        name="Top Pick Heuristic",
        upside=95.0,  # outranks Mikel (86) -> selected first
        stats_source="nba_importer_heuristic",
        stats_confidence=0.30,
    )
    db_session.commit()

    report = build_report(db_session, min_upside=76.0, top_n=5)

    # No error entry from the best-effort simulation path.
    assert not any("error" in e for e in report.selected_top_n_no_projection)
    # Find the entry for our prospect.
    matches = [
        e for e in report.selected_top_n_no_projection
        if e.get("id") == selected.id
    ]
    assert matches, (
        "expected our high-upside prospect to appear in selected_top_n; "
        f"got: {report.selected_top_n_no_projection}"
    )
    entry = matches[0]
    # The fix: provenance comes from the ORM row, not the schema object.
    assert entry["stats_source"] == "nba_importer_heuristic"
    assert entry["stats_confidence"] == 0.30


def test_selected_top_n_falls_back_to_unknown_when_orm_row_missing(
    db_session: Session,
) -> None:
    """If for some reason the ORM re-query misses (row deleted between sim
    and audit), the audit must not crash and must report "unknown".

    We cannot easily delete the row mid-sim in this fixture, so this test
    instead documents the fallback behaviour by asserting that a freshly
    selected prospect with no stats_source still reports "unknown" cleanly
    (the schema-object fallback path)."""
    selected = _add_prospect(
        db_session,
        name="Top Pick Legacy",
        upside=95.0,  # outranks Mikel -> selected first
        stats_source=None,  # legacy row, no provenance
        stats_confidence=None,
    )
    db_session.commit()

    report = build_report(db_session, min_upside=76.0, top_n=5)

    matches = [
        e for e in report.selected_top_n_no_projection
        if e.get("id") == selected.id
    ]
    assert matches, (
        "expected our prospect to appear in selected_top_n; "
        f"got: {report.selected_top_n_no_projection}"
    )
    entry = matches[0]
    assert entry["stats_source"] == "unknown"
    assert entry["stats_confidence"] is None
