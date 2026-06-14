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
