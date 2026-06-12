from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from sqlalchemy.orm import Session

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

TEAM_NEED_PROFILE_OVERRIDES: dict[str, dict[str, Any]] = {
    "SAS": {
        "need_guard_depth": 9,
        "need_wing_depth": 6,
        "need_big_depth": 3,
        "need_center": 2,
        "need_size": 5,
        "need_nba_ready": 7,
        "need_upside": 6,
        "need_spacing": 8,
        "need_shooting_volume": 8,
        "need_movement_shooting": 7,
        "need_self_creation": 7,
        "need_secondary_creation": 9,
        "need_playmaking": 9,
        "need_rim_pressure": 6,
        "need_finishing": 5,
        "need_rim_protection": 4,
        "need_defensive_rebounding": 5,
        "need_point_of_attack_defense": 7,
        "need_switchability": 6,
        "need_team_defense": 6,
        "team_timeline": "retool",
        "core_age_curve": 23.0,
        "development_bandwidth": 7,
        "scheme_tags": "wembanyama-spacing,guard-creation,secondary-playmaking",
        "need_confidence": 0.64,
        "manual_override_reason": (
            "Demo profile: young retooling core needs guard creation, spacing, "
            "and NBA-ready perimeter decision making around Wembanyama."
        ),
    },
    "HOU": {
        "need_guard_depth": 5,
        "need_wing_depth": 8,
        "need_big_depth": 4,
        "need_size": 7,
        "need_nba_ready": 7,
        "need_upside": 6,
        "need_spacing": 9,
        "need_shooting_volume": 9,
        "need_movement_shooting": 8,
        "need_self_creation": 6,
        "need_secondary_creation": 7,
        "need_playmaking": 6,
        "need_rim_pressure": 6,
        "need_rim_protection": 6,
        "need_defensive_rebounding": 6,
        "need_point_of_attack_defense": 7,
        "need_switchability": 8,
        "need_team_defense": 7,
        "team_timeline": "retool",
        "core_age_curve": 23.5,
        "development_bandwidth": 6,
        "scheme_tags": "wing-size,shooting-volume,switch-defense",
        "need_confidence": 0.63,
        "manual_override_reason": (
            "Demo profile: athletic core benefits from more wing size, "
            "shooting volume, and switchable defensive depth."
        ),
    },
    "WAS": {
        "need_guard_depth": 8,
        "need_wing_depth": 8,
        "need_big_depth": 7,
        "need_center": 6,
        "need_size": 8,
        "need_youth": 8,
        "need_nba_ready": 5,
        "need_upside": 9,
        "need_spacing": 7,
        "need_shooting_volume": 7,
        "need_movement_shooting": 6,
        "need_self_creation": 8,
        "need_secondary_creation": 8,
        "need_playmaking": 8,
        "need_rim_pressure": 7,
        "need_finishing": 6,
        "need_rim_protection": 8,
        "need_defensive_rebounding": 8,
        "need_offensive_rebounding": 6,
        "need_point_of_attack_defense": 8,
        "need_switchability": 8,
        "need_team_defense": 8,
        "need_physicality": 7,
        "team_timeline": "rebuild",
        "core_age_curve": 21.0,
        "development_bandwidth": 9,
        "scheme_tags": "rebuild-upside,two-way-size,creation-bet",
        "need_confidence": 0.62,
        "manual_override_reason": (
            "Demo profile: rebuilding roster should prioritize upside, "
            "two-way size, creation, and defensive infrastructure."
        ),
    },
    "DET": {
        "need_guard_depth": 5,
        "need_wing_depth": 8,
        "need_big_depth": 4,
        "need_size": 7,
        "need_youth": 5,
        "need_nba_ready": 8,
        "need_upside": 6,
        "need_spacing": 10,
        "need_shooting_volume": 10,
        "need_movement_shooting": 9,
        "need_self_creation": 5,
        "need_secondary_creation": 6,
        "need_playmaking": 6,
        "need_rim_pressure": 5,
        "need_finishing": 5,
        "need_rim_protection": 5,
        "need_defensive_rebounding": 5,
        "need_point_of_attack_defense": 6,
        "need_switchability": 7,
        "need_team_defense": 6,
        "team_timeline": "retool",
        "core_age_curve": 23.0,
        "development_bandwidth": 6,
        "scheme_tags": "shooting-volume,cade-spacing,wing-depth",
        "need_confidence": 0.66,
        "manual_override_reason": (
            "Demo profile: young retooling team needs shooting volume, "
            "spacing around Cade, and reliable wing depth."
        ),
    },
    "POR": {
        "need_guard_depth": 4,
        "need_wing_depth": 8,
        "need_big_depth": 8,
        "need_center": 7,
        "need_size": 8,
        "need_youth": 7,
        "need_nba_ready": 5,
        "need_upside": 8,
        "need_spacing": 7,
        "need_shooting_volume": 7,
        "need_movement_shooting": 6,
        "need_self_creation": 5,
        "need_secondary_creation": 5,
        "need_playmaking": 5,
        "need_rim_pressure": 6,
        "need_finishing": 7,
        "need_rim_protection": 9,
        "need_defensive_rebounding": 9,
        "need_offensive_rebounding": 7,
        "need_point_of_attack_defense": 7,
        "need_switchability": 8,
        "need_team_defense": 9,
        "need_physicality": 8,
        "team_timeline": "rebuild",
        "core_age_curve": 22.5,
        "development_bandwidth": 8,
        "scheme_tags": "frontcourt-defense,wing-size,rebounding",
        "need_confidence": 0.61,
        "manual_override_reason": (
            "Demo profile: rebuilding roster needs bigger two-way forwards, "
            "frontcourt defense, and rebounding support."
        ),
    },
}

LAL_TEAM_NEED_PROFILE: dict[str, Any] = {
    "need_guard_depth": 5,
    "need_wing_depth": 6,
    "need_big_depth": 9,
    "need_center": 9,
    "need_size": 8,
    "need_youth": 5,
    "need_nba_ready": 9,
    "need_upside": 6,
    "need_spacing": 7,
    "need_shooting_volume": 7,
    "need_movement_shooting": 6,
    "need_self_creation": 5,
    "need_secondary_creation": 6,
    "need_playmaking": 5,
    "need_rim_pressure": 6,
    "need_finishing": 7,
    "need_rim_protection": 9,
    "need_defensive_rebounding": 9,
    "need_offensive_rebounding": 6,
    "need_point_of_attack_defense": 6,
    "need_switchability": 6,
    "need_team_defense": 8,
    "need_physicality": 8,
    "team_timeline": "contend",
    "core_age_curve": 29.0,
    "contract_pressure": 7,
    "development_bandwidth": 4,
    "scheme_tags": "contender-frontcourt,rim-protection,rebounding,spacing",
    "source": "seed",
    "horizon": "next_season",
    "need_confidence": 0.65,
    "manual_override_reason": (
        "Demo profile: contender needing frontcourt defense, rebounding, "
        "spacing, and NBA-ready contributors."
    ),
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
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_demo_data(db)
        db.commit()


def seed_demo_data(db: Session) -> None:
    teams_by_abbr: dict[str, Team] = {}
    for team_data in TEAMS:
        team = _upsert_team(db, team_data)
        teams_by_abbr[team.abbr] = team
    db.flush()

    for abbr, needs in TEAM_NEEDS.items():
        team = teams_by_abbr[abbr]
        _upsert_team_need(db, team.id, 2026, needs)
        _upsert_team_need_profile(
            db,
            team.id,
            2026,
            _build_seed_team_need_profile(abbr, needs),
        )

    lal_team = db.query(Team).filter(Team.abbr == "LAL").first()
    if lal_team is not None:
        _upsert_team_need_profile(db, lal_team.id, 2026, LAL_TEAM_NEED_PROFILE)

    for abbr, players in MOCK_ROSTERS.items():
        team = teams_by_abbr[abbr]
        for index, player in enumerate(players, start=1):
            _upsert_roster_player(
                db,
                team_id=team.id,
                season="2025-26",
                nba_player_id=(team.nba_team_id or 0) + index,
                player=player,
            )

    team_cycle = ["WAS", "DET", "POR", "SAS", "HOU"]
    for pick_no in range(1, 21):
        abbr = team_cycle[(pick_no - 1) % len(team_cycle)]
        _upsert_draft_order(db, 2026, pick_no, teams_by_abbr[abbr].id)

    for index, prospect_data in enumerate(PROSPECTS, start=1):
        prospect = _upsert_prospect(db, 2026, prospect_data)
        db.flush()
        _upsert_scouting_report(db, prospect, index)
        _upsert_prospect_scouting_profile(db, prospect)

    db.flush()


def _assign_attrs(obj: object, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(obj, key, value)


def _upsert_team(db: Session, team_data: dict[str, Any]) -> Team:
    team = db.query(Team).filter(Team.abbr == team_data["abbr"]).first()
    if team is None:
        team = Team(**team_data)
        db.add(team)
    else:
        _assign_attrs(team, team_data)
    return team


def _upsert_team_need(
    db: Session,
    team_id: int,
    year: int,
    needs: dict[str, int],
) -> TeamNeed:
    team_need = db.query(TeamNeed).filter_by(team_id=team_id, year=year).first()
    values = {"team_id": team_id, "year": year, **needs}
    if team_need is None:
        team_need = TeamNeed(**values)
        db.add(team_need)
    else:
        _assign_attrs(team_need, values)
    return team_need


def _upsert_team_need_profile(
    db: Session,
    team_id: int,
    year: int,
    values: dict[str, Any],
) -> TeamNeedProfile:
    horizon = values.get("horizon", "next_season")
    profile = (
        db.query(TeamNeedProfile)
        .filter_by(team_id=team_id, year=year, horizon=horizon)
        .first()
    )
    payload = {"team_id": team_id, "year": year, **values}
    if profile is None:
        profile = TeamNeedProfile(**payload)
        db.add(profile)
    elif profile.source != "seed":
        return profile
    else:
        _assign_attrs(profile, payload)
    return profile


def _upsert_roster_player(
    db: Session,
    *,
    team_id: int,
    season: str,
    nba_player_id: int,
    player: tuple[str, str, float, str, int, str, str, str],
) -> Roster:
    roster = (
        db.query(Roster)
        .filter_by(team_id=team_id, season=season, player_name=player[0])
        .first()
    )
    values = {
        "team_id": team_id,
        "season": season,
        "nba_player_id": nba_player_id,
        "player_name": player[0],
        "position": player[1],
        "age": player[2],
        "height": player[3],
        "weight": player[4],
        "jersey": player[5],
        "experience": player[6],
        "school": player[7],
    }
    if roster is None:
        roster = Roster(**values)
        db.add(roster)
    else:
        _assign_attrs(roster, values)
    return roster


def _upsert_draft_order(
    db: Session,
    year: int,
    pick_no: int,
    team_id: int,
) -> DraftOrder:
    order = db.query(DraftOrder).filter_by(year=year, pick_no=pick_no).first()
    values = {"year": year, "pick_no": pick_no, "team_id": team_id}
    if order is None:
        order = DraftOrder(**values)
        db.add(order)
    else:
        _assign_attrs(order, values)
    return order


def _upsert_prospect(
    db: Session,
    year: int,
    prospect_data: tuple[Any, ...],
) -> Prospect:
    prospect = (
        db.query(Prospect)
        .filter_by(year=year, name=prospect_data[0])
        .order_by(Prospect.id.asc())
        .first()
    )
    values = {
        "year": year,
        "name": prospect_data[0],
        "position": prospect_data[1],
        "age": prospect_data[2],
        "height": prospect_data[3],
        "weight": prospect_data[4],
        "school_or_league": prospect_data[5],
        "ppg": prospect_data[6],
        "rpg": prospect_data[7],
        "apg": prospect_data[8],
        "fg_pct": prospect_data[9],
        "three_pct": prospect_data[10],
        "ft_pct": prospect_data[11],
        "stocks": prospect_data[12],
        "archetype": prospect_data[13],
        "upside_score": prospect_data[14],
        "risk_score": prospect_data[15],
    }
    if prospect is None:
        prospect = Prospect(**values)
        db.add(prospect)
    else:
        _assign_attrs(prospect, values)
    return prospect


def _upsert_scouting_report(db: Session, prospect: Prospect, board_index: int) -> ScoutingReport:
    source = "DraftMind Mock Board"
    report = (
        db.query(ScoutingReport)
        .filter_by(prospect_id=prospect.id, source=source)
        .order_by(ScoutingReport.id.asc())
        .first()
    )
    values = {
        "prospect_id": prospect.id,
        "source": source,
        "report_text": (
            f"{prospect.name} profiles as a {prospect.archetype.lower()} "
            f"with a projected board range near pick {board_index}. Key swing "
            f"factors are shooting translation, decision speed, defensive "
            f"role clarity, and how quickly NBA spacing simplifies reads."
        ),
    }
    if report is None:
        report = ScoutingReport(**values)
        db.add(report)
    else:
        _assign_attrs(report, values)
    return report


def _upsert_prospect_scouting_profile(
    db: Session,
    prospect: Prospect,
) -> ProspectScoutingProfile:
    profile = (
        db.query(ProspectScoutingProfile)
        .filter_by(prospect_id=prospect.id, year=prospect.year)
        .first()
    )
    values = _build_seed_scouting_profile_data(prospect)
    payload = {"prospect_id": prospect.id, "year": prospect.year, **values}
    if profile is None:
        profile = ProspectScoutingProfile(**payload)
        db.add(profile)
    elif profile.source != "seed":
        return profile
    else:
        _assign_attrs(profile, payload)
    return profile


def _build_seed_team_need_profile(abbr: str, needs: dict[str, int]) -> dict[str, Any]:
    base: dict[str, Any] = {
        "need_guard_depth": max(needs["need_pg"], needs["need_sg"]),
        "need_wing_depth": needs["need_sf"],
        "need_big_depth": max(needs["need_pf"], needs["need_c"]),
        "need_center": needs["need_c"],
        "need_size": max(needs["need_sf"], needs["need_pf"], needs["need_c"]),
        "need_youth": 6,
        "need_nba_ready": 6,
        "need_upside": 6,
        "need_spacing": needs["need_shooting"],
        "need_shooting_volume": needs["need_shooting"],
        "need_movement_shooting": max(5, needs["need_shooting"] - 1),
        "need_self_creation": needs["need_creation"],
        "need_secondary_creation": needs["need_creation"],
        "need_playmaking": needs["need_creation"],
        "need_rim_pressure": 5,
        "need_finishing": 5,
        "need_rim_protection": needs["need_defense"],
        "need_defensive_rebounding": max(needs["need_c"], needs["need_defense"]),
        "need_offensive_rebounding": max(5, needs["need_c"]),
        "need_point_of_attack_defense": needs["need_defense"],
        "need_switchability": needs["need_defense"],
        "need_team_defense": needs["need_defense"],
        "need_foul_discipline": 5,
        "need_physicality": 6,
        "team_timeline": "retool",
        "contract_pressure": 5,
        "pending_free_agents": "",
        "development_bandwidth": 6,
        "scheme_tags": "demo-seed",
        "source": "seed",
        "horizon": "next_season",
        "need_confidence": 0.6,
        "manual_override_reason": "Demo profile expanded from seeded TeamNeed values.",
    }
    base.update(TEAM_NEED_PROFILE_OVERRIDES[abbr])
    return base


def _build_seed_scouting_profile_data(prospect: Prospect) -> dict[str, Any]:
    archetype = prospect.archetype.lower()
    is_big = prospect.position in {"C", "PF/C"} or "frontcourt" in archetype
    is_guard = prospect.position in {"PG", "SG", "G"} or "guard" in archetype
    is_shooter = prospect.three_pct >= 37 or "shooter" in archetype or "stretch" in archetype
    is_defender = prospect.stocks >= 2 or "defender" in archetype or "rim protector" in archetype

    data: dict[str, Any] = {
        "shooting_volume": 8 if is_shooter else (6 if prospect.three_pct >= 34 else 4),
        "shooting_versatility": 8 if "movement" in archetype else (7 if is_shooter else 5),
        "spacing_value": 8 if is_shooter else (6 if prospect.three_pct >= 34 else 4),
        "rim_pressure": 7 if "pressure" in archetype or is_big else 5,
        "self_creation": 8 if "creator" in archetype or "scoring guard" in archetype else 5,
        "secondary_creation": 7 if prospect.apg >= 3.5 else 5,
        "passing_feel": 8 if prospect.apg >= 5 else (6 if prospect.apg >= 3 else 4),
        "finishing": 8 if prospect.fg_pct >= 55 else (7 if prospect.fg_pct >= 52 else 5),
        "rim_protection": 8 if "rim protector" in archetype else (7 if is_big and prospect.stocks >= 2 else 4),
        "defensive_rebounding": 8 if prospect.rpg >= 8 else (6 if prospect.rpg >= 6 else 4),
        "offensive_rebounding": 7 if prospect.rpg >= 8 and is_big else 5,
        "point_of_attack_defense": 7 if is_defender and is_guard else 5,
        "switchability": 7 if "wing" in archetype or "mobile" in archetype else 5,
        "team_defense": 8 if is_defender else 5,
        "foul_discipline": 5,
        "physicality": 7 if prospect.weight >= 220 else 5,
        "height": prospect.height,
        "age": prospect.age,
        "nba_readiness": 7 if prospect.risk_score <= 25 else 5,
        "upside": round(max(1, min(10, prospect.upside_score / 10))),
        "medical_risk": round(max(1, min(10, prospect.risk_score / 10))),
        "role_projection": prospect.archetype,
        "scheme_fit_tags": _seed_scheme_tags(prospect, archetype),
        "source": "seed",
        "profile_confidence": 0.58,
        "manual_override_reason": "Demo scouting profile seeded from board role, size, and box-score proxies.",
    }

    data.update(_prospect_profile_overrides().get(prospect.name, {}))
    return data


def _prospect_profile_overrides() -> dict[str, dict[str, Any]]:
    return {
        "AJ Dybantsa": {
            "shooting_volume": 7,
            "spacing_value": 7,
            "rim_pressure": 8,
            "self_creation": 9,
            "secondary_creation": 7,
            "passing_feel": 6,
            "finishing": 8,
            "point_of_attack_defense": 7,
            "switchability": 8,
            "team_defense": 7,
            "physicality": 7,
            "nba_readiness": 7,
            "upside": 10,
            "medical_risk": 3,
            "role_projection": "two-way primary wing creator",
            "scheme_fit_tags": "wing-creation,two-way-size,transition-pressure",
            "profile_confidence": 0.66,
        },
        "Cameron Boozer": {
            "shooting_volume": 5,
            "spacing_value": 6,
            "rim_pressure": 7,
            "secondary_creation": 7,
            "passing_feel": 7,
            "finishing": 9,
            "rim_protection": 6,
            "defensive_rebounding": 9,
            "offensive_rebounding": 8,
            "team_defense": 7,
            "physicality": 8,
            "nba_readiness": 8,
            "upside": 9,
            "medical_risk": 2,
            "role_projection": "skilled frontcourt hub",
            "scheme_fit_tags": "frontcourt-hub,rebounding,finishing",
            "profile_confidence": 0.67,
        },
        "Darryn Peterson": {
            "shooting_volume": 8,
            "shooting_versatility": 7,
            "spacing_value": 8,
            "rim_pressure": 7,
            "self_creation": 9,
            "secondary_creation": 8,
            "passing_feel": 7,
            "point_of_attack_defense": 5,
            "switchability": 5,
            "nba_readiness": 7,
            "upside": 9,
            "medical_risk": 3,
            "role_projection": "scoring guard creator",
            "scheme_fit_tags": "guard-creation,three-level-scoring,secondary-playmaking",
            "profile_confidence": 0.65,
        },
        "Nate Ament": {
            "shooting_volume": 8,
            "shooting_versatility": 7,
            "spacing_value": 8,
            "rim_pressure": 5,
            "self_creation": 5,
            "secondary_creation": 6,
            "finishing": 6,
            "rim_protection": 5,
            "defensive_rebounding": 7,
            "switchability": 7,
            "team_defense": 6,
            "physicality": 5,
            "nba_readiness": 6,
            "upside": 8,
            "role_projection": "stretch forward",
            "scheme_fit_tags": "spacing-forward,weakside-size,pick-and-pop",
            "profile_confidence": 0.62,
        },
        "Koa Peat": {
            "shooting_volume": 4,
            "spacing_value": 5,
            "rim_pressure": 8,
            "finishing": 8,
            "rim_protection": 5,
            "defensive_rebounding": 8,
            "offensive_rebounding": 7,
            "switchability": 6,
            "team_defense": 6,
            "physicality": 9,
            "nba_readiness": 7,
            "upside": 8,
            "role_projection": "physical combo forward",
            "scheme_fit_tags": "physicality,rebounding,frontcourt-finishing",
            "profile_confidence": 0.61,
        },
        "Caleb Wilson": {
            "shooting_volume": 5,
            "spacing_value": 6,
            "rim_pressure": 7,
            "self_creation": 6,
            "secondary_creation": 7,
            "passing_feel": 7,
            "rim_protection": 6,
            "defensive_rebounding": 7,
            "point_of_attack_defense": 7,
            "switchability": 8,
            "team_defense": 8,
            "nba_readiness": 6,
            "upside": 8,
            "role_projection": "defensive playmaking wing",
            "scheme_fit_tags": "wing-defense,secondary-playmaking,switchability",
            "profile_confidence": 0.62,
        },
        "Mikel Brown Jr.": {
            "shooting_volume": 8,
            "shooting_versatility": 7,
            "spacing_value": 8,
            "rim_pressure": 6,
            "self_creation": 8,
            "secondary_creation": 9,
            "passing_feel": 9,
            "finishing": 5,
            "point_of_attack_defense": 5,
            "switchability": 3,
            "physicality": 4,
            "nba_readiness": 7,
            "upside": 8,
            "role_projection": "pick-and-roll lead guard",
            "scheme_fit_tags": "lead-guard,pick-and-roll,spacing-guard",
            "profile_confidence": 0.64,
        },
        "Tounde Yessoufou": {
            "shooting_volume": 5,
            "spacing_value": 6,
            "rim_pressure": 7,
            "finishing": 7,
            "rim_protection": 5,
            "defensive_rebounding": 7,
            "point_of_attack_defense": 8,
            "switchability": 8,
            "team_defense": 8,
            "physicality": 8,
            "nba_readiness": 6,
            "upside": 8,
            "role_projection": "power wing defender",
            "scheme_fit_tags": "power-wing,point-of-attack-defense,transition-finishing",
            "profile_confidence": 0.6,
        },
        "Braylon Mullins": {
            "shooting_volume": 9,
            "shooting_versatility": 8,
            "spacing_value": 9,
            "rim_pressure": 4,
            "self_creation": 5,
            "secondary_creation": 5,
            "passing_feel": 5,
            "finishing": 5,
            "point_of_attack_defense": 5,
            "switchability": 5,
            "team_defense": 5,
            "physicality": 5,
            "nba_readiness": 7,
            "upside": 7,
            "medical_risk": 2,
            "role_projection": "movement shooter",
            "scheme_fit_tags": "movement-shooting,off-ball-spacing,quick-trigger",
            "profile_confidence": 0.68,
        },
        "Jayden Quaintance": {
            "shooting_volume": 2,
            "shooting_versatility": 2,
            "spacing_value": 2,
            "rim_pressure": 7,
            "self_creation": 3,
            "secondary_creation": 4,
            "passing_feel": 4,
            "finishing": 8,
            "rim_protection": 9,
            "defensive_rebounding": 9,
            "offensive_rebounding": 8,
            "point_of_attack_defense": 4,
            "switchability": 6,
            "team_defense": 8,
            "foul_discipline": 4,
            "physicality": 8,
            "nba_readiness": 6,
            "upside": 8,
            "medical_risk": 4,
            "role_projection": "rim protector finisher",
            "scheme_fit_tags": "rim-protection,defensive-rebounding,vertical-finishing,spacing-risk",
            "profile_confidence": 0.63,
        },
        "Isiah Harwell": {
            "shooting_volume": 7,
            "spacing_value": 7,
            "rim_pressure": 5,
            "self_creation": 5,
            "secondary_creation": 5,
            "point_of_attack_defense": 6,
            "switchability": 6,
            "team_defense": 6,
            "nba_readiness": 6,
            "upside": 7,
            "role_projection": "two-way shooting guard",
            "scheme_fit_tags": "two-way-guard,spot-up-shooting,team-defense",
            "profile_confidence": 0.59,
        },
        "Darius Acuff Jr.": {
            "shooting_volume": 6,
            "spacing_value": 6,
            "rim_pressure": 8,
            "self_creation": 8,
            "secondary_creation": 8,
            "passing_feel": 8,
            "finishing": 6,
            "point_of_attack_defense": 4,
            "switchability": 3,
            "physicality": 4,
            "nba_readiness": 5,
            "upside": 8,
            "role_projection": "pressure rim guard",
            "scheme_fit_tags": "rim-pressure,guard-creation,playmaking,size-risk",
            "profile_confidence": 0.59,
        },
        "Chris Cenac Jr.": {
            "shooting_volume": 3,
            "spacing_value": 4,
            "rim_pressure": 7,
            "finishing": 8,
            "rim_protection": 8,
            "defensive_rebounding": 8,
            "offensive_rebounding": 7,
            "point_of_attack_defense": 4,
            "switchability": 7,
            "team_defense": 8,
            "physicality": 7,
            "nba_readiness": 5,
            "upside": 8,
            "role_projection": "mobile defensive big",
            "scheme_fit_tags": "mobile-big,rim-protection,vertical-spacing",
            "profile_confidence": 0.61,
        },
        "Nikolas Khamenia": {
            "shooting_volume": 7,
            "shooting_versatility": 6,
            "spacing_value": 8,
            "rim_pressure": 5,
            "secondary_creation": 7,
            "passing_feel": 8,
            "finishing": 6,
            "defensive_rebounding": 6,
            "point_of_attack_defense": 5,
            "switchability": 7,
            "team_defense": 7,
            "nba_readiness": 7,
            "upside": 7,
            "role_projection": "connector wing",
            "scheme_fit_tags": "connector-wing,spacing,team-defense,quick-decisions",
            "profile_confidence": 0.64,
        },
        "Jasper Johnson": {
            "shooting_volume": 8,
            "shooting_versatility": 8,
            "spacing_value": 8,
            "rim_pressure": 5,
            "self_creation": 7,
            "secondary_creation": 6,
            "passing_feel": 6,
            "point_of_attack_defense": 4,
            "switchability": 4,
            "physicality": 4,
            "nba_readiness": 5,
            "upside": 7,
            "role_projection": "shot-making combo guard",
            "scheme_fit_tags": "shot-making,combo-guard,spacing,defense-risk",
            "profile_confidence": 0.58,
        },
        "Malachi Moreno": {
            "shooting_volume": 1,
            "spacing_value": 2,
            "rim_pressure": 6,
            "finishing": 8,
            "rim_protection": 8,
            "defensive_rebounding": 8,
            "offensive_rebounding": 7,
            "point_of_attack_defense": 3,
            "switchability": 4,
            "team_defense": 7,
            "physicality": 8,
            "nba_readiness": 6,
            "upside": 7,
            "role_projection": "drop coverage center",
            "scheme_fit_tags": "drop-coverage,rim-protection,rebounding,spacing-risk",
            "profile_confidence": 0.6,
        },
        "Niko Bundalo": {
            "shooting_volume": 7,
            "shooting_versatility": 6,
            "spacing_value": 7,
            "rim_pressure": 5,
            "secondary_creation": 5,
            "finishing": 6,
            "rim_protection": 5,
            "defensive_rebounding": 7,
            "offensive_rebounding": 6,
            "switchability": 6,
            "team_defense": 6,
            "nba_readiness": 5,
            "upside": 7,
            "role_projection": "pick-and-pop forward",
            "scheme_fit_tags": "pick-and-pop,spacing-forward,defensive-rebounding",
            "profile_confidence": 0.58,
        },
        "Cayden Boozer": {
            "shooting_volume": 6,
            "spacing_value": 7,
            "rim_pressure": 5,
            "self_creation": 5,
            "secondary_creation": 8,
            "passing_feel": 8,
            "finishing": 6,
            "point_of_attack_defense": 5,
            "switchability": 4,
            "physicality": 5,
            "nba_readiness": 7,
            "upside": 6,
            "role_projection": "steady table-setting guard",
            "scheme_fit_tags": "table-setting,low-mistake-guard,secondary-creation",
            "profile_confidence": 0.62,
        },
        "Meleek Thomas": {
            "shooting_volume": 7,
            "spacing_value": 7,
            "rim_pressure": 6,
            "self_creation": 7,
            "secondary_creation": 6,
            "passing_feel": 5,
            "point_of_attack_defense": 5,
            "switchability": 4,
            "physicality": 5,
            "nba_readiness": 5,
            "upside": 7,
            "role_projection": "aggressive scoring guard",
            "scheme_fit_tags": "scoring-guard,shot-creation,decision-risk",
            "profile_confidence": 0.57,
        },
        "Sidi Gueye": {
            "shooting_volume": 4,
            "spacing_value": 5,
            "rim_pressure": 6,
            "finishing": 6,
            "rim_protection": 6,
            "defensive_rebounding": 7,
            "point_of_attack_defense": 7,
            "switchability": 8,
            "team_defense": 8,
            "physicality": 6,
            "nba_readiness": 4,
            "upside": 7,
            "role_projection": "long defensive wing",
            "scheme_fit_tags": "long-wing-defense,switchability,shooting-risk",
            "profile_confidence": 0.56,
        },
    }


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
