from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, SessionLocal, engine
from app.models import (
    DraftOrder,
    Prospect,
    ProspectScoutingProfile,
    Roster,
    ScoutingReport,
    Team,
    TeamNeed,
    TeamNeedProfile,
)


TEAMS = [
    {
        "name": "San Antonio Spurs",
        "abbr": "SAS",
        "nba_team_id": 1610612759,
        "city": "San Antonio",
        "conference": "West",
        "division": "Southwest",
    },
    {
        "name": "Houston Rockets",
        "abbr": "HOU",
        "nba_team_id": 1610612745,
        "city": "Houston",
        "conference": "West",
        "division": "Southwest",
    },
    {
        "name": "Washington Wizards",
        "abbr": "WAS",
        "nba_team_id": 1610612764,
        "city": "Washington",
        "conference": "East",
        "division": "Southeast",
    },
    {
        "name": "Detroit Pistons",
        "abbr": "DET",
        "nba_team_id": 1610612765,
        "city": "Detroit",
        "conference": "East",
        "division": "Central",
    },
    {
        "name": "Portland Trail Blazers",
        "abbr": "POR",
        "nba_team_id": 1610612757,
        "city": "Portland",
        "conference": "West",
        "division": "Northwest",
    },
]

TEAM_NEEDS = {
    "SAS": {
        "need_pg": 9,
        "need_sg": 6,
        "need_sf": 5,
        "need_pf": 3,
        "need_c": 2,
        "need_shooting": 8,
        "need_defense": 6,
        "need_creation": 9,
    },
    "HOU": {
        "need_pg": 4,
        "need_sg": 7,
        "need_sf": 8,
        "need_pf": 5,
        "need_c": 3,
        "need_shooting": 9,
        "need_defense": 7,
        "need_creation": 6,
    },
    "WAS": {
        "need_pg": 8,
        "need_sg": 7,
        "need_sf": 8,
        "need_pf": 7,
        "need_c": 6,
        "need_shooting": 7,
        "need_defense": 8,
        "need_creation": 8,
    },
    "DET": {
        "need_pg": 5,
        "need_sg": 8,
        "need_sf": 8,
        "need_pf": 4,
        "need_c": 3,
        "need_shooting": 10,
        "need_defense": 6,
        "need_creation": 6,
    },
    "POR": {
        "need_pg": 4,
        "need_sg": 6,
        "need_sf": 8,
        "need_pf": 8,
        "need_c": 7,
        "need_shooting": 7,
        "need_defense": 9,
        "need_creation": 5,
    },
}

PROSPECTS = [
    ("AJ Dybantsa", "SF", 19.3, "6-9", 210, "BYU", 21.6, 7.8, 3.4, 49.2, 35.1, 78.0, 2.2, "Two-way wing creator", 96, 28),
    ("Cameron Boozer", "PF", 18.9, "6-9", 235, "Duke", 19.4, 10.2, 3.1, 55.3, 34.2, 73.5, 1.8, "Skilled frontcourt hub", 94, 22),
    ("Darryn Peterson", "SG", 19.1, "6-5", 195, "Kansas", 20.8, 4.6, 4.9, 47.6, 37.4, 82.1, 1.5, "Scoring guard creator", 92, 31),
    ("Nate Ament", "PF", 18.8, "6-10", 200, "Tennessee", 16.7, 8.5, 2.4, 48.8, 36.8, 80.2, 2.0, "Stretch forward", 90, 34),
    ("Koa Peat", "PF", 19.0, "6-8", 235, "Arizona", 17.1, 8.1, 2.8, 52.0, 31.5, 69.4, 1.7, "Physical combo forward", 88, 29),
    ("Caleb Wilson", "SF", 18.7, "6-9", 205, "North Carolina", 15.9, 7.4, 3.6, 50.1, 33.7, 74.0, 2.4, "Defensive playmaking wing", 87, 33),
    ("Mikel Brown Jr.", "PG", 19.0, "6-3", 180, "Louisville", 18.6, 3.2, 6.8, 45.0, 38.2, 84.5, 1.2, "Pick-and-roll lead guard", 86, 35),
    ("Tounde Yessoufou", "SF", 19.2, "6-7", 215, "Baylor", 16.2, 6.3, 2.1, 46.7, 34.4, 76.2, 2.1, "Power wing defender", 84, 32),
    ("Braylon Mullins", "SG", 18.9, "6-5", 190, "UConn", 14.8, 4.0, 2.7, 45.9, 40.1, 81.0, 1.3, "Movement shooter", 82, 24),
    ("Jayden Quaintance", "C", 19.4, "6-10", 245, "Kentucky", 13.7, 9.8, 1.9, 57.5, 27.0, 63.8, 3.0, "Rim protector finisher", 81, 37),
    ("Isiah Harwell", "SG", 19.1, "6-6", 205, "Houston", 15.4, 4.8, 2.5, 44.8, 36.6, 79.1, 1.4, "Two-way shooting guard", 80, 27),
    ("Darius Acuff Jr.", "PG", 19.0, "6-2", 185, "Arkansas", 17.9, 3.1, 5.9, 43.7, 34.9, 83.7, 1.0, "Pressure rim guard", 79, 39),
    ("Chris Cenac Jr.", "C", 18.8, "6-10", 230, "Houston", 12.8, 8.7, 1.6, 55.8, 30.8, 70.0, 2.6, "Mobile defensive big", 78, 30),
    ("Nikolas Khamenia", "SF", 19.3, "6-8", 215, "Duke", 12.1, 5.9, 3.7, 47.9, 37.6, 78.4, 1.6, "Connector wing", 77, 21),
    ("Jasper Johnson", "SG", 19.0, "6-4", 180, "Kentucky", 16.9, 3.5, 3.8, 43.9, 38.7, 85.0, 1.1, "Shot-making combo guard", 76, 36),
    ("Malachi Moreno", "C", 19.1, "7-0", 240, "Kentucky", 11.5, 8.9, 1.1, 60.4, 18.0, 66.1, 2.7, "Drop coverage center", 74, 25),
    ("Niko Bundalo", "PF", 19.2, "6-10", 215, "Washington", 13.2, 7.2, 2.2, 49.0, 35.5, 77.3, 1.9, "Pick-and-pop forward", 73, 28),
    ("Cayden Boozer", "PG", 18.9, "6-4", 190, "Duke", 12.4, 3.8, 6.1, 46.2, 36.0, 80.8, 1.3, "Steady table-setting guard", 72, 18),
    ("Meleek Thomas", "SG", 19.1, "6-4", 190, "Arkansas", 14.6, 4.3, 3.2, 42.8, 35.8, 79.7, 1.5, "Aggressive scoring guard", 71, 38),
    ("Sidi Gueye", "SF", 19.5, "6-8", 205, "G League Ignite", 11.9, 6.7, 2.0, 45.5, 32.2, 72.6, 2.3, "Long defensive wing", 70, 41),
]

MOCK_ROSTERS = {
    "SAS": [
        ("Victor Wembanyama", "C-F", 22.0, "7-4", 235, "1", "2", "France"),
        ("Stephon Castle", "G", 21.0, "6-6", 210, "5", "2", "Connecticut"),
        ("Devin Vassell", "G-F", 25.0, "6-5", 200, "24", "5", "Florida State"),
    ],
    "HOU": [
        ("Amen Thompson", "G-F", 23.0, "6-7", 209, "1", "3", "Overtime Elite"),
        ("Jalen Green", "G", 24.0, "6-4", 186, "4", "5", "NBA G League Ignite"),
        ("Alperen Sengun", "C", 23.0, "6-11", 243, "28", "5", "Turkey"),
    ],
    "WAS": [
        ("Alex Sarr", "F-C", 21.0, "7-0", 224, "20", "2", "France"),
        ("Bilal Coulibaly", "G-F", 21.0, "6-8", 195, "0", "3", "France"),
        ("Bub Carrington", "G", 20.0, "6-4", 195, "8", "2", "Pittsburgh"),
    ],
    "DET": [
        ("Cade Cunningham", "G", 24.0, "6-6", 220, "2", "5", "Oklahoma State"),
        ("Ausar Thompson", "G-F", 23.0, "6-7", 215, "9", "3", "Overtime Elite"),
        ("Jalen Duren", "C", 22.0, "6-10", 250, "0", "4", "Memphis"),
    ],
    "POR": [
        ("Scoot Henderson", "G", 22.0, "6-3", 202, "00", "3", "NBA G League Ignite"),
        ("Shaedon Sharpe", "G", 23.0, "6-5", 200, "17", "4", "Kentucky"),
        ("Donovan Clingan", "C", 22.0, "7-2", 280, "23", "2", "Connecticut"),
    ],
}


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed() -> None:
    reset_database()
    with SessionLocal() as db:
        teams_by_abbr: dict[str, Team] = {}
        for team_data in TEAMS:
            team = Team(**team_data)
            db.add(team)
            teams_by_abbr[team.abbr] = team
        db.flush()

        for abbr, needs in TEAM_NEEDS.items():
            db.add(TeamNeed(team_id=teams_by_abbr[abbr].id, year=2026, **needs))
            db.add(
                TeamNeedProfile(
                    team_id=teams_by_abbr[abbr].id,
                    year=2026,
                    need_guard_depth=max(needs["need_pg"], needs["need_sg"]),
                    need_wing_depth=needs["need_sf"],
                    need_big_depth=max(needs["need_pf"], needs["need_c"]),
                    need_center=needs["need_c"],
                    need_spacing=needs["need_shooting"],
                    need_shooting_volume=needs["need_shooting"],
                    need_secondary_creation=needs["need_creation"],
                    need_playmaking=needs["need_creation"],
                    need_rim_protection=needs["need_defense"],
                    need_defensive_rebounding=max(needs["need_c"], needs["need_defense"]),
                    need_point_of_attack_defense=needs["need_defense"],
                    need_team_defense=needs["need_defense"],
                    team_timeline="rebuild" if abbr in {"WAS", "POR"} else "retool",
                    source="seed",
                    horizon="now",
                    need_confidence=0.55,
                    manual_override_reason="Seed profile derived from demo TeamNeed values.",
                    scheme_tags="demo-seed",
                )
            )

        for abbr, players in MOCK_ROSTERS.items():
            for index, player in enumerate(players, start=1):
                db.add(
                    Roster(
                        team_id=teams_by_abbr[abbr].id,
                        season="2025-26",
                        nba_player_id=teams_by_abbr[abbr].nba_team_id + index,
                        player_name=player[0],
                        position=player[1],
                        age=player[2],
                        height=player[3],
                        weight=player[4],
                        jersey=player[5],
                        experience=player[6],
                        school=player[7],
                    )
                )

        team_cycle = ["WAS", "DET", "POR", "SAS", "HOU"]
        for pick_no in range(1, 21):
            abbr = team_cycle[(pick_no - 1) % len(team_cycle)]
            db.add(
                DraftOrder(
                    year=2026,
                    pick_no=pick_no,
                    team_id=teams_by_abbr[abbr].id,
                )
            )

        for index, prospect_data in enumerate(PROSPECTS, start=1):
            prospect = Prospect(
                year=2026,
                name=prospect_data[0],
                position=prospect_data[1],
                age=prospect_data[2],
                height=prospect_data[3],
                weight=prospect_data[4],
                school_or_league=prospect_data[5],
                ppg=prospect_data[6],
                rpg=prospect_data[7],
                apg=prospect_data[8],
                fg_pct=prospect_data[9],
                three_pct=prospect_data[10],
                ft_pct=prospect_data[11],
                stocks=prospect_data[12],
                archetype=prospect_data[13],
                upside_score=prospect_data[14],
                risk_score=prospect_data[15],
            )
            db.add(prospect)
            db.flush()
            db.add(
                ScoutingReport(
                    prospect_id=prospect.id,
                    source="DraftMind Mock Board",
                    report_text=(
                        f"{prospect.name} profiles as a {prospect.archetype.lower()} "
                        f"with a projected board range near pick {index}. Key swing "
                        f"factors are shooting translation, decision speed, defensive "
                        f"role clarity, and how quickly NBA spacing simplifies reads."
                    ),
                )
            )
            db.add(_build_seed_scouting_profile(prospect))

        db.commit()


def _build_seed_scouting_profile(prospect: Prospect) -> ProspectScoutingProfile:
    archetype = prospect.archetype.lower()
    is_big = prospect.position in {"C", "PF/C"} or "frontcourt" in archetype
    is_guard = prospect.position in {"PG", "SG", "G"} or "guard" in archetype
    is_shooter = prospect.three_pct >= 37 or "shooter" in archetype or "stretch" in archetype
    is_defender = prospect.stocks >= 2 or "defender" in archetype or "rim protector" in archetype

    return ProspectScoutingProfile(
        prospect_id=prospect.id,
        year=prospect.year,
        shooting_volume=8 if is_shooter else (6 if prospect.three_pct >= 34 else 4),
        shooting_versatility=8 if "movement" in archetype else (7 if is_shooter else 5),
        spacing_value=8 if is_shooter else (6 if prospect.three_pct >= 34 else 4),
        rim_pressure=7 if "pressure" in archetype or is_big else 5,
        self_creation=8 if "creator" in archetype or "scoring guard" in archetype else 5,
        secondary_creation=7 if prospect.apg >= 3.5 else 5,
        passing_feel=8 if prospect.apg >= 5 else (6 if prospect.apg >= 3 else 4),
        finishing=7 if prospect.fg_pct >= 52 else 5,
        rim_protection=8 if "rim protector" in archetype else (7 if is_big and prospect.stocks >= 2 else 4),
        defensive_rebounding=8 if prospect.rpg >= 8 else (6 if prospect.rpg >= 6 else 4),
        offensive_rebounding=7 if prospect.rpg >= 8 and is_big else 5,
        point_of_attack_defense=7 if is_defender and is_guard else 5,
        switchability=7 if "wing" in archetype or "mobile" in archetype else 5,
        team_defense=8 if is_defender else 5,
        foul_discipline=5,
        physicality=7 if prospect.weight >= 220 else 5,
        height=prospect.height,
        age=prospect.age,
        nba_readiness=7 if prospect.risk_score <= 25 else 5,
        upside=round(max(1, min(10, prospect.upside_score / 10))),
        medical_risk=round(max(1, min(10, prospect.risk_score / 10))),
        role_projection=prospect.archetype,
        scheme_fit_tags=_seed_scheme_tags(prospect, archetype),
        source="seed",
        profile_confidence=0.55,
        manual_override_reason="Seeded from demo box-score and archetype fields.",
    )


def _seed_scheme_tags(prospect: Prospect, archetype: str) -> str:
    tags: list[str] = []
    if prospect.position in {"C", "PF/C"}:
        tags.append("frontcourt")
    if "wing" in archetype:
        tags.append("wing")
    if prospect.three_pct >= 37 or "shooter" in archetype:
        tags.append("spacing")
    if prospect.stocks >= 2 or "defender" in archetype:
        tags.append("defense")
    if "creator" in archetype or prospect.apg >= 4:
        tags.append("creation")
    return ",".join(tags or ["demo-seed"])


if __name__ == "__main__":
    seed()
    print("Seeded DraftMind database with 5 teams and 20 prospects.")
