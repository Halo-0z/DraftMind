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


# ---------------------------------------------------------------------------
# B0-J1: seed_db._upsert_prospect reclaims duplicate rows
# ---------------------------------------------------------------------------


def test_upsert_prospect_reclaims_suffixless_duplicate_row(
    db_session: Session,
) -> None:
    """If a suffixless duplicate (e.g. 'Darius Acuff' from the NBA.com
    scrape) already exists when the canonical seed ('Darius Acuff Jr.') is
    upserted, the seed must reclaim and rename that row instead of creating
    a second one."""
    from app.models import Prospect

    # Pre-existing duplicate created by some other importer.
    dup = Prospect(
        year=2026,
        name="Darius Acuff",
        position="SG",
        age=19.0,
        height="6-2",
        weight=186,
        school_or_league="Arkansas",
        ppg=14.5,
        rpg=3.4,
        apg=4.2,
        fg_pct=44.5,
        three_pct=35.5,
        ft_pct=77.5,
        stocks=1.2,
        archetype="Freshman guard prospect",
        upside_score=76.7,
        risk_score=30.6,
    )
    db_session.add(dup)
    db_session.commit()
    dup_id = dup.id

    # Upsert the canonical seed tuple (matches the seed_db PROSPECTS shape).
    canonical = seed_db._upsert_prospect(
        db_session,
        year=2026,
        prospect_data=(
            "Darius Acuff Jr.", "PG", 19.0, "6-2", 185, "Arkansas",
            17.9, 3.1, 5.9, 43.7, 34.9, 83.7, 1.0, "Pressure rim guard",
            79, 39,
        ),
    )
    db_session.commit()

    # The canonical row reuses the duplicate's id (reclaimed, not duplicated).
    assert canonical.id == dup_id
    assert canonical.name == "Darius Acuff Jr."
    # Exactly one prospect row for this normalized identity now.
    rows = (
        db_session.query(Prospect)
        .filter(Prospect.year == 2026)
        .filter(Prospect.name.ilike("Darius Acuff%"))
        .all()
    )
    assert len(rows) == 1


def test_upsert_prospect_raises_on_ambiguous_duplicate_group(
    db_session: Session,
) -> None:
    """If multiple distinct rows already share the normalized key, the seed
    must refuse to guess rather than silently reclaim one."""
    import pytest
    from app.models import Prospect

    db_session.add_all(
        [
            Prospect(
                year=2026, name="Darius Acuff Jr.", position="PG",
                age=19.0, height="6-2", weight=185, school_or_league="Arkansas",
                ppg=17.9, rpg=3.1, apg=5.9, fg_pct=43.7, three_pct=34.9,
                ft_pct=83.7, stocks=1.0, archetype="x", upside_score=79.0,
                risk_score=39.0,
            ),
            Prospect(
                year=2026, name="Darius Acuff", position="SG",
                age=19.0, height="6-2", weight=186, school_or_league="Arkansas",
                ppg=14.5, rpg=3.4, apg=4.2, fg_pct=44.5, three_pct=35.5,
                ft_pct=77.5, stocks=1.2, archetype="y", upside_score=76.7,
                risk_score=30.6,
            ),
        ]
    )
    db_session.commit()

    with pytest.raises(ValueError, match="matches"):
        seed_db._upsert_prospect(
            db_session,
            year=2026,
            prospect_data=(
                "Darius Acuff Jr.", "PG", 19.0, "6-2", 185, "Arkansas",
                17.9, 3.1, 5.9, 43.7, 34.9, 83.7, 1.0, "Pressure rim guard",
                79, 39,
            ),
        )
