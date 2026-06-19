from __future__ import annotations

from pathlib import Path
import json
import re
import sys
from typing import Any

import requests
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, SessionLocal, engine
from app.models import Prospect, ScoutingReport
from app.utils.nameutils import normalized_name


URL = "https://www.nba.com/draft/2026/prospects"
SOURCE = "NBA.com 2026 Draft Prospects"

# B0-K1: stats provenance for importer-created prospects.  estimate_stats()
# produces position-baseline heuristic values (not real stats), so we tag
# them low-confidence.  These are written on every importer create/update
# UNLESS the matched row is already ``seed_manual`` (hand-curated), in which
# case the seed provenance is preserved (see _apply_importer_stats_provenance).
STATS_SOURCE = "nba_importer_heuristic"
STATS_CONFIDENCE = 0.30


# Curated prospect overrides.
#
# Hand-curated stats/position/archetype for prospects whose NBA.com heuristic
# estimates are known to be inaccurate.  Applied after build_prospect() and
# update_bio() so the curated values always win, even on subsequent importer
# runs.
#
# Keys are (name, year) tuples.  Values are dicts of field -> value.
# Only the fields listed in each entry are overwritten; all other prospect
# fields (age, risk_score, height, weight, school_or_league) are left
# untouched.  upside_score may be overridden per-entry when the heuristic
# value is known to be wrong (see Brayden Burries below).
#
# M4-P: Yaxel Lendeborg's NBA.com heuristic stats were SF-position template
# values (ppg=12.1, rpg=5.9, apg=2.4, three_pct=33.5, ...), not real stats.
# Source-scout verified values (M4-N) are curated here so the importer can
# never regress them back to template estimates.
#
# M4-W: Brayden Burries's NBA.com heuristic stats were PG/SG-position
# template values (ppg=13.0, rpg=3.4, apg=4.2, stocks=1.2, fg=44.5,
# three=35.5, ft=77.5), not real stats.  Source-scout verified values
# (M4-T) are curated here.  upside_score is also lifted from 72.6 to 78.0
# (M4-V S4 sweet spot) so Brayden lands in his projected range 8-13
# instead of being skipped in the first round.  risk_score is intentionally
# left at the DB value (36.3) per M4-V conclusion.
CURATED_PROSPECT_OVERRIDES: dict[tuple[str, int], dict[str, Any]] = {
    ("Yaxel Lendeborg", 2026): {
        "position": "PF",
        "archetype": "Connector frontcourt",
        "ppg": 15.1,
        "rpg": 6.8,
        "apg": 3.2,
        "fg_pct": 51.5,
        "three_pct": 37.2,
        "ft_pct": 82.4,
        "stocks": 2.3,
        "stats_source": "seed_manual",
        "stats_confidence": 0.80,
    },
    ("Brayden Burries", 2026): {
        "position": "SG",
        "archetype": "Two-way combo guard",
        "ppg": 16.1,
        "rpg": 4.9,
        "apg": 2.4,
        "fg_pct": 49.1,
        "three_pct": 39.1,
        "ft_pct": 80.5,
        "stocks": 1.7,
        "upside_score": 78.0,
        "stats_source": "seed_manual",
        "stats_confidence": 0.80,
    },
}


def apply_curated_override(prospect: Prospect) -> bool:
    """Apply curated stats override to a prospect if one exists.

    Returns True if an override was applied, False otherwise.
    Only overwrites the fields present in the override dict; never touches
    age, upside_score, risk_score, or projection data.
    """
    key = (prospect.name, prospect.year)
    override = CURATED_PROSPECT_OVERRIDES.get(key)
    if override is None:
        return False
    for field, value in override.items():
        setattr(prospect, field, value)
    return True


def apply_curated_overrides_to_db() -> int:
    """Apply curated overrides to existing DB rows without fetching NBA.com.

    Useful for applying hand-curated fixes without a network round-trip.
    Returns the number of prospects updated.
    """
    with SessionLocal() as db:
        updated = 0
        all_prospects = list(db.scalars(select(Prospect)))
        for prospect in all_prospects:
            if apply_curated_override(prospect):
                updated += 1
        db.commit()
        return updated


def _apply_importer_stats_provenance(prospect: Prospect) -> None:
    """Tag a prospect with importer-heuristic stats provenance.

    Guarded: never downgrades a ``seed_manual`` row.  This is what keeps the
    NBA.com scrape from relabelling a canonical seed prospect (e.g.
    "Darius Acuff Jr." matched via normalized name from NBA.com's
    "Darius Acuff") as heuristic data.
    """
    if prospect.stats_source == "seed_manual":
        return
    prospect.stats_source = STATS_SOURCE
    prospect.stats_confidence = STATS_CONFIDENCE


def main() -> None:
    Base.metadata.create_all(bind=engine)
    prospects = fetch_nba_prospects()

    with SessionLocal() as db:
        imported = 0
        updated = 0
        # Cache the whole 2026 pool once so normalized-name lookups (which
        # would otherwise scan per row) stay cheap.  This is what stops the
        # NBA.com scrape from creating a duplicate when the site lists a
        # player without a "Jr." suffix that the local seed has -- e.g.
        # NBA.com "Darius Acuff" must resolve to the seeded
        # "Darius Acuff Jr." instead of creating a second row.
        all_prospects = list(
            db.scalars(select(Prospect).where(Prospect.year == 2026))
        )
        exact_by_name = {p.name.lower(): p for p in all_prospects}
        norm_index: dict[str, list[Prospect]] = {}
        for p in all_prospects:
            norm_index.setdefault(normalized_name(p.name), []).append(p)

        for board_index, row in enumerate(prospects, start=1):
            name = str(row.get("displayName") or "").strip()
            if not name:
                continue

            existing = exact_by_name.get(name.lower())
            if existing is None:
                # Fall back to normalized-name matching across the existing
                # pool before deciding to create a new row.
                norm_matches = norm_index.get(normalized_name(name), [])
                if len(norm_matches) == 1:
                    existing = norm_matches[0]
                elif len(norm_matches) > 1:
                    # Real duplicate already in the DB -- do not silently
                    # pick one.  Skip with a loud message so the operator
                    # can clean it up via the audit/cleanup scripts.
                    dup_names = ", ".join(sorted(p.name for p in norm_matches))
                    print(
                        f"SKIP {name!r}: {len(norm_matches)} existing prospects "
                        f"share normalized name ({dup_names}); resolve the "
                        f"duplicate first."
                    )
                    continue

            if existing is None:
                prospect_obj = build_prospect(row=row, board_index=board_index)
                db.add(prospect_obj)
                db.flush()
                # Keep the in-memory indexes consistent for later rows in
                # the same run.
                exact_by_name[prospect_obj.name.lower()] = prospect_obj
                norm_index.setdefault(
                    normalized_name(prospect_obj.name), []
                ).append(prospect_obj)
                imported += 1
                prospect = prospect_obj
            else:
                update_bio(existing, row)
                updated += 1
                prospect = existing

            # M4-P: apply curated override AFTER build_prospect/update_bio
            # so hand-curated values always win over heuristic estimates.
            apply_curated_override(prospect)

            upsert_report(db, prospect, row)

        db.commit()
        print(
            f"Imported {imported} new prospects and updated {updated} existing prospects "
            f"from NBA.com ({len(prospects)} rows read)."
        )


def fetch_nba_prospects() -> list[dict[str, Any]]:
    response = requests.get(
        URL,
        timeout=25,
        headers={"User-Agent": "Mozilla/5.0 DraftMind/0.1"},
    )
    response.raise_for_status()
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        response.text,
    )
    if match is None:
        raise RuntimeError("Could not find __NEXT_DATA__ on NBA.com prospects page.")

    data = json.loads(match.group(1))
    prospects = data["props"]["pageProps"]["page"]["prospects"]
    if not isinstance(prospects, list):
        raise RuntimeError("Unexpected NBA.com prospects payload shape.")
    return prospects


def build_prospect(row: dict[str, Any], board_index: int) -> Prospect:
    position = normalize_position(row.get("position"))
    estimates = estimate_stats(position=position, row=row, board_index=board_index)
    return Prospect(
        year=2026,
        name=str(row["displayName"]).strip(),
        position=position,
        age=to_float(row.get("age")) or 19.5,
        height=height(row),
        weight=to_int(row.get("weightLbs")) or 200,
        school_or_league=school(row),
        ppg=estimates["ppg"],
        rpg=estimates["rpg"],
        apg=estimates["apg"],
        fg_pct=estimates["fg_pct"],
        three_pct=estimates["three_pct"],
        ft_pct=estimates["ft_pct"],
        stocks=estimates["stocks"],
        archetype=archetype(position=position, row=row),
        upside_score=estimates["upside_score"],
        risk_score=estimates["risk_score"],
        # B0-K1: mark these as heuristic estimates (not real stats).  The
        # constant is defined at module scope and mirrored by audit / ranking
        # tooling to distinguish seed_manual vs importer data.
        stats_source=STATS_SOURCE,
        stats_confidence=STATS_CONFIDENCE,
    )


def update_bio(prospect: Prospect, row: dict[str, Any]) -> None:
    prospect.position = normalize_position(row.get("position"))
    prospect.age = to_float(row.get("age")) or prospect.age
    prospect.height = height(row)
    prospect.weight = to_int(row.get("weightLbs")) or prospect.weight
    prospect.school_or_league = school(row)
    # B0-K1: refresh stats provenance on update, but never downgrade a
    # seed_manual canonical row (e.g. "Darius Acuff Jr." matched from the
    # NBA.com "Darius Acuff" displayName via normalized name).
    _apply_importer_stats_provenance(prospect)


def upsert_report(db, prospect: Prospect, row: dict[str, Any]) -> None:
    profile_link = row.get("profileLink") or URL
    text = (
        f"{prospect.name} is listed by NBA.com as a {row.get('position') or prospect.position} "
        f"from {school(row)}. Bio: {height(row)}, {row.get('weightLbs') or 'unknown'} lbs, "
        f"age {row.get('age') or 'unknown'}, status {row.get('status') or 'unknown'}, "
        f"country {row.get('country') or 'unknown'}. Profile: {profile_link}. "
        "Scoring fields for newly imported prospects are DraftMind heuristic estimates, "
        "not official NBA statistical projections."
    )
    existing = db.scalar(
        select(ScoutingReport).where(
            ScoutingReport.prospect_id == prospect.id,
            ScoutingReport.source == SOURCE,
        )
    )
    if existing is None:
        db.add(
            ScoutingReport(
                prospect_id=prospect.id,
                source=SOURCE,
                report_text=text,
            )
        )
    else:
        existing.report_text = text


def normalize_position(value: Any) -> str:
    position = str(value or "").upper()
    if "C" in position and "F" in position:
        return "C"
    if position == "C":
        return "C"
    if "G" in position and "F" in position:
        return "SF"
    if position == "G":
        return "SG"
    if position == "F":
        return "SF"
    return "SF"


def estimate_stats(position: str, row: dict[str, Any], board_index: int) -> dict[str, float]:
    age = to_float(row.get("age")) or 20.0
    height_inches = to_int(row.get("heightInches")) or 78
    youth_bonus = max(0.0, min(6.0, 22.5 - age))
    size_bonus = max(0.0, min(4.0, (height_inches - 74) / 3))
    board_bonus = max(0.0, 12.0 - board_index * 0.08)

    base_upside = 63 + youth_bonus + size_bonus + board_bonus
    if row.get("status") == "International":
        base_upside += 1.5
    if position == "C" and height_inches >= 83:
        base_upside += 2

    if position in {"PG", "SG"}:
        ppg, rpg, apg, stocks = 13.0, 3.4, 4.2, 1.2
        three_pct, fg_pct, ft_pct = 35.5, 44.5, 77.5
    elif position == "C":
        ppg, rpg, apg, stocks = 10.8, 7.6, 1.4, 2.0
        three_pct, fg_pct, ft_pct = 28.5, 55.0, 67.5
    else:
        ppg, rpg, apg, stocks = 12.1, 5.9, 2.4, 1.5
        three_pct, fg_pct, ft_pct = 33.5, 47.0, 73.0

    risk = 28 + max(0.0, age - 20) * 3 + board_index * 0.12
    if row.get("status") in {"Senior", "Graduate"}:
        risk += 4
    if row.get("status") == "International":
        risk += 2

    return {
        "ppg": round(ppg + board_bonus * 0.15, 1),
        "rpg": round(rpg, 1),
        "apg": round(apg, 1),
        "fg_pct": round(fg_pct, 1),
        "three_pct": round(three_pct, 1),
        "ft_pct": round(ft_pct, 1),
        "stocks": round(stocks, 1),
        "upside_score": round(max(55.0, min(88.0, base_upside)), 1),
        "risk_score": round(max(18.0, min(55.0, risk)), 1),
    }


def archetype(position: str, row: dict[str, Any]) -> str:
    status = row.get("status") or "prospect"
    if position in {"PG", "SG"}:
        return f"{status} guard prospect"
    if position == "C":
        return f"{status} frontcourt prospect"
    return f"{status} wing prospect"


def height(row: dict[str, Any]) -> str:
    return (
        row.get("heightFeetInches")
        or (row.get("height") or {}).get("feetAndInches")
        or "6-6"
    )


def school(row: dict[str, Any]) -> str:
    return str(row.get("school") or row.get("country") or "Unknown")


def to_int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    import sys

    if "--curated-only" in sys.argv:
        count = apply_curated_overrides_to_db()
        print(f"Applied curated overrides to {count} prospect(s).")
    else:
        main()
