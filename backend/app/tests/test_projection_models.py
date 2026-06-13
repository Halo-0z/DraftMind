import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Prospect, ProspectDraftProjection, Team, TeamPickProjection
from app.schemas.projection import (
    ProspectDraftProjectionUpsert,
    TeamPickProjectionUpsert,
)


def _prospect(db: Session, name: str = "Mikel Brown Jr.") -> Prospect:
    return db.query(Prospect).filter(Prospect.name == name).one()


def _team(db: Session, abbr: str = "SAS") -> Team:
    return db.query(Team).filter(Team.abbr == abbr).one()


def test_prospect_draft_projection_can_create(db_session: Session) -> None:
    prospect = _prospect(db_session)
    projection = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        consensus_rank=7,
        big_board_rank=8,
        expected_pick=9,
        draft_range_min=5,
        draft_range_max=14,
        tier=2,
        source="manual_projection",
        source_count=4,
        confidence=0.72,
        notes="Manual projection board input; not final answer.",
    )

    db_session.add(projection)
    db_session.commit()

    loaded = db_session.query(ProspectDraftProjection).one()
    assert loaded.prospect_id == prospect.id
    assert loaded.expected_pick == 9
    assert loaded.tier == 2
    assert loaded.source == "manual_projection"
    assert loaded.confidence == 0.72
    assert loaded.created_at is not None
    assert loaded.updated_at is not None


def test_prospect_draft_projection_unique_constraint(db_session: Session) -> None:
    prospect = _prospect(db_session)
    first = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        expected_pick=8,
        source="consensus_reference",
    )
    duplicate = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        expected_pick=9,
        source="consensus_reference",
    )

    db_session.add(first)
    db_session.commit()
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_prospect_draft_projection_schema_validates_rank_and_confidence() -> None:
    with pytest.raises(ValidationError):
        ProspectDraftProjectionUpsert(
            prospect_id=1,
            year=2026,
            consensus_rank=0,
            source="manual_projection",
        )

    with pytest.raises(ValidationError):
        ProspectDraftProjectionUpsert(
            prospect_id=1,
            year=2026,
            expected_pick=61,
            source="manual_projection",
        )

    with pytest.raises(ValidationError):
        ProspectDraftProjectionUpsert(
            prospect_id=1,
            year=2026,
            confidence=1.2,
            source="manual_projection",
        )


def test_team_pick_projection_can_create(db_session: Session) -> None:
    prospect = _prospect(db_session)
    team = _team(db_session)
    projection = TeamPickProjection(
        year=2026,
        pick_no=2,
        team_id=team.id,
        prospect_id=prospect.id,
        projection_type="team_report",
        source="manual_projection",
        confidence=0.68,
        notes="Team-specific prediction signal, not a locked pick.",
    )

    db_session.add(projection)
    db_session.commit()

    loaded = db_session.query(TeamPickProjection).one()
    assert loaded.pick_no == 2
    assert loaded.team_id == team.id
    assert loaded.prospect_id == prospect.id
    assert loaded.projection_type == "team_report"
    assert loaded.source == "manual_projection"
    assert loaded.confidence == 0.68
    assert loaded.created_at is not None
    assert loaded.updated_at is not None


def test_team_pick_projection_unique_constraint(db_session: Session) -> None:
    prospect = _prospect(db_session)
    team = _team(db_session)
    first = TeamPickProjection(
        year=2026,
        pick_no=2,
        team_id=team.id,
        prospect_id=prospect.id,
        projection_type="consensus_mock",
        source="consensus_reference",
    )
    duplicate = TeamPickProjection(
        year=2026,
        pick_no=2,
        team_id=team.id,
        prospect_id=prospect.id,
        projection_type="consensus_mock",
        source="consensus_reference",
    )

    db_session.add(first)
    db_session.commit()
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_team_pick_projection_schema_validates_pick_and_confidence() -> None:
    with pytest.raises(ValidationError):
        TeamPickProjectionUpsert(
            year=2026,
            pick_no=0,
            team_id=1,
            prospect_id=1,
            projection_type="manual_prediction",
            source="manual_projection",
        )

    with pytest.raises(ValidationError):
        TeamPickProjectionUpsert(
            year=2026,
            pick_no=61,
            team_id=1,
            prospect_id=1,
            projection_type="manual_prediction",
            source="manual_projection",
        )

    with pytest.raises(ValidationError):
        TeamPickProjectionUpsert(
            year=2026,
            pick_no=14,
            team_id=1,
            prospect_id=1,
            projection_type="manual_prediction",
            source="manual_projection",
            confidence=-0.1,
        )
