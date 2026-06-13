from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import delete

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, SessionLocal, engine
from app.models import ProspectDraftProjection, TeamPickProjection
from scripts.import_projection_board import (
    import_prospect_projection_csv,
    import_team_pick_projection_csv,
)


DATA_DIR = ROOT / "data" / "projections"
PROSPECT_CSV = DATA_DIR / "2026_consensus_projection_board.csv"
TEAM_PICK_CSV = DATA_DIR / "2026_team_pick_projection_signals.csv"
DEMO_PROSPECT_NOTE = "Demo seed projection signal for DraftMind development; not official."
DEMO_TEAM_PICK_NOTE = "Demo seed team-pick projection signal; not official."


def remove_stale_demo_projection_rows(db) -> tuple[int, int]:
    prospect_result = db.execute(
        delete(ProspectDraftProjection).where(
            ProspectDraftProjection.year == 2026,
            ProspectDraftProjection.source == "seed_projection",
            ProspectDraftProjection.notes == DEMO_PROSPECT_NOTE,
        )
    )
    team_result = db.execute(
        delete(TeamPickProjection).where(
            TeamPickProjection.year == 2026,
            TeamPickProjection.source == "seed_projection",
            TeamPickProjection.notes == DEMO_TEAM_PICK_NOTE,
        )
    )
    return prospect_result.rowcount or 0, team_result.rowcount or 0


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        removed_prospects, removed_team_picks = remove_stale_demo_projection_rows(db)
        prospect_summary = import_prospect_projection_csv(db, PROSPECT_CSV)
        team_summary = import_team_pick_projection_csv(db, TEAM_PICK_CSV)
        db.commit()

    print(
        "removed stale demo projection rows: "
        f"prospect={removed_prospects}, team_pick={removed_team_picks}"
    )
    print(f"prospect projections: {prospect_summary}")
    print(f"team pick projections: {team_summary}")


if __name__ == "__main__":
    main()
