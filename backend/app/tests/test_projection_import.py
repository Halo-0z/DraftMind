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


# ---------------------------------------------------------------------------
# B0-J1: normalized-name duplicate guard in import_projection_board
# ---------------------------------------------------------------------------


def _make_prospect(
    db: Session,
    *,
    name: str,
    position: str = "PG",
    upside: float = 80.0,
) -> Prospect:
    p = Prospect(
        year=2026,
        name=name,
        position=position,
        age=19.0,
        height="6-4",
        weight=190,
        school_or_league="Test U",
        ppg=14.0,
        rpg=4.0,
        apg=3.0,
        fg_pct=45.0,
        three_pct=35.0,
        ft_pct=75.0,
        stocks=1.5,
        archetype="Versatile",
        upside_score=upside,
        risk_score=25.0,
    )
    db.add(p)
    db.flush()
    return p


def test_find_prospect_resolves_suffixless_name_to_canonical_row(
    db_session: Session,
) -> None:
    """A CSV row 'Darius Acuff' must resolve to the seeded canonical
    'Darius Acuff Jr.' rather than returning None (and skipping the row) or
    creating a duplicate."""
    from scripts.import_projection_board import _find_prospect

    canonical = _make_prospect(db_session, name="Darius Acuff Jr.")
    db_session.commit()

    resolved = _find_prospect(db_session, year=2026, name="Darius Acuff")
    assert resolved is not None
    assert resolved.id == canonical.id
    assert resolved.name == "Darius Acuff Jr."


def test_find_prospect_raises_on_ambiguous_duplicate_group(
    db_session: Session,
) -> None:
    """If two real prospect rows normalize to the same key (a genuine
    duplicate), _find_prospect must raise ValueError instead of silently
    picking one -- the projection must never land on the wrong row."""
    import pytest

    from scripts.import_projection_board import _find_prospect

    _make_prospect(db_session, name="Darius Acuff Jr.")
    _make_prospect(db_session, name="Darius Acuff")
    db_session.commit()

    with pytest.raises(ValueError, match="normalize"):
        _find_prospect(db_session, year=2026, name="Darius Acuff")


def test_import_prospect_projection_skips_ambiguous_duplicate_row(
    db_session: Session, tmp_path: Path,
) -> None:
    """When a CSV row resolves to an ambiguous duplicate group, the importer
    must record an explicit skip (not crash, not silently pick)."""
    _make_prospect(db_session, name="Darius Acuff Jr.")
    _make_prospect(db_session, name="Darius Acuff")
    db_session.commit()

    csv_path = _write_csv(
        tmp_path / "ambiguous.csv",
        "year,prospect_name,consensus_rank,big_board_rank,expected_pick,"
        "draft_range_min,draft_range_max,tier,source,source_count,confidence,notes",
        [
            '2026,Darius Acuff,5,5,5,4,7,2,consensus_reference,2,0.74,"ambiguous"',
        ],
    )

    summary = import_prospect_projection_csv(db_session, csv_path)
    db_session.commit()

    assert summary.created == 0
    assert summary.updated == 0
    assert summary.skipped == 1
    assert any("ambiguous prospect" in err for err in (summary.errors or []))
    # No projection was written.
    assert db_session.query(ProspectDraftProjection).count() == 0


def test_import_prospect_projection_writes_to_canonical_via_normalized_match(
    db_session: Session, tmp_path: Path,
) -> None:
    """The happy path of the suffixless-name fix: a CSV 'Darius Acuff' row
    lands its projection on the canonical 'Darius Acuff Jr.' prospect."""
    canonical = _make_prospect(db_session, name="Darius Acuff Jr.")
    db_session.commit()

    csv_path = _write_csv(
        tmp_path / "canonical.csv",
        "year,prospect_name,consensus_rank,big_board_rank,expected_pick,"
        "draft_range_min,draft_range_max,tier,source,source_count,confidence,notes",
        [
            '2026,Darius Acuff,5,5,5,4,7,2,consensus_reference,2,0.74,"via norm"',
        ],
    )

    summary = import_prospect_projection_csv(db_session, csv_path)
    db_session.commit()

    assert summary.created == 1
    assert summary.skipped == 0
    proj = db_session.query(ProspectDraftProjection).one()
    assert proj.prospect_id == canonical.id
    assert proj.expected_pick == 5


# ---------------------------------------------------------------------------
# M4-D: projection field upper bound widened from 60 to 100
# ---------------------------------------------------------------------------


def test_prospect_projection_accepts_expected_pick_above_60(
    db_session: Session,
) -> None:
    """M4-D: ProspectDraftProjection must accept expected_pick=65
    (second-round / UDFA-bubble projection)."""
    prospect = _prospect(db_session)
    projection = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        expected_pick=65,
        consensus_rank=68,
        big_board_rank=82,
        draft_range_min=54,
        draft_range_max=97,
        tier=6,
        source="consensus_reference",
        source_count=4,
        confidence=0.52,
        notes="M4-D second-round projection",
    )
    db_session.add(projection)
    db_session.commit()
    db_session.refresh(projection)

    assert projection.expected_pick == 65
    assert projection.consensus_rank == 68
    assert projection.big_board_rank == 82
    assert projection.draft_range_max == 97


def test_prospect_projection_rejects_expected_pick_above_100(
    db_session: Session,
) -> None:
    """M4-D: ProspectDraftProjection must still reject expected_pick=101."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    prospect = _prospect(db_session)
    projection = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        expected_pick=101,
        tier=6,
        source="consensus_reference",
        source_count=1,
        confidence=0.5,
        notes="should fail",
    )
    db_session.add(projection)
    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        db_session.commit()
    db_session.rollback()


def test_prospect_projection_rejects_draft_range_max_above_100(
    db_session: Session,
) -> None:
    """M4-D: draft_range_max=101 must still be rejected."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    prospect = _prospect(db_session)
    projection = ProspectDraftProjection(
        prospect_id=prospect.id,
        year=2026,
        expected_pick=65,
        draft_range_min=60,
        draft_range_max=101,
        tier=6,
        source="consensus_reference",
        source_count=1,
        confidence=0.5,
        notes="should fail",
    )
    db_session.add(projection)
    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        db_session.commit()
    db_session.rollback()


def test_csv_import_accepts_expected_pick_above_60(
    db_session: Session,
    tmp_path: Path,
) -> None:
    """M4-D: importer must accept a CSV row with expected_pick=65."""
    csv_path = _write_csv(
        tmp_path / "second_round.csv",
        "year,prospect_name,consensus_rank,big_board_rank,expected_pick,draft_range_min,draft_range_max,tier,source,source_count,confidence,notes",
        [
            "2026,Mikel Brown Jr.,65,65,65,62,67,6,consensus_reference,4,0.54,second round",
        ],
    )

    summary = import_prospect_projection_csv(db_session, csv_path)
    db_session.commit()

    assert summary.created == 1
    projection = db_session.query(ProspectDraftProjection).one()
    assert projection.expected_pick == 65
    assert projection.draft_range_max == 67
    assert projection.notes == "second round"


def test_team_pick_projection_still_rejects_pick_no_above_60(
    db_session: Session,
) -> None:
    """M4-D: TeamPickProjection.pick_no must still be limited to 1-60
    (the NBA draft only has 60 picks)."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    prospect = _prospect(db_session)
    team = _team(db_session)
    projection = TeamPickProjection(
        year=2026,
        pick_no=61,
        team_id=team.id,
        prospect_id=prospect.id,
        projection_type="consensus_mock",
        source="seed_projection",
        confidence=0.5,
        notes="should fail",
    )
    db_session.add(projection)
    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        db_session.commit()
    db_session.rollback()
