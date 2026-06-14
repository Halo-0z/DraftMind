from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, SessionLocal, engine
from app.models import Prospect, ProspectDraftProjection, Team, TeamPickProjection
from app.utils.nameutils import normalized_name


DEFAULT_SOURCE = "seed_projection"
VALID_SOURCES = {"seed_projection", "manual_projection", "consensus_reference"}
VALID_TEAM_PROJECTION_TYPES = {
    "consensus_mock",
    "team_report",
    "workout_signal",
    "manual_prediction",
}


@dataclass
class ImportSummary:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def import_prospect_projection_csv(db: Session, csv_path: str | Path) -> ImportSummary:
    summary = ImportSummary()
    for row_no, row in _read_csv_rows(csv_path):
        year = _parse_int(row, "year", default=2026)
        prospect_name = (row.get("prospect_name") or "").strip()
        if not prospect_name:
            _skip(summary, row_no, "missing prospect_name")
            continue

        try:
            prospect = _find_prospect(db, year=year, name=prospect_name)
        except ValueError as exc:
            # Ambiguous normalized-name match (duplicate prospects).  Record
            # an explicit skip so the operator sees the data-quality problem
            # instead of a projection silently landing on the wrong row.
            _skip(summary, row_no, f"ambiguous prospect: {exc}")
            continue
        if prospect is None:
            _skip(summary, row_no, f"prospect not found: {prospect_name!r}")
            continue

        source = _source_from_row(row)
        if source not in VALID_SOURCES:
            _skip(summary, row_no, f"invalid source: {source!r}")
            continue

        values = {
            "prospect_id": prospect.id,
            "year": year,
            "consensus_rank": _parse_optional_int(row, "consensus_rank"),
            "big_board_rank": _parse_optional_int(row, "big_board_rank"),
            "expected_pick": _parse_optional_int(row, "expected_pick"),
            "draft_range_min": _parse_optional_int(row, "draft_range_min"),
            "draft_range_max": _parse_optional_int(row, "draft_range_max"),
            "tier": _parse_int(row, "tier", default=5),
            "source": source,
            "source_count": _parse_int(row, "source_count", default=1),
            "confidence": _parse_float(row, "confidence", default=0.5),
            "notes": (row.get("notes") or "").strip(),
        }

        existing = (
            db.query(ProspectDraftProjection)
            .filter_by(prospect_id=prospect.id, year=year, source=source)
            .first()
        )
        if existing is None:
            db.add(ProspectDraftProjection(**values))
            summary.created += 1
        else:
            _assign_attrs(existing, values)
            summary.updated += 1
    return summary


def import_team_pick_projection_csv(db: Session, csv_path: str | Path) -> ImportSummary:
    summary = ImportSummary()
    for row_no, row in _read_csv_rows(csv_path):
        year = _parse_int(row, "year", default=2026)
        team_abbr = (row.get("team_abbr") or "").strip().upper()
        prospect_name = (row.get("prospect_name") or "").strip()
        if not team_abbr:
            _skip(summary, row_no, "missing team_abbr")
            continue
        if not prospect_name:
            _skip(summary, row_no, "missing prospect_name")
            continue

        team = db.query(Team).filter(Team.abbr == team_abbr).first()
        if team is None:
            _skip(summary, row_no, f"team not found: {team_abbr!r}")
            continue
        try:
            prospect = _find_prospect(db, year=year, name=prospect_name)
        except ValueError as exc:
            # Ambiguous normalized-name match (duplicate prospects).  Record
            # an explicit skip so the operator sees the data-quality problem
            # instead of a projection silently landing on the wrong row.
            _skip(summary, row_no, f"ambiguous prospect: {exc}")
            continue
        if prospect is None:
            _skip(summary, row_no, f"prospect not found: {prospect_name!r}")
            continue

        source = _source_from_row(row)
        if source not in VALID_SOURCES:
            _skip(summary, row_no, f"invalid source: {source!r}")
            continue
        projection_type = (row.get("projection_type") or "manual_prediction").strip()
        if projection_type not in VALID_TEAM_PROJECTION_TYPES:
            _skip(summary, row_no, f"invalid projection_type: {projection_type!r}")
            continue

        values = {
            "year": year,
            "pick_no": _parse_int(row, "pick_no"),
            "team_id": team.id,
            "prospect_id": prospect.id,
            "projection_type": projection_type,
            "source": source,
            "confidence": _parse_float(row, "confidence", default=0.5),
            "notes": (row.get("notes") or "").strip(),
        }

        existing = (
            db.query(TeamPickProjection)
            .filter_by(
                year=year,
                pick_no=values["pick_no"],
                team_id=team.id,
                prospect_id=prospect.id,
                projection_type=projection_type,
                source=source,
            )
            .first()
        )
        if existing is None:
            db.add(TeamPickProjection(**values))
            summary.created += 1
        else:
            _assign_attrs(existing, values)
            summary.updated += 1
    return summary


def _read_csv_rows(csv_path: str | Path):
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row_no, row in enumerate(reader, start=2):
            yield row_no, row


def _find_prospect(db: Session, *, year: int, name: str) -> Prospect | None:
    """Resolve a CSV/seed prospect name to a single Prospect row.

    Resolution is canonical-aware so a CSV ``Darius Acuff`` lands on the
    canonical ``Darius Acuff Jr.`` row even when a bare ``Darius Acuff``
    duplicate also exists in the pool.  Algorithm:

      1. Build the normalized-name group for ``name`` (every 2026 prospect
         whose name normalizes to the same key).
      2. If the group is empty -> return None (caller records "not found").
      3. If exactly one row has a ProspectDraftProjection and the group has
         >1 member, return that canonical row.  This is the rule that keeps
         a projection off a duplicate.
      4. If the group has exactly one member, return it (normal happy path,
         includes the case where the name is an exact display match).
      5. Otherwise the group is genuinely ambiguous (no projection, or
         multiple projections) -> raise ``ValueError``.  The caller records
         an explicit skip so the projection is never written to the wrong
         row.

    Step 3 is deliberately applied even when ``name`` is itself an exact
    display match for one of the duplicates: that is exactly the situation
    the B0-J audit found (CSV "Darius Acuff" silently matching the wrong
    duplicate).
    """
    target_key = normalized_name(name)
    if not target_key:
        return None

    candidates = (
        db.query(Prospect)
        .filter(Prospect.year == year)
        .all()
    )
    matches = [p for p in candidates if normalized_name(p.name) == target_key]
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]

    # Ambiguous group: prefer the single member with a projection (canonical).
    with_proj_ids = {
        pid
        for (pid,) in db.query(ProspectDraftProjection.prospect_id)
        .filter(ProspectDraftProjection.year == year)
        .filter(
            ProspectDraftProjection.prospect_id.in_([p.id for p in matches])
        )
        .all()
    }
    with_proj = [p for p in matches if p.id in with_proj_ids]
    if len(with_proj) == 1:
        return with_proj[0]

    # Still ambiguous (multiple projections, or none).  Refuse to guess.
    names = ", ".join(sorted(p.name for p in matches))
    raise ValueError(
        f"prospects {names!s} all normalize to {target_key!r}; "
        f"cannot unambiguously resolve {name!r}"
    )


def _source_from_row(row: dict[str, str]) -> str:
    return (row.get("source") or DEFAULT_SOURCE).strip() or DEFAULT_SOURCE


def _parse_optional_int(row: dict[str, str], key: str) -> int | None:
    raw = (row.get(key) or "").strip()
    if not raw:
        return None
    return int(raw)


def _parse_int(row: dict[str, str], key: str, *, default: int | None = None) -> int:
    raw = (row.get(key) or "").strip()
    if not raw:
        if default is None:
            raise ValueError(f"missing required integer field: {key}")
        return default
    return int(raw)


def _parse_float(row: dict[str, str], key: str, *, default: float) -> float:
    raw = (row.get(key) or "").strip()
    if not raw:
        return default
    return float(raw)


def _assign_attrs(obj: object, values: dict[str, Any]) -> None:
    for key, value in values.items():
        setattr(obj, key, value)


def _skip(summary: ImportSummary, row_no: int, message: str) -> None:
    summary.skipped += 1
    assert summary.errors is not None
    summary.errors.append(f"row {row_no}: {message}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import DraftMind projection CSV files.")
    parser.add_argument("--prospect-csv", type=Path, default=None)
    parser.add_argument("--team-csv", type=Path, default=None)
    args = parser.parse_args()

    if args.prospect_csv is None and args.team_csv is None:
        parser.error("provide --prospect-csv and/or --team-csv")

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if args.prospect_csv is not None:
            summary = import_prospect_projection_csv(db, args.prospect_csv)
            print(f"prospect projections: {summary}")
        if args.team_csv is not None:
            summary = import_team_pick_projection_csv(db, args.team_csv)
            print(f"team pick projections: {summary}")
        db.commit()


if __name__ == "__main__":
    main()
