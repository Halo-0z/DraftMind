from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Prospect, ProspectDraftProjection, Team, TeamPickProjection
from scripts.import_projection_board import (
    import_prospect_projection_csv,
    import_team_pick_projection_csv,
)
from scripts.import_2026_consensus_projection import (
    DEMO_PROSPECT_NOTE,
    DEMO_TEAM_PICK_NOTE,
    remove_stale_demo_projection_rows,
)
from scripts.seed_db import (
    PROSPECT_PROJECTION_NOTE,
    TEAM_PICK_PROJECTION_NOTE,
    seed_demo_data,
)


def _prospect(db: Session, name: str = "Mikel Brown Jr.") -> Prospect:
    return db.query(Prospect).filter(Prospect.name == name).one()


def _team(db: Session, abbr: str = "SAS") -> Team:
    return db.query(Team).filter(Team.abbr == abbr).one()


def _write_csv(path: Path, header: str, rows: list[str]) -> Path:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_seed_projection_data_inserts_and_is_idempotent(db_session: Session) -> None:
    seed_demo_data(db_session)
    db_session.commit()

    prospect_count = db_session.query(ProspectDraftProjection).count()
    team_pick_count = db_session.query(TeamPickProjection).count()
    assert prospect_count >= 15
    assert team_pick_count >= 5

    seed_demo_data(db_session)
    db_session.commit()

    assert db_session.query(ProspectDraftProjection).count() == prospect_count
    assert db_session.query(TeamPickProjection).count() == team_pick_count


def test_seed_projection_data_does_not_overwrite_manual_projection(
    db_session: Session,
) -> None:
    prospect = _prospect(db_session)
    manual = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        expected_pick=44,
        source="manual_projection",
        confidence=0.91,
        notes="User manual projection should stay intact.",
    )
    db_session.add(manual)
    db_session.commit()

    seed_demo_data(db_session)
    db_session.commit()
    db_session.refresh(manual)

    assert manual.expected_pick == 44
    assert manual.confidence == 0.91
    assert manual.notes == "User manual projection should stay intact."


def test_seed_projection_data_updates_existing_seed_projection(
    db_session: Session,
) -> None:
    prospect = _prospect(db_session)
    seed_projection = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        expected_pick=60,
        source="seed_projection",
        confidence=0.11,
        notes="Old seed value.",
    )
    db_session.add(seed_projection)
    db_session.commit()

    seed_demo_data(db_session)
    db_session.commit()
    db_session.refresh(seed_projection)

    assert seed_projection.expected_pick != 60
    assert seed_projection.source == "seed_projection"
    assert seed_projection.notes == PROSPECT_PROJECTION_NOTE


def test_csv_prospect_import_creates_and_updates_projection(
    db_session: Session,
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(
        tmp_path / "prospect_projection.csv",
        "year,prospect_name,consensus_rank,big_board_rank,expected_pick,draft_range_min,draft_range_max,tier,source,source_count,confidence,notes",
        [
            "2026,Mikel Brown Jr.,8,9,10,7,14,2,seed_projection,5,0.7,first import",
        ],
    )

    summary = import_prospect_projection_csv(db_session, csv_path)
    db_session.commit()

    assert summary.created == 1
    projection = db_session.query(ProspectDraftProjection).one()
    assert projection.expected_pick == 10
    assert projection.notes == "first import"

    csv_path = _write_csv(
        tmp_path / "prospect_projection_update.csv",
        "year,prospect_name,consensus_rank,big_board_rank,expected_pick,draft_range_min,draft_range_max,tier,source,source_count,confidence,notes",
        [
            "2026,Mikel Brown Jr.,8,9,11,8,15,2,seed_projection,6,0.74,updated import",
        ],
    )
    summary = import_prospect_projection_csv(db_session, csv_path)
    db_session.commit()

    assert summary.updated == 1
    assert db_session.query(ProspectDraftProjection).count() == 1
    db_session.refresh(projection)
    assert projection.expected_pick == 11
    assert projection.source_count == 6
    assert projection.notes == "updated import"


def test_csv_prospect_import_skips_missing_prospect(
    db_session: Session,
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(
        tmp_path / "missing_prospect.csv",
        "year,prospect_name,consensus_rank,big_board_rank,expected_pick,draft_range_min,draft_range_max,tier,source,source_count,confidence,notes",
        [
            "2026,Missing Prospect,8,9,10,7,14,2,seed_projection,5,0.7,skip me",
        ],
    )

    summary = import_prospect_projection_csv(db_session, csv_path)

    assert summary.created == 0
    assert summary.skipped == 1
    assert "prospect not found" in summary.errors[0]


def test_csv_team_import_creates_projection(
    db_session: Session,
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(
        tmp_path / "team_projection.csv",
        "year,pick_no,team_abbr,prospect_name,projection_type,source,confidence,notes",
        [
            "2026,2,SAS,Mikel Brown Jr.,team_report,seed_projection,0.66,team signal",
        ],
    )

    summary = import_team_pick_projection_csv(db_session, csv_path)
    db_session.commit()

    assert summary.created == 1
    projection = db_session.query(TeamPickProjection).one()
    assert projection.pick_no == 2
    assert projection.team.abbr == "SAS"
    assert projection.prospect.name == "Mikel Brown Jr."
    assert projection.notes == "team signal"


def test_csv_team_import_skips_missing_team_or_prospect(
    db_session: Session,
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(
        tmp_path / "missing_team_or_prospect.csv",
        "year,pick_no,team_abbr,prospect_name,projection_type,source,confidence,notes",
        [
            "2026,2,XXX,Mikel Brown Jr.,team_report,seed_projection,0.66,missing team",
            "2026,2,SAS,Missing Prospect,team_report,seed_projection,0.66,missing prospect",
        ],
    )

    summary = import_team_pick_projection_csv(db_session, csv_path)

    assert summary.created == 0
    assert summary.skipped == 2
    assert "team not found" in summary.errors[0]
    assert "prospect not found" in summary.errors[1]


def test_csv_import_defaults_to_seed_projection_and_does_not_overwrite_manual(
    db_session: Session,
    tmp_path: Path,
) -> None:
    prospect = _prospect(db_session)
    manual = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        expected_pick=33,
        source="manual_projection",
        confidence=0.95,
        notes="manual stays",
    )
    db_session.add(manual)
    db_session.commit()
    csv_path = _write_csv(
        tmp_path / "default_source.csv",
        "year,prospect_name,consensus_rank,big_board_rank,expected_pick,draft_range_min,draft_range_max,tier,source,source_count,confidence,notes",
        [
            "2026,Mikel Brown Jr.,8,9,10,7,14,2,,5,0.7,default seed row",
        ],
    )

    summary = import_prospect_projection_csv(db_session, csv_path)
    db_session.commit()
    db_session.refresh(manual)

    assert summary.created == 1
    assert manual.expected_pick == 33
    assert manual.notes == "manual stays"
    assert db_session.query(ProspectDraftProjection).count() == 2


def test_csv_import_does_not_affect_simulation_selected_player(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    before = client.post("/api/simulate", json={"year": 2026, "rounds": 1, "limit": 1})
    assert before.status_code == 200
    before_name = before.json()["picks"][0]["selected_player"]["prospect"]["name"]

    csv_path = _write_csv(
        tmp_path / "projection_only.csv",
        "year,pick_no,team_abbr,prospect_name,projection_type,source,confidence,notes",
        [
            "2026,2,SAS,Braylon Mullins,manual_prediction,seed_projection,1.0,projection only",
        ],
    )
    summary = import_team_pick_projection_csv(db_session, csv_path)
    db_session.commit()

    after = client.post("/api/simulate", json={"year": 2026, "rounds": 1, "limit": 1})
    assert summary.created == 1
    assert after.status_code == 200
    assert after.json()["picks"][0]["selected_player"]["prospect"]["name"] == before_name


def test_consensus_import_removes_only_stale_demo_projection_rows(
    db_session: Session,
) -> None:
    prospect = _prospect(db_session)
    other_prospect = _prospect(db_session, "Braylon Mullins")
    team = _team(db_session)
    demo_projection = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        expected_pick=10,
        source="seed_projection",
        confidence=0.4,
        notes=DEMO_PROSPECT_NOTE,
    )
    custom_seed_projection = ProspectDraftProjection(
        prospect_id=other_prospect.id,
        year=2026,
        expected_pick=11,
        source="seed_projection",
        confidence=0.6,
        notes="Custom seed projection should stay.",
    )
    manual_projection = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        expected_pick=12,
        source="manual_projection",
        confidence=0.9,
        notes="Manual projection should stay.",
    )
    demo_team_projection = TeamPickProjection(
        year=2026,
        pick_no=2,
        team_id=team.id,
        prospect_id=prospect.id,
        projection_type="consensus_mock",
        source="seed_projection",
        confidence=0.4,
        notes=DEMO_TEAM_PICK_NOTE,
    )
    db_session.add_all(
        [
            demo_projection,
            custom_seed_projection,
            manual_projection,
            demo_team_projection,
        ]
    )
    db_session.commit()

    removed_prospects, removed_team_picks = remove_stale_demo_projection_rows(
        db_session
    )
    db_session.commit()

    assert removed_prospects == 1
    assert removed_team_picks == 1
    remaining_notes = {
        row.notes for row in db_session.query(ProspectDraftProjection).all()
    }
    assert DEMO_PROSPECT_NOTE not in remaining_notes
    assert "Custom seed projection should stay." in remaining_notes
    assert "Manual projection should stay." in remaining_notes
    assert db_session.query(TeamPickProjection).count() == 0
