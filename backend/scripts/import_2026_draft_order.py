from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nba_api.stats.static import teams as nba_teams
from sqlalchemy import delete, select, text

from app.database import Base, SessionLocal, engine
from app.models import DraftOrder, Team


SOURCE = "NBA.com 2026 Draft Order, updated 2026-06-04"

ORDER: list[tuple[int, str, str | None, str | None]] = [
    (1, "WAS", None, None),
    (2, "UTA", None, None),
    (3, "MEM", None, None),
    (4, "CHI", None, None),
    (5, "LAC", "IND", "from Indiana"),
    (6, "BKN", None, None),
    (7, "SAC", None, None),
    (8, "ATL", "NOP", "from New Orleans"),
    (9, "DAL", None, None),
    (10, "MIL", None, None),
    (11, "GSW", None, None),
    (12, "OKC", "LAC", "from the LA Clippers"),
    (13, "MIA", None, None),
    (14, "CHA", None, None),
    (15, "CHI", "POR", "from Portland"),
    (16, "MEM", "PHX", "from Phoenix via Orlando"),
    (17, "OKC", "PHI", "from Philadelphia"),
    (18, "CHA", "ORL", "from Orlando via Phoenix"),
    (19, "TOR", None, None),
    (20, "SAS", "ATL", "from Atlanta"),
    (21, "DET", "MIN", "from Minnesota"),
    (22, "PHI", "HOU", "from Houston via Oklahoma City"),
    (23, "ATL", "CLE", "from Cleveland"),
    (24, "NYK", None, None),
    (25, "LAL", None, None),
    (26, "DEN", None, None),
    (27, "BOS", None, None),
    (28, "MIN", "DET", "from Detroit"),
    (29, "CLE", "SAS", "from San Antonio via Atlanta"),
    (30, "DAL", "OKC", "from Oklahoma City via Washington and Philadelphia"),
    (31, "NYK", "WAS", "from Washington via Oklahoma City and Houston"),
    (32, "MEM", "IND", "from Indiana via Milwaukee"),
    (33, "BKN", None, None),
    (34, "SAC", None, None),
    (35, "SAS", "UTA", "from Utah via Minnesota"),
    (36, "LAC", "MEM", "from Memphis via Atlanta and Utah"),
    (37, "OKC", "DAL", "from Dallas"),
    (38, "CHI", "NOP", "from New Orleans via Boston, Detroit, and Portland"),
    (39, "HOU", "CHI", "from Chicago via Washington"),
    (40, "BOS", "MIL", "from Milwaukee via Orlando"),
    (41, "MIA", "GSW", "from Golden State via Charlotte, New York, Oklahoma City, and Atlanta"),
    (42, "SAS", "POR", "from Portland via New Orleans"),
    (43, "BKN", "LAC", "from the LA Clippers via Houston"),
    (44, "SAS", "MIA", "from Miami via Indiana"),
    (45, "SAC", "CHA", "from Charlotte via San Antonio, Atlanta, and New York"),
    (46, "ORL", None, None),
    (47, "PHX", "PHI", "from Philadelphia via Houston and Oklahoma City"),
    (48, "DAL", "PHX", "from Phoenix via Washington"),
    (49, "DEN", "ATL", "from Atlanta via Brooklyn and Golden State"),
    (50, "TOR", None, None),
    (51, "WAS", "MIN", "from Minnesota via Detroit and New York"),
    (52, "LAC", "CLE", "from Cleveland"),
    (53, "HOU", None, None),
    (54, "GSW", "LAL", "from the Los Angeles Lakers via Toronto, Miami, and Cleveland"),
    (55, "NYK", None, None),
    (56, "CHI", "DEN", "from Denver via Minnesota, Phoenix, Charlotte, and Phoenix"),
    (57, "ATL", "BOS", "from Boston"),
    (58, "NOP", "DET", "from Detroit via New York, Brooklyn, Phoenix, Orlando, and LA Clippers"),
    (59, "MIN", "SAS", "from San Antonio via Indiana"),
    (60, "WAS", "OKC", "from Oklahoma City via San Antonio and Miami"),
]


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_draft_order_columns()

    with SessionLocal() as db:
        teams_by_abbr = upsert_nba_teams(db)
        db.execute(delete(DraftOrder).where(DraftOrder.year == 2026))

        for pick_no, owner_abbr, original_team, notes in ORDER:
            db.add(
                DraftOrder(
                    year=2026,
                    pick_no=pick_no,
                    team_id=teams_by_abbr[owner_abbr].id,
                    original_team=original_team,
                    source=SOURCE,
                    notes=notes,
                )
            )

        db.commit()
        print(f"Imported {len(ORDER)} official 2026 draft-order rows from NBA.com.")


def ensure_draft_order_columns() -> None:
    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.execute(text("PRAGMA table_info(draft_order)")).all()
        }
        for column_name in ("original_team", "source", "notes"):
            if column_name not in columns:
                connection.execute(
                    text(f"ALTER TABLE draft_order ADD COLUMN {column_name} VARCHAR")
                )


def upsert_nba_teams(db) -> dict[str, Team]:
    teams_by_abbr: dict[str, Team] = {}
    for nba_team in nba_teams.get_teams():
        abbr = nba_team["abbreviation"]
        team = db.scalar(select(Team).where(Team.abbr == abbr))
        if team is None:
            team = Team(
                name=nba_team["full_name"],
                abbr=abbr,
                nba_team_id=nba_team["id"],
                city=nba_team.get("city"),
                conference="Unknown",
                division="Unknown",
            )
            db.add(team)
        else:
            team.name = nba_team["full_name"]
            team.nba_team_id = nba_team["id"]
            team.city = nba_team.get("city")
        teams_by_abbr[abbr] = team

    db.flush()
    return teams_by_abbr


if __name__ == "__main__":
    main()
