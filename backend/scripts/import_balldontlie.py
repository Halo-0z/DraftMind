from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, SessionLocal, engine
from app.models import Team
from app.services.balldontlie_service import fetch_teams


def main() -> None:
    Base.metadata.create_all(bind=engine)
    try:
        teams = fetch_teams()
    except Exception as exc:  # noqa: BLE001
        print(f"balldontlie import failed: {exc}")
        return
    with SessionLocal() as db:
        updated = 0
        for item in teams:
            abbr = item.get("abbreviation")
            if not abbr:
                continue
            team = db.query(Team).filter(Team.abbr == abbr).one_or_none()
            if team is None:
                team = Team(
                    name=item.get("full_name") or abbr,
                    abbr=abbr,
                    nba_team_id=item.get("id"),
                    city=item.get("city"),
                    conference=item.get("conference", "Unknown"),
                    division=item.get("division", "Unknown"),
                )
                db.add(team)
                updated += 1
            else:
                team.name = item.get("full_name") or team.name
                team.nba_team_id = item.get("id") or team.nba_team_id
                team.city = item.get("city") or team.city
                team.conference = item.get("conference", team.conference)
                team.division = item.get("division", team.division)
        db.commit()
        print(f"Synced {updated} new teams from balldontlie (total processed: {len(teams)}).")


if __name__ == "__main__":
    main()
