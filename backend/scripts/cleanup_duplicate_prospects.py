"""Safe, opt-in cleanup for duplicate prospect rows.

The B0-J preflight found that the 2026 pool contained duplicate prospect rows
created by source-name drift -- most notably ``Darius Acuff Jr.`` (id=12, the
canonical seeded row with a projection) and ``Darius Acuff`` (id=41, a
duplicate created by the NBA.com scrape, with NO projection).  Both were
eligible for selection, so the same player was effectively drafted twice
(#8 and #29).

This script merges such duplicate groups down to a single canonical row.  It
is **opt-in and dry-run by default**: running it with no flags only prints
what it would do.  Pass ``--apply`` to actually commit the merge.

Merge policy (per normalized-name group with >1 row):

  * The **canonical row** is the one with a ProspectDraftProjection; if
    several have projections, the one with the highest source priority
    (manual_projection > seed_projection > consensus_reference) wins; ties
    broken by lowest prospect id (most senior row).
  * If no row has a projection, the lowest-id row is canonical (it is the
    one most likely to be referenced by other seed data).
  * Duplicate rows are deleted.  Their ProspectDraftProjection /
    TeamPickProjection / ScoutingReport / ProspectScoutingProfile rows
    (if any) are NOT moved -- by definition the canonical row already
    carries the projection we want to keep, and a duplicate that somehow
    has its own projection / scouting data is printed as a warning for
    manual review rather than silently merged.

The script NEVER touches the .db file on disk directly and NEVER commits
unless ``--apply`` is passed.  It is safe to re-run.

Usage::

    cd D:\\DraftMind\\backend
    # Dry run (default):
    D:\\anaconda\\python.exe scripts\\cleanup_duplicate_prospects.py
    # Actually apply:
    D:\\anaconda\\python.exe scripts\\cleanup_duplicate_prospects.py --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Prospect,
    ProspectDraftProjection,
    ProspectScoutingProfile,
    ScoutingReport,
    TeamPickProjection,
)
from app.utils.nameutils import find_duplicate_name_groups  # noqa: E402

# Mirrors simulation_service.PROJECTION_SOURCE_PRIORITY but kept local so the
# cleanup script has no dependency on the simulation service.
_SOURCE_PRIORITY = {
    "manual_projection": 0,
    "seed_projection": 1,
    "consensus_reference": 2,
}


def _pick_canonical(
    group: list[Prospect],
    projection_by_pid: dict[int, ProspectDraftProjection],
) -> Prospect:
    """Choose the canonical row for a duplicate group.

    Priority: has-projection > projection-source-priority > lowest id.
    """
    with_proj = [p for p in group if p.id in projection_by_pid]
    if with_proj:
        return min(
            with_proj,
            key=lambda p: (
                _SOURCE_PRIORITY.get(
                    projection_by_pid[p.id].source, 99
                ),
                p.id,
            ),
        )
    return min(group, key=lambda p: p.id)


def plan_cleanup(db) -> list[dict]:
    """Return the list of planned merge actions (no DB writes).

    Each action records, for the row we plan to delete, whether it has any
    of the four dependency types that would lose data on deletion:
    ProspectDraftProjection, TeamPickProjection, ScoutingReport,
    ProspectScoutingProfile.  Any such dependency blocks auto-apply (the
    action is tagged with a specific ``warning`` for manual review).
    """
    all_prospects = list(db.scalars(select(Prospect).where(Prospect.year == 2026)))
    projections = list(
        db.scalars(select(ProspectDraftProjection).where(ProspectDraftProjection.year == 2026))
    )
    proj_by_pid = {p.prospect_id: p for p in projections}

    # Pre-compute the full set of prospect_ids that each dependency type
    # references, so per-row checks are O(1) set lookups.
    projection_pids = {p.prospect_id for p in projections}
    team_projection_pids = set(
        db.scalars(
            select(TeamPickProjection.prospect_id).where(
                TeamPickProjection.year == 2026
            )
        )
    )
    scouting_report_pids = set(
        db.scalars(select(ScoutingReport.prospect_id))
    )
    scouting_profile_pids = set(
        db.scalars(
            select(ProspectScoutingProfile.prospect_id).where(
                ProspectScoutingProfile.year == 2026
            )
        )
    )

    name_groups = find_duplicate_name_groups(p.name for p in all_prospects)
    # Map each display name back to its rows (a display name could in theory
    # appear twice, though that would itself be a duplicate).
    by_display: dict[str, list[Prospect]] = {}
    for p in all_prospects:
        by_display.setdefault(p.name, []).append(p)

    actions: list[dict] = []
    for norm_key, display_names in sorted(name_groups.items()):
        members: list[Prospect] = []
        for display in display_names:
            members.extend(by_display.get(display, []))
        if len(members) < 2:
            continue
        canonical = _pick_canonical(members, proj_by_pid)
        for m in members:
            if m.id == canonical.id:
                continue
            has_proj = m.id in projection_pids
            has_tpp = m.id in team_projection_pids
            has_report = m.id in scouting_report_pids
            has_profile = m.id in scouting_profile_pids
            action = {
                "normalized": norm_key,
                "keep_id": canonical.id,
                "keep_name": canonical.name,
                "delete_id": m.id,
                "delete_name": m.name,
                "delete_has_projection": has_proj,
                "delete_has_team_projection": has_tpp,
                "delete_has_scouting_report": has_report,
                "delete_has_scouting_profile": has_profile,
                "warning": None,
            }
            # If the row we are about to delete carries ANY dependency, flag
            # it with a specific reason instead of silently dropping data.
            # The first hit wins for the warning text; all flags stay on the
            # action dict so callers/tests can inspect the full picture.
            deps: list[tuple[bool, str]] = [
                (has_proj, "ProspectDraftProjection"),
                (has_tpp, "TeamPickProjection"),
                (has_report, "ScoutingReport"),
                (has_profile, "ProspectScoutingProfile"),
            ]
            blocking = [label for flag, label in deps if flag]
            if blocking:
                action["warning"] = (
                    f"duplicate row has {'+'.join(blocking)}; "
                    "review manually before applying"
                )
            actions.append(action)
    return actions


def apply_cleanup(db, safe_actions: list[dict]) -> int:
    """Commit the deletion of duplicate rows for ``safe_actions``.

    ``safe_actions`` must already be the warning-filtered subset (the caller
    is responsible for excluding any action whose ``warning`` is set).
    Inside the transaction we re-check every ``delete_id`` against all four
    dependency types -- ProspectDraftProjection, TeamPickProjection,
    ScoutingReport, ProspectScoutingProfile -- and refuse (raising
    ``RuntimeError``) if any linkage appeared since planning.  The caller
    has not committed yet in that case.

    Returns the number of rows deleted.  Commits the transaction.
    """
    if not safe_actions:
        return 0

    to_delete_ids = [a["delete_id"] for a in safe_actions]

    # Defensive in-transaction re-check: refuse to delete any row that still
    # has ANY of the four dependency types attached.  This catches the case
    # where data changed between plan_cleanup() and apply_cleanup() (e.g.
    # another importer added a scouting report to the duplicate).
    protected: dict[int, str] = {}
    for model, label in (
        (ProspectDraftProjection, "ProspectDraftProjection"),
        (TeamPickProjection, "TeamPickProjection"),
        (ScoutingReport, "ScoutingReport"),
        (ProspectScoutingProfile, "ProspectScoutingProfile"),
    ):
        # db.scalars() already returns scalar values (the prospect_id), so
        # we iterate directly -- no tuple unpacking.
        for pid in db.scalars(
            select(model.prospect_id).where(
                model.prospect_id.in_(to_delete_ids)
            )
        ):
            pid = int(pid)
            # Accumulate all dependency labels per pid so the error message
            # names every offending linkage, not just the first found.
            protected.setdefault(pid, label)
            if label not in protected[pid]:
                protected[pid] = f"{protected[pid]}+{label}"

    if protected:
        offenders = ", ".join(
            f"id={pid} ({protected[pid]})" for pid in sorted(protected)
        )
        raise RuntimeError(
            "refusing to delete protected duplicate row(s): "
            f"{offenders}; row(s) gained dependency linkage since "
            "planning. Re-run plan_cleanup."
        )

    deleted = (
        db.query(Prospect)
        .filter(Prospect.id.in_(to_delete_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually commit the merge (default is dry-run)",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        actions = plan_cleanup(db)
        if not actions:
            print("No duplicate prospect groups found. Nothing to do.")
            return

        mode = "APPLY" if args.apply else "DRY-RUN"
        print(f"=== cleanup_duplicate_prospects ({mode}) ===")
        for a in actions:
            tag = "  [WARN] " if a["warning"] else "  "
            print(f"{tag}normalized={a['normalized']!r}: "
                  f"keep id={a['keep_id']} ({a['keep_name']}), "
                  f"delete id={a['delete_id']} ({a['delete_name']})")
            if a["warning"]:
                print(f"         ! {a['warning']}")

        # Filter out actions that carry a warning -- those need manual review
        # and are never auto-applied even with --apply.
        safe_actions = [a for a in actions if not a["warning"]]
        skipped = [a for a in actions if a["warning"]]
        if skipped:
            print(f"\n{len(skipped)} action(s) skipped (need manual review).")

        if not args.apply:
            print(f"\nDRY-RUN: would delete {len(safe_actions)} duplicate row(s). "
                  "Re-run with --apply to commit.")
            return

        if not safe_actions:
            print("\nNo safe auto-merge actions; nothing committed.")
            return

        deleted = apply_cleanup(db, safe_actions)
        print(f"\nAPPLY: deleted {deleted} duplicate row(s).")


if __name__ == "__main__":
    main()
