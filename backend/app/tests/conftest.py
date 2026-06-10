from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import DraftOrder, Prospect, Roster, Team, TeamNeed


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        spurs = Team(
            name="San Antonio Spurs",
            abbr="SAS",
            nba_team_id=1610612759,
            city="San Antonio",
            conference="West",
            division="Southwest",
        )
        rockets = Team(
            name="Houston Rockets",
            abbr="HOU",
            nba_team_id=1610612745,
            city="Houston",
            conference="West",
            division="Southwest",
        )
        session.add_all([spurs, rockets])
        session.flush()
        session.add(
            TeamNeed(
                team_id=spurs.id,
                year=2026,
                need_pg=9,
                need_sg=6,
                need_sf=5,
                need_pf=3,
                need_c=2,
                need_shooting=8,
                need_defense=6,
                need_creation=9,
            )
        )
        session.add_all(
            [
                Roster(
                    team_id=spurs.id,
                    season="2025-26",
                    nba_player_id=1641705,
                    player_name="Victor Wembanyama",
                    position="C-F",
                    age=22.0,
                    height="7-4",
                    weight=235,
                    jersey="1",
                    experience="2",
                    school="France",
                ),
                Prospect(
                    year=2026,
                    name="Mikel Brown Jr.",
                    position="PG",
                    age=19.0,
                    height="6-3",
                    weight=180,
                    school_or_league="Louisville",
                    ppg=18.6,
                    rpg=3.2,
                    apg=6.8,
                    fg_pct=45.0,
                    three_pct=38.2,
                    ft_pct=84.5,
                    stocks=1.2,
                    archetype="Pick-and-roll lead guard",
                    upside_score=86,
                    risk_score=35,
                ),
                Prospect(
                    year=2026,
                    name="Braylon Mullins",
                    position="SG",
                    age=18.9,
                    height="6-5",
                    weight=190,
                    school_or_league="UConn",
                    ppg=14.8,
                    rpg=4.0,
                    apg=2.7,
                    fg_pct=45.9,
                    three_pct=40.1,
                    ft_pct=81.0,
                    stocks=1.3,
                    archetype="Movement shooter",
                    upside_score=82,
                    risk_score=24,
                ),
            ]
        )
        # The simulate tests (test_simulate_api.py,
        # test_simulation_service.py) expect 4 DraftOrder rows for
        # 2026 — pick_no 2, 5, 10, 20 — to already be in the DB.
        # They add pick_no=1 themselves and then call
        # /api/simulate with limit=2/4.  See the comments in those
        # tests ("conftest already seeds pick_no 2,5,10,20 for
        # year 2026").
        session.add_all(
            [
                DraftOrder(
                    year=2026,
                    pick_no=2,
                    team_id=spurs.id,
                    original_team=None,
                    notes=None,
                ),
                DraftOrder(
                    year=2026,
                    pick_no=5,
                    team_id=rockets.id,
                    original_team=None,
                    notes=None,
                ),
                DraftOrder(
                    year=2026,
                    pick_no=10,
                    team_id=spurs.id,
                    original_team="ATL",
                    notes="from Atlanta",
                ),
                DraftOrder(
                    year=2026,
                    pick_no=20,
                    team_id=rockets.id,
                    original_team="POR",
                    notes="from Portland",
                ),
            ]
        )
        session.commit()
        yield session


@pytest.fixture()
def db_with_team_picks(db_session: Session) -> Generator[Session, None, None]:
    """Provide a deterministic 2026 draft-order slate for the picks tests.

    The base `db_session` fixture already seeds picks 2, 5, 10, 20 for
    the simulate tests.  Wipe those first and re-insert with
    high-numbered picks so the picks-endpoint tests can assert an
    exact, isolated list without colliding with the simulate tests.
    """
    from sqlalchemy import delete  # local import keeps top of file tidy

    spurs = db_session.query(Team).filter(Team.abbr == "SAS").first()
    rockets = db_session.query(Team).filter(Team.abbr == "HOU").first()
    assert spurs is not None and rockets is not None

    db_session.execute(delete(DraftOrder).where(DraftOrder.year == 2026))

    db_session.add_all(
        [
            DraftOrder(
                year=2026,
                pick_no=61,
                team_id=spurs.id,
                original_team=None,
                notes=None,
            ),
            DraftOrder(
                year=2026,
                pick_no=70,
                team_id=spurs.id,
                original_team="ATL",
                notes="from Atlanta",
            ),
            DraftOrder(
                year=2026,
                pick_no=65,
                team_id=rockets.id,
                original_team=None,
                notes=None,
            ),
            DraftOrder(
                year=2026,
                pick_no=80,
                team_id=rockets.id,
                original_team="POR",
                notes="from Portland",
            ),
        ]
    )
    db_session.commit()
    yield db_session


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
