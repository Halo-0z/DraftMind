from sqlalchemy.orm import Session

from app.models import Prospect, ProspectScoutingProfile, Team, TeamNeed, TeamNeedProfile
from app.schemas.scouting import ProspectScoutingProfileRead, TeamNeedProfileRead
from scripts.seed_db import PROSPECTS, TEAM_NEEDS, seed_demo_data


def test_team_need_profile_can_attach_to_team_and_serialize(db_session: Session) -> None:
    team = db_session.query(Team).filter(Team.abbr == "SAS").one()
    profile = TeamNeedProfile(
        team_id=team.id,
        year=2026,
        need_center=8,
        need_rim_protection=7,
        need_defensive_rebounding=8,
        need_shooting_volume=6,
        team_timeline="contend",
        source="manual",
        horizon="next_season",
        need_confidence=0.82,
        manual_override_reason="Manual GM audit: frontcourt depth and rebounding.",
        scheme_tags="drop,low-man-help",
    )
    db_session.add(profile)
    db_session.commit()

    loaded = db_session.query(TeamNeedProfile).filter_by(team_id=team.id, year=2026).one()
    payload = TeamNeedProfileRead.model_validate(loaded).model_dump()

    assert loaded.team.abbr == "SAS"
    assert payload["source"] == "manual"
    assert payload["horizon"] == "next_season"
    assert payload["team_timeline"] == "contend"
    assert payload["need_confidence"] == 0.82
    assert payload["need_rim_protection"] == 7
    assert payload["scheme_tags"] == "drop,low-man-help"


def test_prospect_scouting_profile_can_attach_to_prospect_and_serialize(
    db_session: Session,
) -> None:
    prospect = db_session.query(Prospect).filter(Prospect.name == "Braylon Mullins").one()
    profile = ProspectScoutingProfile(
        prospect_id=prospect.id,
        year=2026,
        shooting_volume=8,
        shooting_versatility=8,
        spacing_value=8,
        point_of_attack_defense=5,
        switchability=5,
        height=prospect.height,
        wingspan="6-8",
        age=prospect.age,
        nba_readiness=7,
        upside=6,
        role_projection="movement shooter",
        scheme_fit_tags="movement-shooting,off-ball",
        source="seed",
        profile_confidence=0.7,
        manual_override_reason="Seeded from demo board archetype.",
    )
    db_session.add(profile)
    db_session.commit()

    loaded = (
        db_session.query(ProspectScoutingProfile)
        .filter_by(prospect_id=prospect.id, year=2026)
        .one()
    )
    payload = ProspectScoutingProfileRead.model_validate(loaded).model_dump()

    assert loaded.prospect.name == "Braylon Mullins"
    assert payload["source"] == "seed"
    assert payload["profile_confidence"] == 0.7
    assert payload["shooting_volume"] == 8
    assert payload["wingspan"] == "6-8"
    assert payload["scheme_fit_tags"] == "movement-shooting,off-ball"


def test_profile_defaults_do_not_break_existing_team_need_or_prospect(
    db_session: Session,
) -> None:
    team = db_session.query(Team).filter(Team.abbr == "HOU").one()
    old_need = TeamNeed(
        team_id=team.id,
        year=2027,
        need_pg=5,
        need_sg=5,
        need_sf=5,
        need_pf=5,
        need_c=5,
        need_shooting=6,
        need_defense=6,
        need_creation=6,
    )
    prospect = Prospect(
        year=2027,
        name="Legacy Prospect",
        position="SF",
        age=19.0,
        height="6-7",
        weight=205,
        school_or_league="Demo",
        ppg=12.0,
        rpg=5.0,
        apg=2.0,
        fg_pct=45.0,
        three_pct=34.0,
        ft_pct=75.0,
        stocks=1.4,
        archetype="Wing prospect",
        upside_score=75.0,
        risk_score=30.0,
    )
    team_profile = TeamNeedProfile(team_id=team.id, year=2027)
    prospect_profile = ProspectScoutingProfile(prospect=prospect, year=2027)
    db_session.add_all([old_need, prospect, team_profile, prospect_profile])
    db_session.commit()

    assert old_need.need_shooting == 6
    assert prospect.three_pct == 34.0
    assert team_profile.source == "seed"
    assert team_profile.horizon == "now"
    assert team_profile.need_confidence == 0.5
    assert prospect_profile.source == "seed"
    assert prospect_profile.profile_confidence == 0.5


def test_seed_demo_data_creates_realistic_profiles_and_is_idempotent(
    db_session: Session,
) -> None:
    seed_demo_data(db_session)
    seed_demo_data(db_session)

    team_profiles = db_session.query(TeamNeedProfile).all()
    prospect_profiles = db_session.query(ProspectScoutingProfile).all()

    assert len(team_profiles) == len(TEAM_NEEDS)
    assert len(prospect_profiles) == len(PROSPECTS)
    assert db_session.query(TeamNeedProfile).filter_by(source="seed").count() == len(TEAM_NEEDS)
    assert (
        db_session.query(ProspectScoutingProfile)
        .filter_by(source="seed")
        .count()
        == len(PROSPECTS)
    )

    was = (
        db_session.query(TeamNeedProfile)
        .join(Team)
        .filter(Team.abbr == "WAS", TeamNeedProfile.year == 2026)
        .one()
    )
    assert was.team_timeline == "rebuild"
    assert was.horizon == "next_season"
    assert was.need_confidence == 0.62
    assert was.need_upside > was.need_nba_ready

    pistons = (
        db_session.query(TeamNeedProfile)
        .join(Team)
        .filter(Team.abbr == "DET", TeamNeedProfile.year == 2026)
        .one()
    )
    assert pistons.team_timeline == "retool"
    assert pistons.need_shooting_volume >= 9
    assert "shooting" in pistons.scheme_tags

    jayden = (
        db_session.query(ProspectScoutingProfile)
        .join(Prospect)
        .filter(Prospect.name == "Jayden Quaintance")
        .one()
    )
    assert jayden.rim_protection >= 9
    assert jayden.defensive_rebounding >= 8
    assert jayden.spacing_value <= 3
    assert "rim-protection" in jayden.scheme_fit_tags

    braylon = (
        db_session.query(ProspectScoutingProfile)
        .join(Prospect)
        .filter(Prospect.name == "Braylon Mullins")
        .one()
    )
    assert braylon.shooting_volume >= 8
    assert braylon.spacing_value >= 8
    assert braylon.point_of_attack_defense <= 5
    assert "movement-shooting" in braylon.scheme_fit_tags


def test_seed_demo_data_does_not_delete_existing_rows(db_session: Session) -> None:
    custom = Team(
        name="Custom Expansion Team",
        abbr="CET",
        nba_team_id=999999,
        city="Nowhere",
        conference="West",
        division="Test",
    )
    db_session.add(custom)
    db_session.commit()

    seed_demo_data(db_session)

    assert db_session.query(Team).filter_by(abbr="CET").one().name == "Custom Expansion Team"


def test_seed_demo_data_does_not_overwrite_custom_team_need_profile(
    db_session: Session,
) -> None:
    team = db_session.query(Team).filter(Team.abbr == "SAS").one()
    custom_profile = TeamNeedProfile(
        team_id=team.id,
        year=2026,
        horizon="next_season",
        source="manual",
        team_timeline="contend",
        need_center=10,
        need_confidence=0.91,
        manual_override_reason="User custom audit should survive demo seed.",
        scheme_tags="custom-lakers-style-frontcourt-audit",
    )
    db_session.add(custom_profile)
    db_session.commit()

    seed_demo_data(db_session)

    loaded = (
        db_session.query(TeamNeedProfile)
        .filter_by(team_id=team.id, year=2026, horizon="next_season")
        .one()
    )
    assert loaded.source == "manual"
    assert loaded.team_timeline == "contend"
    assert loaded.need_center == 10
    assert loaded.need_confidence == 0.91
    assert loaded.scheme_tags == "custom-lakers-style-frontcourt-audit"


def test_seed_demo_data_does_not_overwrite_custom_prospect_scouting_profile(
    db_session: Session,
) -> None:
    prospect = db_session.query(Prospect).filter(Prospect.name == "Braylon Mullins").one()
    custom_profile = ProspectScoutingProfile(
        prospect_id=prospect.id,
        year=2026,
        source="manual",
        shooting_volume=3,
        spacing_value=4,
        profile_confidence=0.92,
        role_projection="user custom role projection",
        scheme_fit_tags="custom-user-tag",
        manual_override_reason="User custom prospect profile should survive demo seed.",
    )
    db_session.add(custom_profile)
    db_session.commit()

    seed_demo_data(db_session)

    loaded = (
        db_session.query(ProspectScoutingProfile)
        .filter_by(prospect_id=prospect.id, year=2026)
        .one()
    )
    assert loaded.source == "manual"
    assert loaded.shooting_volume == 3
    assert loaded.spacing_value == 4
    assert loaded.profile_confidence == 0.92
    assert loaded.role_projection == "user custom role projection"
    assert loaded.scheme_fit_tags == "custom-user-tag"
