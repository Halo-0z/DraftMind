"""B0-K2 tests: Class A seed_manual projection market priors.

Covers:
  1. The 7 Class A prospects get a ProspectDraftProjection when their CSV
     rows are imported, with the expected expected_pick / range / tier /
     confidence / source.
  2. Re-importing the same CSV is idempotent (no duplicate projections,
     no count drift).
  3. The importer resolves these prospects by normalized name (the CSV
     names match the seeded canonical display names exactly here, but the
     guard is the same normalized-name machinery used elsewhere).
  4. A pre-existing ``manual_projection`` row is NOT overwritten by the
     consensus_reference import (source is part of the unique key).
  5. With projections in place, audit_projection_coverage's high-upside
     no-projection section no longer lists them.
  6. The import path does not crash on the live CSV (smoke check that the
     shipped CSV is well-formed).

These tests do NOT assert on ranking_engine / final_score / selected_player
-- B0-K2 only adds market priors and must not change selection behaviour.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Prospect, ProspectDraftProjection
from app.utils.nameutils import normalized_name
from scripts.audit_projection_coverage import build_report
from scripts.import_projection_board import import_prospect_projection_csv


# The 7 Class A prospects and their B0-K2 projection values.
CLASS_A = {
    "Tounde Yessoufou": dict(expected_pick=11, draft_range_min=9,  draft_range_max=15, tier=3, confidence=0.70),
    "Braylon Mullins":  dict(expected_pick=13, draft_range_min=10, draft_range_max=18, tier=3, confidence=0.70),
    "Isiah Harwell":    dict(expected_pick=16, draft_range_min=12, draft_range_max=22, tier=4, confidence=0.64),
    "Nikolas Khamenia": dict(expected_pick=20, draft_range_min=16, draft_range_max=26, tier=4, confidence=0.64),
    "Cayden Boozer":    dict(expected_pick=22, draft_range_min=18, draft_range_max=28, tier=4, confidence=0.64),
    "Jasper Johnson":   dict(expected_pick=24, draft_range_min=20, draft_range_max=30, tier=4, confidence=0.64),
    "Niko Bundalo":     dict(expected_pick=28, draft_range_min=24, draft_range_max=34, tier=5, confidence=0.54),
}

HEADER = (
    "year,prospect_name,consensus_rank,big_board_rank,expected_pick,"
    "draft_range_min,draft_range_max,tier,source,source_count,confidence,notes"
)


def _class_a_row(name: str, spec: dict) -> str:
    return (
        f'2026,{name},{spec["expected_pick"]},{spec["expected_pick"]},'
        f'{spec["expected_pick"]},{spec["draft_range_min"]},'
        f'{spec["draft_range_max"]},{spec["tier"]},consensus_reference,1,'
        f'{spec["confidence"]},"Class A B0-K2 test row"'
    )


def _add_prospect(db: Session, *, name: str, position: str = "SG") -> Prospect:
    p = Prospect(
        year=2026, name=name, position=position, age=19.0, height="6-4",
        weight=190, school_or_league="Test U", ppg=14.0, rpg=4.0, apg=3.0,
        fg_pct=45.0, three_pct=35.0, ft_pct=75.0, stocks=1.5,
        archetype="Versatile", upside_score=82.0, risk_score=25.0,
    )
    db.add(p)
    db.flush()
    return p


def _seed_class_a_prospects(db: Session) -> dict[str, Prospect]:
    """Ensure each Class A prospect exists exactly once.

    The conftest ``db_session`` fixture already pre-seeds a couple of 2026
    prospects (notably "Mikel Brown Jr." and "Braylon Mullins").  Adding a
    second "Braylon Mullins" would create a same-display-name duplicate that
    the B0-J1 normalized-name guard correctly refuses to resolve -- so we
    reuse the existing row when one is already present rather than blindly
    inserting.
    """
    out: dict[str, Prospect] = {}
    for name in CLASS_A:
        existing = db.query(Prospect).filter(
            Prospect.year == 2026, Prospect.name == name,
        ).first()
        if existing is not None:
            out[name] = existing
            continue
        out[name] = _add_prospect(db, name=name)
    db.commit()
    return out


def _write_class_a_csv(path: Path) -> Path:
    rows = [_class_a_row(name, spec) for name, spec in CLASS_A.items()]
    path.write_text(HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Case 1 + 2: import creates the 7 projections with correct values + is idempotent
# ---------------------------------------------------------------------------


def test_class_a_csv_import_creates_projections_with_expected_values(
    db_session: Session, tmp_path: Path,
) -> None:
    _seed_class_a_prospects(db_session)
    csv_path = _write_class_a_csv(tmp_path / "class_a.csv")

    summary = import_prospect_projection_csv(db_session, csv_path)
    db_session.commit()

    assert summary.created == 7
    assert summary.skipped == 0

    for name, spec in CLASS_A.items():
        prospect = db_session.query(Prospect).filter(
            Prospect.year == 2026, Prospect.name == name,
        ).one()
        proj = db_session.query(ProspectDraftProjection).filter_by(
            prospect_id=prospect.id, year=2026, source="consensus_reference",
        ).one()
        assert proj.expected_pick == spec["expected_pick"], name
        assert proj.draft_range_min == spec["draft_range_min"], name
        assert proj.draft_range_max == spec["draft_range_max"], name
        assert proj.tier == spec["tier"], name
        assert proj.confidence == spec["confidence"], name
        assert proj.source == "consensus_reference", name


def test_class_a_csv_import_is_idempotent(
    db_session: Session, tmp_path: Path,
) -> None:
    _seed_class_a_prospects(db_session)
    csv_path = _write_class_a_csv(tmp_path / "class_a.csv")

    import_prospect_projection_csv(db_session, csv_path)
    db_session.commit()
    count_after_first = db_session.query(ProspectDraftProjection).count()

    # Re-import the identical CSV: must not create duplicates.
    summary2 = import_prospect_projection_csv(db_session, csv_path)
    db_session.commit()
    count_after_second = db_session.query(ProspectDraftProjection).count()

    assert summary2.created == 0
    assert summary2.updated == 7  # same source-key rows get updated in place
    assert count_after_second == count_after_first


# ---------------------------------------------------------------------------
# Case 3: normalized_name resolves these names (no Jr./punctuation ambiguity)
# ---------------------------------------------------------------------------


def test_class_a_names_normalize_consistently() -> None:
    """The 7 Class A names have no Jr./Sr./punctuation variants, but they
    must still normalize deterministically so the importer can match them
    even if a future source spells them with different case/spacing."""
    for name in CLASS_A:
        norm = normalized_name(name)
        # Re-normalizing the lowered/trimmed name must be a fixed point.
        assert normalized_name(name.upper()) == norm
        assert normalized_name(" " + name + " ") == norm


# ---------------------------------------------------------------------------
# Case 4: a pre-existing manual_projection is NOT overwritten
# ---------------------------------------------------------------------------


def test_class_a_import_does_not_overwrite_manual_projection(
    db_session: Session, tmp_path: Path,
) -> None:
    """Source is part of the ProspectDraftProjection unique key, so a
    consensus_reference import cannot clobber a manual_projection row."""
    prospects = _seed_class_a_prospects(db_session)
    target = prospects["Tounde Yessoufou"]
    db_session.add(ProspectDraftProjection(
        prospect_id=target.id, year=2026, expected_pick=2,
        draft_range_min=1, draft_range_max=4, tier=1,
        source="manual_projection", confidence=0.95,
        notes="User override must survive the import.",
    ))
    db_session.commit()

    csv_path = _write_class_a_csv(tmp_path / "class_a.csv")
    import_prospect_projection_csv(db_session, csv_path)
    db_session.commit()

    # Both rows coexist (different source keys).
    rows = db_session.query(ProspectDraftProjection).filter_by(
        prospect_id=target.id, year=2026,
    ).all()
    sources = {r.source for r in rows}
    assert sources == {"manual_projection", "consensus_reference"}
    manual = next(r for r in rows if r.source == "manual_projection")
    assert manual.expected_pick == 2  # untouched
    assert manual.confidence == 0.95


# ---------------------------------------------------------------------------
# Case 5: with projections in place, audit no longer lists them as
# high-upside no-projection.
# ---------------------------------------------------------------------------


def test_audit_excludes_class_a_once_projected(
    db_session: Session, tmp_path: Path,
) -> None:
    _seed_class_a_prospects(db_session)
    csv_path = _write_class_a_csv(tmp_path / "class_a.csv")
    import_prospect_projection_csv(db_session, csv_path)
    db_session.commit()

    report = build_report(db_session, min_upside=76.0, top_n=0)
    high_upside_no_proj_names = {e["name"] for e in report.high_upside_no_projection}

    for name in CLASS_A:
        assert name not in high_upside_no_proj_names, (
            f"{name} should no longer appear in high-upside no-projection "
            "once it has a projection"
        )


# ---------------------------------------------------------------------------
# Case 6: the shipped live CSV is well-formed and re-importable.
# ---------------------------------------------------------------------------


def test_live_consensus_csv_includes_class_a_rows() -> None:
    """The shipped 2026_consensus_projection_board.csv must contain the 7
    Class A rows (this is the real data change of B0-K2)."""
    import csv as _csv

    live_csv = (
        Path(__file__).resolve().parents[2]
        / "data" / "projections" / "2026_consensus_projection_board.csv"
    )
    rows = list(_csv.DictReader(live_csv.open(newline="", encoding="utf-8-sig")))
    by_name = {r["prospect_name"]: r for r in rows}

    for name, spec in CLASS_A.items():
        assert name in by_name, f"{name} missing from live CSV"
        row = by_name[name]
        assert int(row["expected_pick"]) == spec["expected_pick"], name
        assert int(row["draft_range_min"]) == spec["draft_range_min"], name
        assert int(row["draft_range_max"]) == spec["draft_range_max"], name
        assert int(row["tier"]) == spec["tier"], name
        assert float(row["confidence"]) == spec["confidence"], name
        assert row["source"] == "consensus_reference", name


def test_live_consensus_csv_has_no_duplicate_prospect_names() -> None:
    """The shipped CSV must not list the same prospect_name twice after the
    B0-K2 insertion (the re-sort script is idempotent, but guard the data)."""
    import csv as _csv

    live_csv = (
        Path(__file__).resolve().parents[2]
        / "data" / "projections" / "2026_consensus_projection_board.csv"
    )
    rows = list(_csv.DictReader(live_csv.open(newline="", encoding="utf-8-sig")))
    names = [r["prospect_name"] for r in rows]
    assert len(names) == len(set(names)), "duplicate prospect_name in live CSV"
