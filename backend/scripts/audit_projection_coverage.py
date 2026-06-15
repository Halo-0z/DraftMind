"""Read-only data-quality audit for the 2026 prospect pool.

Reports three classes of problems found by the B0-J preflight:

  1. High-upside prospects with NO ProspectDraftProjection (these get selected
     on raw ranking_engine score alone and can crowd out market-top-20
     prospects that DO have projections).
  2. Duplicate / near-duplicate prospect names (Jr./Sr./punctuation/case
     variants of the same player) detected via normalized_name().
  3. Prospects that share an identical stats fingerprint (ppg/rpg/apg/fg/3pt/
     ft/stocks) -- a signal of seed/import template copying.

The script never mutates the database.  Run it from the backend directory so
that ``sqlite:///./draftmind.db`` resolves to the live DB the server uses::

    cd D:\\DraftMind\\backend
    D:\\anaconda\\python.exe scripts\\audit_projection_coverage.py

Options:
    --min-upside FLOAT   threshold for the "high-upside no projection" report
                         (default 76.0, the cutoff where a prospect starts
                         competing for #11-20 on raw score alone)
    --top-selected INT   also list prospects with no projection that were
                         selected in the first N picks of a recent 60-pick
                         simulation (default 30; set 0 to disable)
    --json               emit machine-readable JSON instead of human text
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Prospect, ProspectDraftProjection  # noqa: E402
from app.utils.nameutils import find_duplicate_name_groups  # noqa: E402


# Stats fields that together form a "fingerprint".  Two prospects sharing all
# seven values is a strong signal of seed/import template copying (the
# NBA.com importer derives these from position alone, so any two guards
# imported with the same board_index bucket can collide).
STATS_FIELDS = ("ppg", "rpg", "apg", "fg_pct", "three_pct", "ft_pct", "stocks")


@dataclass
class AuditReport:
    high_upside_no_projection: list[dict[str, Any]] = field(default_factory=list)
    selected_top_n_no_projection: list[dict[str, Any]] = field(default_factory=list)
    duplicate_name_groups: list[dict[str, Any]] = field(default_factory=list)
    duplicate_stats_groups: list[dict[str, Any]] = field(default_factory=list)
    totals: dict[str, int] = field(default_factory=dict)


def _prospect_brief(p: Prospect) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "position": p.position,
        "school_or_league": p.school_or_league,
        "upside_score": p.upside_score,
        "risk_score": p.risk_score,
        "archetype": p.archetype,
        # B0-K1: surface stats provenance so an operator can tell, at a
        # glance, whether a high-upside-no-projection pick or a duplicate
        # stats group is driven by hand-curated seed data or by the NBA.com
        # importer's heuristic baseline.  Legacy rows read as "unknown".
        "stats_source": p.stats_source or "unknown",
        "stats_confidence": p.stats_confidence,
    }


def _stats_fingerprint(p: Prospect) -> tuple:
    return tuple(getattr(p, f) for f in STATS_FIELDS)


def build_report(
    db,
    *,
    min_upside: float,
    top_n: int,
) -> AuditReport:
    report = AuditReport()

    all_prospects = list(db.scalars(select(Prospect).where(Prospect.year == 2026)))
    pids_with_proj = set(
        db.scalars(
            select(ProspectDraftProjection.prospect_id).where(
                ProspectDraftProjection.year == 2026
            )
        )
    )

    report.totals = {
        "prospects": len(all_prospects),
        "with_projection": len(pids_with_proj),
        "without_projection": len(all_prospects) - len(pids_with_proj),
    }

    # 1. high-upside no-projection
    for p in sorted(
        (p for p in all_prospects if p.id not in pids_with_proj),
        key=lambda x: x.upside_score or 0.0,
        reverse=True,
    ):
        if (p.upside_score or 0.0) >= min_upside:
            report.high_upside_no_projection.append(_prospect_brief(p))

    # 2. duplicate name groups
    name_groups = find_duplicate_name_groups(p.name for p in all_prospects)
    # Attach ids/positions to each duplicate group for actionable output.
    by_display = defaultdict(list)
    for p in all_prospects:
        by_display[p.name].append(p)
    for norm_key, display_names in sorted(name_groups.items()):
        members: list[dict[str, Any]] = []
        for display in display_names:
            for p in by_display.get(display, []):
                entry = _prospect_brief(p)
                entry["has_projection"] = p.id in pids_with_proj
                members.append(entry)
        report.duplicate_name_groups.append(
            {"normalized": norm_key, "members": members}
        )

    # 3. duplicate stats fingerprints (only groups with >1 distinct prospect)
    by_fp: dict[tuple, list[Prospect]] = defaultdict(list)
    for p in all_prospects:
        by_fp[_stats_fingerprint(p)].append(p)
    for fp, group in by_fp.items():
        if len(group) < 2:
            continue
        report.duplicate_stats_groups.append(
            {
                "stats": dict(zip(STATS_FIELDS, fp)),
                "members": [_prospect_brief(p) for p in group],
            }
        )

    # 4. (optional) prospects selected in the first `top_n` picks of a sim
    #     that had no projection.  We import lazily so the audit does not
    #     require the simulation service to be runnable.
    if top_n > 0:
        try:
            from app.schemas.simulation import SimulateRequest
            from app.services.simulation_service import simulate_draft

            req = SimulateRequest(
                year=2026,
                rounds=2,
                limit=60,
                use_prediction_calibration=True,
                include_prediction_shadow=True,
                include_projection_diagnostics=True,
            )
            resp = simulate_draft(db, req)
            for pick in resp.picks[:top_n]:
                sp = pick.selected_player
                if sp.prospect.id not in pids_with_proj:
                    # B0-K1a: sp.prospect is a pydantic schema object that
                    # does NOT carry stats_source / stats_confidence (those
                    # are ORM-only fields).  Re-query the ORM Prospect by id
                    # so the audit reports the real provenance the operator
                    # sees in the high-upside section.  Fall back to the
                    # schema object (-> "unknown") if the row is somehow gone.
                    orm_prospect = db.get(Prospect, sp.prospect.id)
                    brief = (
                        _prospect_brief(orm_prospect)
                        if orm_prospect is not None
                        else _prospect_brief_obj(sp.prospect)
                    )
                    report.selected_top_n_no_projection.append(
                        {
                            **brief,
                            "selected_pick": pick.pick,
                            "team_abbr": pick.team.abbr,
                            "final_score": sp.scores.final_score,
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            # Simulation is best-effort here; never fail the audit because
            # of it.
            report.selected_top_n_no_projection.append(
                {"error": f"simulation skipped: {exc!s}"}
            )

    return report


def _prospect_brief_obj(prospect) -> dict[str, Any]:
    return {
        "id": prospect.id,
        "name": prospect.name,
        "position": prospect.position,
        "school_or_league": prospect.school_or_league,
        "upside_score": prospect.upside_score,
        "risk_score": prospect.risk_score,
        "archetype": prospect.archetype,
        # B0-K1: mirror _prospect_brief so the selected-top-N section also
        # reports stats provenance.
        "stats_source": getattr(prospect, "stats_source", None) or "unknown",
        "stats_confidence": getattr(prospect, "stats_confidence", None),
    }


def _print_human(report: AuditReport, *, min_upside: float, top_n: int) -> None:
    t = report.totals
    print("=" * 78)
    print("PROJECTION COVERAGE AUDIT (2026)")
    print("=" * 78)
    print(
        f"prospects: {t['prospects']}  "
        f"with_projection: {t['with_projection']}  "
        f"without_projection: {t['without_projection']}"
    )

    print("\n--- high-upside prospects with NO projection "
          f"(upside >= {min_upside}) ---")
    if not report.high_upside_no_projection:
        print("  (none)")
    for e in report.high_upside_no_projection:
        print(f"  id={e['id']:>3} upside={e['upside_score']:5.1f} "
              f"{e['name']:<26} {e['position']} {e['school_or_league']} "
              f"[stats={e['stats_source']}]")

    print("\n--- duplicate / near-duplicate prospect names ---")
    if not report.duplicate_name_groups:
        print("  (none)")
    for g in report.duplicate_name_groups:
        print(f"  normalized = {g['normalized']!r}")
        for m in g["members"]:
            proj = "proj" if m["has_projection"] else "NO-proj"
            print(f"    id={m['id']:>3} {m['name']:<28} {m['position']} "
                  f"upside={m['upside_score']} [{proj}] "
                  f"[stats={m['stats_source']}]")

    print("\n--- duplicate stats fingerprints (template-copy candidates) ---")
    if not report.duplicate_stats_groups:
        print("  (none)")
    for g in report.duplicate_stats_groups:
        s = g["stats"]
        print(f"  ppg={s['ppg']} rpg={s['rpg']} apg={s['apg']} "
              f"fg={s['fg_pct']} 3pt={s['three_pct']} ft={s['ft_pct']} "
              f"stocks={s['stocks']}")
        for m in g["members"]:
            print(f"    id={m['id']:>3} {m['name']:<26} {m['position']} "
                  f"{m['school_or_league']} [stats={m['stats_source']}]")

    if top_n > 0:
        print(f"\n--- prospects selected in first {top_n} picks with NO projection ---")
        if not report.selected_top_n_no_projection:
            print("  (none)")
        for e in report.selected_top_n_no_projection:
            if "error" in e:
                print(f"  {e['error']}")
            else:
                print(f"  #{e['selected_pick']:>2} {e['team_abbr']:<4} "
                      f"id={e['id']:>3} {e['name']:<26} "
                      f"final={e['final_score']} [stats={e['stats_source']}]")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-upside", type=float, default=76.0)
    parser.add_argument("--top-selected", type=int, default=30)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    with SessionLocal() as db:
        report = build_report(
            db, min_upside=args.min_upside, top_n=args.top_selected,
        )

    if args.as_json:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        _print_human(report, min_upside=args.min_upside, top_n=args.top_selected)


if __name__ == "__main__":
    main()
