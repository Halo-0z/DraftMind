from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.draft import DraftOrder
from app.models.projection import ProspectDraftProjection, TeamPickProjection
from app.models.team import Team
from scripts import seed_db


def _team(db: Session, abbr: str, name: str) -> Team:
    team = db.query(Team).filter(Team.abbr == abbr).first()
    if team is not None:
        return team
    team = Team(
        name=name,
        abbr=abbr,
        nba_team_id=None,
        city=name.rsplit(" ", 1)[0],
        conference="Unknown",
        division="Unknown",
    )
    db.add(team)
    db.flush()
    return team


def _set_pick_owner(
    db: Session,
    *,
    pick_no: int,
    team: Team,
    original_team: str | None = None,
    notes: str | None = None,
) -> None:
    order = db.query(DraftOrder).filter_by(year=2026, pick_no=pick_no).first()
    if order is None:
        order = DraftOrder(year=2026, pick_no=pick_no)
        db.add(order)
    order.team_id = team.id
    order.original_team = original_team
    order.source = "official-test-order"
    order.notes = notes
    db.flush()


def test_seed_demo_data_does_not_overwrite_existing_official_draft_order(
    db_session: Session,
) -> None:
    expected_owners = {
        2: _team(db_session, "UTA", "Utah Jazz"),
        6: _team(db_session, "BKN", "Brooklyn Nets"),
        11: _team(db_session, "GSW", "Golden State Warriors"),
        16: _team(db_session, "MEM", "Memphis Grizzlies"),
    }
    _set_pick_owner(db_session, pick_no=2, team=expected_owners[2])
    _set_pick_owner(db_session, pick_no=6, team=expected_owners[6])
    _set_pick_owner(db_session, pick_no=11, team=expected_owners[11])
    _set_pick_owner(
        db_session,
        pick_no=16,
        team=expected_owners[16],
        original_team="PHX",
        notes="from Phoenix via Orlando",
    )
    db_session.commit()

    seed_db.seed_demo_data(db_session)
    db_session.commit()

    for pick_no, expected_team in expected_owners.items():
        order = db_session.query(DraftOrder).filter_by(
            year=2026,
            pick_no=pick_no,
        ).one()
        assert order.team_id == expected_team.id
        assert order.team.abbr == expected_team.abbr
        assert order.source == "official-test-order"

    pick_16 = db_session.query(DraftOrder).filter_by(year=2026, pick_no=16).one()
    assert pick_16.original_team == "PHX"
    assert pick_16.notes == "from Phoenix via Orlando"
    assert pick_16.team.abbr != "WAS"


def test_seed_demo_data_still_creates_projection_seed_rows(
    db_session: Session,
) -> None:
    seed_db.seed_demo_data(db_session)
    db_session.commit()

    prospect_projection_count = db_session.query(ProspectDraftProjection).count()
    team_projection_count = db_session.query(TeamPickProjection).count()

    assert prospect_projection_count >= len(seed_db.PROSPECTS)
    assert team_projection_count >= len(seed_db.TEAM_PICK_PROJECTION_SEEDS)
