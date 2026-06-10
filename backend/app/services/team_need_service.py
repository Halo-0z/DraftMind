from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.roster import Roster
from app.models.team import TeamNeed


def get_or_infer_team_need(db: Session, team_id: int, year: int) -> TeamNeed:
    team_need = db.scalar(
        select(TeamNeed).where(
            TeamNeed.team_id == team_id,
            TeamNeed.year == year,
        )
    )
    if team_need is not None:
        return team_need

    roster = list(
        db.scalars(
            select(Roster).where(
                Roster.team_id == team_id,
                Roster.season == f"{year - 1}-{str(year)[-2:]}",
            )
        )
    )
    return infer_team_need(team_id=team_id, year=year, roster=roster)


def infer_team_need(team_id: int, year: int, roster: list[Roster]) -> TeamNeed:
    counts = {"G": 0, "F": 0, "C": 0}
    for player in roster:
        position = (player.position or "").upper()
        if "G" in position:
            counts["G"] += 1
        if "F" in position:
            counts["F"] += 1
        if "C" in position:
            counts["C"] += 1

    if not roster:
        return TeamNeed(
            team_id=team_id,
            year=year,
            need_pg=5,
            need_sg=5,
            need_sf=5,
            need_pf=5,
            need_c=5,
            need_shooting=6,
            need_defense=6,
            need_creation=6,
        )

    guard_need = _need_from_count(counts["G"], target=6)
    forward_need = _need_from_count(counts["F"], target=6)
    center_need = _need_from_count(counts["C"], target=3)

    return TeamNeed(
        team_id=team_id,
        year=year,
        need_pg=guard_need,
        need_sg=max(4, guard_need - 1),
        need_sf=forward_need,
        need_pf=max(4, forward_need - 1),
        need_c=center_need,
        need_shooting=7,
        need_defense=6,
        need_creation=6,
    )


def _need_from_count(count: int, target: int) -> int:
    if count <= 0:
        return 9
    if count >= target + 2:
        return 3
    return max(3, min(9, 5 + (target - count)))
