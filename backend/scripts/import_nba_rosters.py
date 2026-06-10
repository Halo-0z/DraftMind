from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nba_api.stats.endpoints import CommonTeamRoster
from nba_api.stats.static import teams as nba_teams
from sqlalchemy import delete, select

from app.database import Base, SessionLocal, engine
from app.models import Roster, Team


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import NBA.com team rosters into DraftMind SQLite cache.",
    )
    parser.add_argument("--season", default="2025-26")
    parser.add_argument(
        "--abbr",
        action="append",
        help="Limit import to one or more team abbreviations, e.g. --abbr SAS --abbr HOU.",
    )
    parser.add_argument("--sleep", type=float, default=0.7)
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    selected_abbrs = {abbr.upper() for abbr in args.abbr} if args.abbr else None

    with SessionLocal() as db:
        imported_count = 0
        for nba_team in nba_teams.get_teams():
            abbr = nba_team["abbreviation"].upper()
            if selected_abbrs and abbr not in selected_abbrs:
                continue

            team = upsert_team(db, nba_team)
            rows = fetch_roster_rows(team.nba_team_id, args.season)

            db.execute(
                delete(Roster).where(
                    Roster.team_id == team.id,
                    Roster.season == args.season,
                )
            )
            for row in rows:
                db.add(build_roster_player(team.id, args.season, row))

            db.commit()
            imported_count += len(rows)
            print(f"Imported {len(rows):>2} players for {abbr} {args.season}")
            time.sleep(args.sleep)

        print(f"Done. Imported {imported_count} roster rows.")


def upsert_team(db, nba_team: dict[str, Any]) -> Team:
    team = db.scalar(select(Team).where(Team.abbr == nba_team["abbreviation"]))
    if team is None:
        team = Team(
            name=nba_team["full_name"],
            abbr=nba_team["abbreviation"],
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

    db.flush()
    return team


def fetch_roster_rows(team_id: int, season: str) -> list[dict[str, Any]]:
    response = CommonTeamRoster(team_id=team_id, season=season, timeout=20)
    frame = response.common_team_roster.get_data_frame()
    return frame.to_dict(orient="records")


def build_roster_player(team_id: int, season: str, row: dict[str, Any]) -> Roster:
    return Roster(
        team_id=team_id,
        season=season,
        nba_player_id=to_int(row.get("PLAYER_ID")),
        player_name=str(row.get("PLAYER") or row.get("PLAYER_NAME") or ""),
        position=to_optional_str(row.get("POSITION")),
        age=to_float(row.get("AGE")),
        height=to_optional_str(row.get("HEIGHT")),
        weight=to_int(row.get("WEIGHT")),
        jersey=to_optional_str(row.get("NUM")),
        experience=to_optional_str(row.get("EXP")),
        school=to_optional_str(row.get("SCHOOL")),
    )


def to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def to_int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
