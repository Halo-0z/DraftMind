from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Prospect, ProspectScoutingProfile, Team, TeamNeedProfile


def _spurs(db: Session) -> Team:
    team = db.query(Team).filter(Team.abbr == "SAS").one()
    return team


def _prospect(db: Session, name: str = "Mikel Brown Jr.") -> Prospect:
    prospect = db.query(Prospect).filter(Prospect.name == name).one()
    return prospect


def test_get_team_profile_exists(client: TestClient, db_session: Session) -> None:
    team = _spurs(db_session)
    db_session.add(
        TeamNeedProfile(
            team_id=team.id,
            year=2026,
            horizon="next_season",
            source="seed",
            need_center=8,
            need_confidence=0.65,
        )
    )
    db_session.commit()

    response = client.get(
        "/api/scouting/team-profiles",
        params={"team_id": team.id, "year": 2026, "horizon": "next_season"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["team_id"] == team.id
    assert body["need_center"] == 8
    assert body["source"] == "seed"
    assert body["need_confidence"] == 0.65


def test_get_team_profile_missing_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    team = _spurs(db_session)

    response = client.get(
        "/api/scouting/team-profiles",
        params={"team_id": team.id, "year": 2099, "horizon": "next_season"},
    )

    assert response.status_code == 404


def test_post_team_profile_creates_manual_profile(
    client: TestClient,
    db_session: Session,
) -> None:
    team = _spurs(db_session)

    response = client.post(
        "/api/scouting/team-profiles",
        json={
            "team_id": team.id,
            "year": 2027,
            "need_center": 9,
            "need_rim_protection": 8,
            "manual_override_reason": "Manual frontcourt profile.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["team_id"] == team.id
    assert body["year"] == 2027
    assert body["horizon"] == "next_season"
    assert body["source"] == "manual"
    assert body["need_confidence"] == 1.0
    assert body["need_center"] == 9
    assert body["need_rim_protection"] == 8


def test_post_team_profile_updates_seed_profile_and_converts_to_manual(
    client: TestClient,
    db_session: Session,
) -> None:
    team = _spurs(db_session)
    db_session.add(
        TeamNeedProfile(
            team_id=team.id,
            year=2026,
            horizon="next_season",
            source="seed",
            need_center=5,
            need_confidence=0.5,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/scouting/team-profiles",
        json={
            "team_id": team.id,
            "year": 2026,
            "horizon": "next_season",
            "need_center": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "manual"
    assert body["need_confidence"] == 1.0
    assert body["need_center"] == 10
    assert (
        db_session.query(TeamNeedProfile)
        .filter_by(team_id=team.id, year=2026, horizon="next_season")
        .count()
        == 1
    )


def test_post_team_profile_validates_trait_range(
    client: TestClient,
    db_session: Session,
) -> None:
    response = client.post(
        "/api/scouting/team-profiles",
        json={
            "team_id": _spurs(db_session).id,
            "year": 2027,
            "need_center": 11,
        },
    )

    assert response.status_code == 422


def test_post_team_profile_validates_confidence_range(
    client: TestClient,
    db_session: Session,
) -> None:
    response = client.post(
        "/api/scouting/team-profiles",
        json={
            "team_id": _spurs(db_session).id,
            "year": 2027,
            "need_confidence": 1.5,
        },
    )

    assert response.status_code == 422


def test_team_news_display_only_profile_becomes_manual_after_edit(
    client: TestClient,
    db_session: Session,
) -> None:
    team = _spurs(db_session)
    db_session.add(
        TeamNeedProfile(
            team_id=team.id,
            year=2027,
            horizon="next_season",
            source="news_display_only",
            need_confidence=0.2,
            need_center=6,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/scouting/team-profiles",
        json={"team_id": team.id, "year": 2027, "need_center": 9},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "manual"
    assert body["need_confidence"] == 1.0
    assert body["need_center"] == 9


def test_get_prospect_profile_exists(client: TestClient, db_session: Session) -> None:
    prospect = _prospect(db_session)
    db_session.add(
        ProspectScoutingProfile(
            prospect_id=prospect.id,
            year=2026,
            source="seed",
            rim_protection=7,
            profile_confidence=0.6,
        )
    )
    db_session.commit()

    response = client.get(
        "/api/scouting/prospect-profiles",
        params={"prospect_id": prospect.id, "year": 2026},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["prospect_id"] == prospect.id
    assert body["rim_protection"] == 7
    assert body["source"] == "seed"
    assert body["profile_confidence"] == 0.6


def test_get_prospect_profile_missing_returns_404(
    client: TestClient,
    db_session: Session,
) -> None:
    response = client.get(
        "/api/scouting/prospect-profiles",
        params={"prospect_id": _prospect(db_session).id, "year": 2099},
    )

    assert response.status_code == 404


def test_post_prospect_profile_creates_manual_profile(
    client: TestClient,
    db_session: Session,
) -> None:
    prospect = _prospect(db_session)

    response = client.post(
        "/api/scouting/prospect-profiles",
        json={
            "prospect_id": prospect.id,
            "year": 2027,
            "rim_protection": 8,
            "spacing_value": 4,
            "manual_override_reason": "Manual scouting update.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["prospect_id"] == prospect.id
    assert body["year"] == 2027
    assert body["source"] == "manual"
    assert body["profile_confidence"] == 1.0
    assert body["rim_protection"] == 8
    assert body["spacing_value"] == 4


def test_post_prospect_profile_updates_seed_profile_and_converts_to_manual(
    client: TestClient,
    db_session: Session,
) -> None:
    prospect = _prospect(db_session)
    db_session.add(
        ProspectScoutingProfile(
            prospect_id=prospect.id,
            year=2026,
            source="seed",
            rim_protection=5,
            profile_confidence=0.5,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/scouting/prospect-profiles",
        json={
            "prospect_id": prospect.id,
            "year": 2026,
            "rim_protection": 9,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "manual"
    assert body["profile_confidence"] == 1.0
    assert body["rim_protection"] == 9
    assert (
        db_session.query(ProspectScoutingProfile)
        .filter_by(prospect_id=prospect.id, year=2026)
        .count()
        == 1
    )


def test_post_prospect_profile_validates_trait_range(
    client: TestClient,
    db_session: Session,
) -> None:
    response = client.post(
        "/api/scouting/prospect-profiles",
        json={
            "prospect_id": _prospect(db_session).id,
            "year": 2027,
            "rim_protection": 0,
        },
    )

    assert response.status_code == 422


def test_post_prospect_profile_validates_confidence_range(
    client: TestClient,
    db_session: Session,
) -> None:
    response = client.post(
        "/api/scouting/prospect-profiles",
        json={
            "prospect_id": _prospect(db_session).id,
            "year": 2027,
            "profile_confidence": -0.1,
        },
    )

    assert response.status_code == 422


def test_prospect_news_display_only_profile_becomes_manual_after_edit(
    client: TestClient,
    db_session: Session,
) -> None:
    prospect = _prospect(db_session)
    db_session.add(
        ProspectScoutingProfile(
            prospect_id=prospect.id,
            year=2027,
            source="news_display_only",
            profile_confidence=0.1,
            rim_protection=5,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/scouting/prospect-profiles",
        json={"prospect_id": prospect.id, "year": 2027, "rim_protection": 8},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "manual"
    assert body["profile_confidence"] == 1.0
    assert body["rim_protection"] == 8


def test_manual_source_request_cannot_be_news_display_only(
    client: TestClient,
    db_session: Session,
) -> None:
    response = client.post(
        "/api/scouting/prospect-profiles",
        json={
            "prospect_id": _prospect(db_session).id,
            "year": 2027,
            "source": "news_display_only",
        },
    )

    assert response.status_code == 422
