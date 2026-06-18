"""RAG-v1-D1-E2: Dev-only seed script for ManualNoteRecord.

This script writes a small set of demo ``ManualNoteRecord`` rows into the
``manual_notes`` table so that the persisted retrieval chain
(``retrieve_manual_note_documents`` -> ``EvidenceDocumentRead`` ->
``retrieved_evidence / citations``) can be verified locally.

Scope:
- Dev/test only.  Not a production data import.
- Only writes ``ManualNoteRecord``.  Never touches ranking_engine,
  simulation_service, prediction_calibration, prospects, teams, etc.
- All seed notes have ``evidence_only=True`` and ``source="manual_seed"``.
- Non-destructive:重复运行不会重复插入,不会删除或覆盖已有 custom notes.

Usage:
    cd backend
    python scripts/seed_manual_notes.py

After seeding, enable retrieval locally:
    # In .env or environment
    EVIDENCE_RETRIEVE_MANUAL_NOTES=True
    # Then restart the API and call POST /api/evidence/pick
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, SessionLocal, engine
from app.models import ManualNoteRecord, Prospect, Team


SEED_SOURCE = "manual_seed"
SEED_YEAR = 2026


def _build_demo_notes(
    sas: Team | None,
    hou: Team | None,
    mikel: Prospect | None,
    braylon: Prospect | None,
) -> list[dict[str, Any]]:
    """Build the list of demo note payloads.

    Returns a list of dicts whose keys match ManualNoteRecord fields.
    ``prospect_id`` / ``team_id`` are resolved from the DB; if a demo
    entity is missing, that note is simply not built (graceful skip).
    """
    notes: list[dict[str, Any]] = []

    sas_id = sas.id if sas is not None else None
    hou_id = hou.id if hou is not None else None
    mikel_id = mikel.id if mikel is not None else None
    braylon_id = braylon.id if braylon is not None else None

    # 1. Prospect-only note (prospect_id filter)
    if mikel_id is not None:
        notes.append({
            "year": SEED_YEAR,
            "entity_type": "prospect",
            "entity_id": str(mikel_id),
            "prospect_id": mikel_id,
            "team_id": None,
            "pick_no": None,
            "title": "Mikel Brown Jr. — workout passing feel",
            "body": (
                "Demo seed note: Mikel Brown Jr. displayed advanced passing "
                "feel in the 5-on-0 transition drill, reading the tag defender "
                "and delivering skip passes with pace. Not official scouting."
            ),
            "summary": "Workout passing feel observation (dev seed).",
            "source": SEED_SOURCE,
            "author": "dev_seed",
            "source_url": None,
            "source_date": "2026-06-10",
            "confidence": 0.7,
            "tags": "passing,transition,dev_seed",
            "relevance_reason": "Explains creation upside for a guard prospect.",
            "evidence_only": True,
        })

    # 2. Team-only note (team_id filter)
    if sas_id is not None:
        notes.append({
            "year": SEED_YEAR,
            "entity_type": "team",
            "entity_id": sas.abbr,
            "prospect_id": None,
            "team_id": sas_id,
            "pick_no": None,
            "title": "SAS — guard creation need context",
            "body": (
                "Demo seed note: San Antonio's roster construction around "
                "Wembanyama prioritizes secondary guard creation and spacing. "
                "Not official team analysis."
            ),
            "summary": "SAS guard creation need context (dev seed).",
            "source": SEED_SOURCE,
            "author": "dev_seed",
            "source_url": None,
            "source_date": "2026-06-11",
            "confidence": 0.65,
            "tags": "team_need,guard_creation,dev_seed",
            "relevance_reason": "Explains why a guard prospect fits this team.",
            "evidence_only": True,
        })

    # 3. Pick-only note (pick_no filter)
    notes.append({
        "year": SEED_YEAR,
        "entity_type": "pick",
        "entity_id": "5",
        "prospect_id": None,
        "team_id": None,
        "pick_no": 5,
        "title": "Pick 5 — draft board context",
        "body": (
            "Demo seed note: Pick 5 in the 2026 mock is a pivot point where "
            "wing creators and stretch forwards are both in range. Not "
            "official draft analysis."
        ),
        "summary": "Pick 5 board context (dev seed).",
        "source": SEED_SOURCE,
        "author": "dev_seed",
        "source_url": None,
        "source_date": "2026-06-12",
        "confidence": 0.6,
        "tags": "draft_board,pick_context,dev_seed",
        "relevance_reason": "Explains the draft context around pick 5.",
        "evidence_only": True,
    })

    # 4. Prospect + team combo note (both filters)
    if mikel_id is not None and sas_id is not None:
        notes.append({
            "year": SEED_YEAR,
            "entity_type": "prospect_team",
            "entity_id": f"{mikel_id}_{sas.abbr}",
            "prospect_id": mikel_id,
            "team_id": sas_id,
            "pick_no": None,
            "title": "Mikel Brown Jr. → SAS fit note",
            "body": (
                "Demo seed note: Mikel Brown Jr.'s pick-and-roll feel "
                "complements San Antonio's spacing around Wembanyama. Not "
                "official fit analysis."
            ),
            "summary": "Mikel Brown Jr. to SAS fit observation (dev seed).",
            "source": SEED_SOURCE,
            "author": "dev_seed",
            "source_url": None,
            "source_date": "2026-06-13",
            "confidence": 0.68,
            "tags": "fit,guard_creation,dev_seed",
            "relevance_reason": "Explains the prospect-team fit for this pick.",
            "evidence_only": True,
        })

    # 5. Year-filter note (year=2025, should NOT be retrieved when year=2026)
    if mikel_id is not None:
        notes.append({
            "year": 2025,
            "entity_type": "prospect",
            "entity_id": str(mikel_id),
            "prospect_id": mikel_id,
            "team_id": None,
            "pick_no": None,
            "title": "Mikel Brown Jr. — 2025 legacy note",
            "body": (
                "Demo seed note (2025): legacy observation from a prior "
                "year. Should not appear in 2026 retrieval. Not official."
            ),
            "summary": "2025 legacy note for year-filter verification (dev seed).",
            "source": SEED_SOURCE,
            "author": "dev_seed",
            "source_url": None,
            "source_date": "2025-11-01",
            "confidence": 0.5,
            "tags": "legacy,year_filter,dev_seed",
            "relevance_reason": "Verifies that year filtering excludes old notes.",
            "evidence_only": True,
        })

    # 6. Another prospect note (different prospect)
    if braylon_id is not None:
        notes.append({
            "year": SEED_YEAR,
            "entity_type": "prospect",
            "entity_id": str(braylon_id),
            "prospect_id": braylon_id,
            "team_id": None,
            "pick_no": None,
            "title": "Braylon Mullins — movement shooting note",
            "body": (
                "Demo seed note: Braylon Mullins projects as a movement "
                "shooter with quick trigger and off-ball gravity. Not "
                "official scouting."
            ),
            "summary": "Movement shooting observation (dev seed).",
            "source": SEED_SOURCE,
            "author": "dev_seed",
            "source_url": None,
            "source_date": "2026-06-14",
            "confidence": 0.72,
            "tags": "shooting,movement,dev_seed",
            "relevance_reason": "Explains spacing value for a shooting guard.",
            "evidence_only": True,
        })

    return notes


def _dedup_key(note: dict[str, Any]) -> tuple:
    """Stable dedup key for a demo note payload.

    Two runs of the seed script should never produce duplicate rows.
    The key combines source, title, year, entity_type, entity_id,
    prospect_id, team_id, and pick_no — enough to uniquely identify
    each demo note without relying on auto-increment IDs.
    """
    return (
        note["source"],
        note["title"],
        note["year"],
        note["entity_type"],
        note.get("entity_id"),
        note.get("prospect_id"),
        note.get("team_id"),
        note.get("pick_no"),
    )


def seed_manual_notes(db: Session) -> dict[str, int]:
    """Seed demo ManualNoteRecord rows into the database.

    Non-destructive:
    - Skips demo notes that already exist (by dedup key).
    - Never deletes or overwrites existing rows.
    - Only inserts rows with ``source="manual_seed"``.

    Returns a dict with ``created_count``, ``skipped_count``, and
    ``total_seed_notes`` (the total number of manual_seed rows after
    the run, including pre-existing ones).
    """
    sas = db.query(Team).filter(Team.abbr == "SAS").first()
    hou = db.query(Team).filter(Team.abbr == "HOU").first()
    mikel = db.query(Prospect).filter(Prospect.name == "Mikel Brown Jr.").first()
    braylon = db.query(Prospect).filter(Prospect.name == "Braylon Mullins").first()

    demo_notes = _build_demo_notes(sas, hou, mikel, braylon)

    # Build a set of existing dedup keys for manual_seed rows only.
    # We intentionally do NOT look at non-manual_seed rows — those are
    # custom notes that must never be touched.
    existing_keys: set[tuple] = set()
    existing_seed_rows = db.query(ManualNoteRecord).filter(
        ManualNoteRecord.source == SEED_SOURCE
    ).all()
    for row in existing_seed_rows:
        existing_keys.add((
            row.source,
            row.title,
            row.year,
            row.entity_type,
            row.entity_id,
            row.prospect_id,
            row.team_id,
            row.pick_no,
        ))

    created_count = 0
    skipped_count = 0

    for note_data in demo_notes:
        key = _dedup_key(note_data)
        if key in existing_keys:
            skipped_count += 1
            continue
        db.add(ManualNoteRecord(**note_data))
        existing_keys.add(key)
        created_count += 1

    if created_count > 0:
        db.commit()

    total_seed_notes = (
        db.query(ManualNoteRecord)
        .filter(ManualNoteRecord.source == SEED_SOURCE)
        .count()
    )

    return {
        "created_count": created_count,
        "skipped_count": skipped_count,
        "total_seed_notes": total_seed_notes,
    }


def _print_instructions(result: dict[str, int]) -> None:
    """Print CLI-friendly summary and local verification instructions."""
    print("=" * 60)
    print("ManualNote dev-only seed complete.")
    print(f"  created_count:    {result['created_count']}")
    print(f"  skipped_count:    {result['skipped_count']}")
    print(f"  total_seed_notes: {result['total_seed_notes']}")
    print("=" * 60)
    print()
    print("To verify persisted retrieval locally:")
    print("  1. Set in .env or environment:")
    print("     EVIDENCE_RETRIEVE_MANUAL_NOTES=True")
    print("  2. Restart the API:")
    print("     uvicorn app.main:app --reload")
    print("  3. Call POST /api/evidence/pick with a simulation/pick")
    print("     and check retrieved_evidence for manual_note entries.")
    print()
    print("Note: This script does NOT modify .env or open the flag.")
    print("      The flag must be enabled manually.")


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        result = seed_manual_notes(db)
    _print_instructions(result)
