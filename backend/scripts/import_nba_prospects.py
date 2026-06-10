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


URL = "https://www.nba.com/draft/2026/prospects"
SOURCE = "NBA.com 2026 Draft Prospects"


def main() -> None:
    Base.metadata.create_all(bind=engine)
    prospects = fetch_nba_prospects()

    with SessionLocal() as db:
        imported = 0
        updated = 0
        for board_index, row in enumerate(prospects, start=1):
            name = str(row.get("displayName") or "").strip()
            if not name:
                continue

            existing = db.scalar(
                select(Prospect).where(
                    Prospect.year == 2026,
                    Prospect.name == name,
                )
            )

            if existing is None:
                db.add(build_prospect(row=row, board_index=board_index))
                db.flush()
                imported += 1
            else:
                update_bio(existing, row)
                updated += 1

            prospect = db.scalar(
                select(Prospect).where(Prospect.year == 2026, Prospect.name == name)
            )
            if prospect is not None:
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
    )


def update_bio(prospect: Prospect, row: dict[str, Any]) -> None:
    prospect.position = normalize_position(row.get("position"))
    prospect.age = to_float(row.get("age")) or prospect.age
    prospect.height = height(row)
    prospect.weight = to_int(row.get("weightLbs")) or prospect.weight
    prospect.school_or_league = school(row)


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
    main()
