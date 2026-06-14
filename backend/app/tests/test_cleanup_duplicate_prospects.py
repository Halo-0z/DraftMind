"""Tests for scripts.cleanup_duplicate_prospects (B0-J1 cleanup safety).

Covers the four-dependency protection: a duplicate row carrying ANY of
ProspectDraftProjection / TeamPickProjection / ScoutingReport /
ProspectScoutingProfile must be flagged with a warning in plan_cleanup and
must NOT be deleted by apply_cleanup.

The deletion path is exercised through the extracted ``apply_cleanup(db,
safe_actions)`` helper so tests never shell out to ``--apply`` (and the real
backend/draftmind.db is never touched -- these tests run against the
in-memory conftest db_session fixture).
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models import (
    Prospect,
    ProspectDraftProjection,
    ProspectScoutingProfile,
    ScoutingReport,
    Team,
    TeamPickProjection,
)
from scripts.cleanup_duplicate_prospects import apply_cleanup, plan_cleanup


# ---------------------------------------------------------------------------
# Fixtures: build minimal duplicate groups on the in-memory db_session.
# ---------------------------------------------------------------------------


def _add_prospect(db: Session, *, name: str, position: str = "PG") -> Prospect:
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
        upside_score=80.0,
        risk_score=25.0,
    )
    db.add(p)
    db.flush()
    return p


def _add_projection(db: Session, *, prospect: Prospect) -> ProspectDraftProjection:
    proj = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        expected_pick=5,
        draft_range_min=4,
        draft_range_max=7,
        tier=2,
        source="consensus_reference",
        confidence=0.74,
    )
    db.add(proj)
    db.flush()
    return proj


def _add_scouting_report(db: Session, *, prospect: Prospect) -> ScoutingReport:
    report = ScoutingReport(
        prospect_id=prospect.id,
        source="Test report",
        report_text="Some scouting text.",
    )
    db.add(report)
    db.flush()
    return report


def _add_scouting_profile(db: Session, *, prospect: Prospect) -> ProspectScoutingProfile:
    profile = ProspectScoutingProfile(
        prospect_id=prospect.id,
        year=2026,
        source="manual",
        shooting_volume=5,
        profile_confidence=0.5,
    )
    db.add(profile)
    db.flush()
    return profile


def _add_team_pick_projection(
    db: Session, *, prospect: Prospect
) -> TeamPickProjection:
    # Reuse an existing conftest team (SAS) so the FK is valid.
    team = db.query(Team).filter(Team.abbr == "SAS").first()
    assert team is not None, "conftest must seed SAS"
    tpp = TeamPickProjection(
        year=2026,
        pick_no=5,
        team_id=team.id,
        prospect_id=prospect.id,
        projection_type="consensus_mock",
        source="consensus_reference",
        confidence=0.62,
    )
    db.add(tpp)
    db.flush()
    return tpp


def _action_for(actions: list[dict], delete_id: int) -> dict:
    """Helper: pick the single action targeting a delete_id."""
    matches = [a for a in actions if a["delete_id"] == delete_id]
    assert len(matches) == 1, f"expected 1 action for delete_id={delete_id}, got {matches}"
    return matches[0]


# ---------------------------------------------------------------------------
# Required case 5: Darius-style canonical-with-projection + bare duplicate.
# ---------------------------------------------------------------------------


def test_plan_cleanup_keeps_canonical_with_projection_and_flags_bare_duplicate(
    db_session: Session,
) -> None:
    """Canonical Darius Acuff Jr. has a projection; bare Darius Acuff has no
    dependency.  plan_cleanup must keep the canonical and propose deleting
    the bare duplicate, with NO warning (safe to auto-apply)."""
    canonical = _add_prospect(db_session, name="Darius Acuff Jr.")
    duplicate = _add_prospect(db_session, name="Darius Acuff", position="SG")
    _add_projection(db_session, prospect=canonical)
    db_session.commit()

    actions = plan_cleanup(db_session)

    assert len(actions) == 1
    action = actions[0]
    assert action["keep_id"] == canonical.id
    assert action["keep_name"] == "Darius Acuff Jr."
    assert action["delete_id"] == duplicate.id
    assert action["delete_name"] == "Darius Acuff"
    # Bare duplicate has no dependencies -> safe to delete, no warning.
    assert action["warning"] is None
    assert action["delete_has_projection"] is False
    assert action["delete_has_team_projection"] is False
    assert action["delete_has_scouting_report"] is False
    assert action["delete_has_scouting_profile"] is False


# ---------------------------------------------------------------------------
# Required case 1: duplicate carrying a ScoutingReport is warned.
# ---------------------------------------------------------------------------


def test_plan_cleanup_warns_when_duplicate_has_scouting_report(
    db_session: Session,
) -> None:
    canonical = _add_prospect(db_session, name="Darius Acuff Jr.")
    duplicate = _add_prospect(db_session, name="Darius Acuff", position="SG")
    _add_projection(db_session, prospect=canonical)
    _add_scouting_report(db_session, prospect=duplicate)
    db_session.commit()

    actions = plan_cleanup(db_session)
    action = _action_for(actions, duplicate.id)

    assert action["delete_has_scouting_report"] is True
    assert action["warning"] is not None
    assert "ScoutingReport" in action["warning"]
    assert "review manually" in action["warning"]


# ---------------------------------------------------------------------------
# Required case 2: duplicate carrying a ProspectScoutingProfile is warned.
# ---------------------------------------------------------------------------


def test_plan_cleanup_warns_when_duplicate_has_scouting_profile(
    db_session: Session,
) -> None:
    canonical = _add_prospect(db_session, name="Darius Acuff Jr.")
    duplicate = _add_prospect(db_session, name="Darius Acuff", position="SG")
    _add_projection(db_session, prospect=canonical)
    _add_scouting_profile(db_session, prospect=duplicate)
    db_session.commit()

    actions = plan_cleanup(db_session)
    action = _action_for(actions, duplicate.id)

    assert action["delete_has_scouting_profile"] is True
    assert action["warning"] is not None
    assert "ProspectScoutingProfile" in action["warning"]


# ---------------------------------------------------------------------------
# Required case 3: apply_cleanup will not delete a row that gained a
# ScoutingReport (defensive in-txn re-check).  We simulate this by passing
# the duplicate id directly to apply_cleanup via a forged "safe" action --
# i.e. emulating the race where plan_cleanup saw no dependency but the row
# gained one before apply.
# ---------------------------------------------------------------------------


def test_apply_cleanup_refuses_to_delete_row_with_scouting_report(
    db_session: Session,
) -> None:
    canonical = _add_prospect(db_session, name="Darius Acuff Jr.")
    duplicate = _add_prospect(db_session, name="Darius Acuff", position="SG")
    _add_projection(db_session, prospect=canonical)
    _add_scouting_report(db_session, prospect=duplicate)
    db_session.commit()
    duplicate_id = duplicate.id

    # Forge a "safe" action (warning=None) to simulate the plan/apply race:
    # plan_cleanup would normally warn here, but we want to prove the
    # apply-time re-check is an independent backstop.
    forged_safe_action = {
        "normalized": "darius acuff",
        "keep_id": canonical.id,
        "keep_name": "Darius Acuff Jr.",
        "delete_id": duplicate.id,
        "delete_name": "Darius Acuff",
        "delete_has_projection": False,
        "delete_has_team_projection": False,
        "delete_has_scouting_report": False,  # deliberately stale
        "delete_has_scouting_profile": False,
        "warning": None,
    }

    with pytest.raises(RuntimeError, match="protected duplicate row"):
        apply_cleanup(db_session, [forged_safe_action])

    # Row must still exist -- nothing was deleted.
    db_session.expire_all()
    still_there = db_session.get(Prospect, duplicate_id)
    assert still_there is not None


# ---------------------------------------------------------------------------
# Required case 4: a dependency-free duplicate IS deleted by apply_cleanup.
# ---------------------------------------------------------------------------


def test_apply_cleanup_deletes_dependency_free_duplicate(db_session: Session) -> None:
    canonical = _add_prospect(db_session, name="Darius Acuff Jr.")
    duplicate = _add_prospect(db_session, name="Darius Acuff", position="SG")
    _add_projection(db_session, prospect=canonical)
    db_session.commit()
    duplicate_id = duplicate.id

    actions = plan_cleanup(db_session)
    safe_actions = [a for a in actions if not a["warning"]]
    assert len(safe_actions) == 1

    deleted = apply_cleanup(db_session, safe_actions)
    assert deleted == 1

    # Duplicate is gone, canonical survives.
    db_session.expire_all()
    assert db_session.get(Prospect, duplicate_id) is None
    assert db_session.get(Prospect, canonical.id) is not None


# ---------------------------------------------------------------------------
# Extra: the in-txn re-check also covers TeamPickProjection (the 4th dep).
# ---------------------------------------------------------------------------


def test_apply_cleanup_refuses_to_delete_row_with_team_pick_projection(
    db_session: Session,
) -> None:
    canonical = _add_prospect(db_session, name="Darius Acuff Jr.")
    duplicate = _add_prospect(db_session, name="Darius Acuff", position="SG")
    _add_projection(db_session, prospect=canonical)
    _add_team_pick_projection(db_session, prospect=duplicate)
    db_session.commit()
    duplicate_id = duplicate.id

    forged_safe_action = {
        "normalized": "darius acuff",
        "keep_id": canonical.id,
        "keep_name": "Darius Acuff Jr.",
        "delete_id": duplicate.id,
        "delete_name": "Darius Acuff",
        "delete_has_projection": False,
        "delete_has_team_projection": False,
        "delete_has_scouting_report": False,
        "delete_has_scouting_profile": False,
        "warning": None,
    }

    with pytest.raises(RuntimeError, match="protected duplicate row"):
        apply_cleanup(db_session, [forged_safe_action])

    db_session.expire_all()
    assert db_session.get(Prospect, duplicate_id) is not None
