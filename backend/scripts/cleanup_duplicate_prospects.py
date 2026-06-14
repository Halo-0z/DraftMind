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

By default a duplicate carrying a ScoutingReport is blocked (the report is
not silently dropped).  Pass ``--migrate-scouting-reports`` to allow the
report rows to be reassigned to the canonical prospect before the duplicate
is deleted; this only fires for rows whose sole dependency is
ScoutingReport, and only when combined with ``--apply``.  The three "hard"
dependencies (ProspectDraftProjection, TeamPickProjection,
ProspectScoutingProfile) always block.

Usage::

    cd D:\\DraftMind\\backend
    # Dry run (default):
    D:\\anaconda\\python.exe scripts\\cleanup_duplicate_prospects.py
    # Dry run with migration planning:
    D:\\anaconda\\python.exe scripts\\cleanup_duplicate_prospects.py \\
        --migrate-scouting-reports
    # Actually apply (plain deletion of dependency-free duplicates):
    D:\\anaconda\\python.exe scripts\\cleanup_duplicate_prospects.py --apply
    # Actually apply with ScoutingReport migration:
    D:\\anaconda\\python.exe scripts\\cleanup_duplicate_prospects.py \\
        --apply --migrate-scouting-reports
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

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


def plan_cleanup(db, *, migrate_scouting_reports: bool = False) -> list[dict]:
    """Return the list of planned merge actions (no DB writes).

    Each action records, for the row we plan to delete, whether it has any
    of the four dependency types that would lose data on deletion:
    ProspectDraftProjection, TeamPickProjection, ScoutingReport,
    ProspectScoutingProfile.  Any such dependency blocks auto-apply (the
    action is tagged with a specific ``warning`` for manual review).

    When ``migrate_scouting_reports`` is True, a duplicate row whose *only*
    dependency is ScoutingReport becomes eligible for an explicit migration:
    the action's ``warning`` is cleared and ``migrate_scouting_reports`` is
    set to True on the action, signalling that apply_cleanup may reassign
    those ScoutingReport rows to the canonical prospect before deleting the
    duplicate.  Any other dependency combination still blocks.
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
                # Whether apply_cleanup is allowed to migrate the
                # ScoutingReport rows from delete_id -> keep_id.  Only set
                # True in migrate mode AND when ScoutingReport is the sole
                # dependency.
                "migrate_scouting_reports": False,
                "warning": None,
            }
            # Dependency evaluation.  The three "hard" dependencies
            # (projection, team-pick, scouting-profile) always block.  A
            # lone ScoutingReport blocks in default mode but is migratable
            # in migrate mode.
            hard_blocking: list[str] = []
            if has_proj:
                hard_blocking.append("ProspectDraftProjection")
            if has_tpp:
                hard_blocking.append("TeamPickProjection")
            if has_profile:
                hard_blocking.append("ProspectScoutingProfile")

            migratable = (
                migrate_scouting_reports
                and has_report
                and not hard_blocking
            )

            if migratable:
                # Eligible for explicit migration: clear the warning so the
                # action is auto-applicable (under --apply --migrate).
                action["migrate_scouting_reports"] = True
            else:
                # Build the warning from every blocking dependency, including
                # ScoutingReport when not migratable.
                blocking = list(hard_blocking)
                if has_report:
                    blocking.append("ScoutingReport")
                if blocking:
                    action["warning"] = (
                        f"duplicate row has {'+'.join(blocking)}; "
                        "review manually before applying"
                    )
            actions.append(action)
    return actions


def apply_cleanup(
    db,
    safe_actions: list[dict],
    *,
    migrate_scouting_reports: bool = False,
) -> int:
    """Commit the deletion of duplicate rows for ``safe_actions``.

    ``safe_actions`` must already be the warning-filtered subset (the caller
    is responsible for excluding any action whose ``warning`` is set).

    Dependency handling inside the transaction:

      * ProspectDraftProjection, TeamPickProjection, ProspectScoutingProfile
        ALWAYS block deletion (raise ``RuntimeError``), regardless of flags.
        These dependencies carry irreplaceable model data and must never be
        silently dropped or reassigned by this script.
      * ScoutingReport blocks deletion in the default path.  When the caller
        passes ``migrate_scouting_reports=True`` AND an action is marked
        ``migrate_scouting_reports`` (i.e. ScoutingReport is the row's sole
        dependency), the report rows are reassigned from ``delete_id`` to
        ``keep_id`` before the duplicate Prospect row is deleted.  No
        ScoutingReport row is ever dropped -- it is either moved or the
        deletion is refused.

    Returns the number of Prospect rows deleted.  Commits the transaction.
    """
    if not safe_actions:
        return 0

    to_delete_ids = [a["delete_id"] for a in safe_actions]

    # Defensive in-transaction re-check.  The three "hard" dependencies are
    # unconditional blockers.  ScoutingReport is a blocker unless this call
    # is in migrate mode AND the specific action opted into migration.
    hard_models: list[tuple[Any, str]] = [
        (ProspectDraftProjection, "ProspectDraftProjection"),
        (TeamPickProjection, "TeamPickProjection"),
        (ProspectScoutingProfile, "ProspectScoutingProfile"),
    ]
    protected: dict[int, str] = {}
    for model, label in hard_models:
        for pid in db.scalars(
            select(model.prospect_id).where(
                model.prospect_id.in_(to_delete_ids)
            )
        ):
            pid = int(pid)
            protected.setdefault(pid, label)
            if label not in protected[pid]:
                protected[pid] = f"{protected[pid]}+{label}"

    # ScoutingReport: block per-row unless that specific action opted in to
    # migration AND we are in migrate mode.
    migrate_ids = {
        a["delete_id"]
        for a in safe_actions
        if migrate_scouting_reports and a.get("migrate_scouting_reports")
    }
    for pid in db.scalars(
        select(ScoutingReport.prospect_id).where(
            ScoutingReport.prospect_id.in_(to_delete_ids)
        )
    ):
        pid = int(pid)
        if pid in migrate_ids:
            continue  # handled by the migration step below
        protected.setdefault(pid, "ScoutingReport")
        if "ScoutingReport" not in protected[pid]:
            protected[pid] = f"{protected[pid]}+ScoutingReport"

    if protected:
        offenders = ", ".join(
            f"id={pid} ({protected[pid]})" for pid in sorted(protected)
        )
        raise RuntimeError(
            "refusing to delete protected duplicate row(s): "
            f"{offenders}; row(s) gained dependency linkage since "
            "planning. Re-run plan_cleanup."
        )

    # Migrate ScoutingReport rows for the opt-in actions.  Reassign
    # prospect_id from delete_id -> keep_id; never delete a report.  If the
    # canonical row already has ScoutingReports, the migrated rows simply
    # coexist (ScoutingReport has no uniqueness constraint on
    # (prospect_id, source), so this is safe and loses nothing).
    migrated_reports = 0
    for a in safe_actions:
        if not (migrate_scouting_reports and a.get("migrate_scouting_reports")):
            continue
        delete_id = a["delete_id"]
        keep_id = a["keep_id"]
        reports = list(
            db.scalars(
                select(ScoutingReport).where(
                    ScoutingReport.prospect_id == delete_id
                )
            )
        )
        for report in reports:
            report.prospect_id = keep_id
            migrated_reports += 1

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
    parser.add_argument(
        "--migrate-scouting-reports",
        action="store_true",
        dest="migrate_scouting_reports",
        help=(
            "allow a duplicate row whose ONLY dependency is ScoutingReport "
            "to have its report rows reassigned to the canonical prospect "
            "before deletion.  Default is off (such rows are blocked).  "
            "Has no effect unless --apply is also passed."
        ),
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        actions = plan_cleanup(
            db, migrate_scouting_reports=args.migrate_scouting_reports
        )
        if not actions:
            print("No duplicate prospect groups found. Nothing to do.")
            return

        mode = "APPLY" if args.apply else "DRY-RUN"
        if args.migrate_scouting_reports:
            mode += " +MIGRATE-SCOUTING-REPORTS"
        print(f"=== cleanup_duplicate_prospects ({mode}) ===")
        for a in actions:
            if a.get("migrate_scouting_reports"):
                tag = "  [MIGRATE]"
            elif a["warning"]:
                tag = "  [WARN]  "
            else:
                tag = "  "
            print(f"{tag} normalized={a['normalized']!r}: "
                  f"keep id={a['keep_id']} ({a['keep_name']}), "
                  f"delete id={a['delete_id']} ({a['delete_name']})")
            if a.get("migrate_scouting_reports"):
                # Count the ScoutingReport rows that would move, for an
                # actionable dry-run message.
                report_total = (
                    db.query(ScoutingReport)
                    .filter(ScoutingReport.prospect_id == a["delete_id"])
                    .count()
                )
                print(
                    f"           would move {report_total} ScoutingReport "
                    f"row(s) from {a['delete_id']} -> {a['keep_id']} "
                    f"({a['keep_name']})"
                )
                print(f"           would delete duplicate prospect id={a['delete_id']}")
            elif a["warning"]:
                print(f"           ! {a['warning']}")

        # "safe" = auto-applicable actions: either no warning at all, or a
        # migration-opted action (warning cleared by plan_cleanup).
        safe_actions = [a for a in actions if not a["warning"]]
        skipped = [a for a in actions if a["warning"]]
        if skipped:
            print(f"\n{len(skipped)} action(s) skipped (need manual review).")

        if not args.apply:
            print(
                f"\nDRY-RUN: would delete {len(safe_actions)} duplicate "
                "row(s)."
            )
            if args.migrate_scouting_reports and any(
                a.get("migrate_scouting_reports") for a in safe_actions
            ):
                print(
                    "Re-run with --apply --migrate-scouting-reports to "
                    "commit."
                )
            else:
                print("Re-run with --apply to commit.")
            return

        if not safe_actions:
            print("\nNo safe auto-merge actions; nothing committed.")
            return

        deleted = apply_cleanup(
            db,
            safe_actions,
            migrate_scouting_reports=args.migrate_scouting_reports,
        )
        print(f"\nAPPLY: deleted {deleted} duplicate row(s).")


if __name__ == "__main__":
    main()
