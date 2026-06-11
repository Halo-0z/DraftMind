"""Shared team-need adjustment helpers.

This module was extracted from ``simulation_service`` so that both
``simulation_service`` and ``recommendation_service`` can import the
in-memory team-need state primitives without creating an import cycle.

It exposes:

* :class:`TeamNeedSnapshot` — lightweight in-memory copy of a
  :class:`app.models.team.TeamNeed` row, mutated through picks.
* :class:`ProspectLike` — duck-typed Protocol that captures the
  prospect attributes consumed by :func:`adjust_team_need_after_pick`.
* :func:`clamp_need` — clamp a need score to the valid range
  ``[1, 10]``.
* :func:`adjust_team_need_after_pick` — reduce position and skill
  needs after a team selects a prospect.

It is **pure** (no DB, no FastAPI, no LLM, no business logic beyond
the adjustment rules).  Both :func:`simulation_service.simulate_draft`
and :func:`recommendation_service._compute_available_prospects_for_pick`
use these primitives to keep their in-memory team-need state in sync
with the picks the engine walks through.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


# ---------------------------------------------------------------------------
# Duck-typed contract for any object carrying the prospect attributes that
# adjust_team_need_after_pick cares about.  Both the SQLAlchemy Prospect
# model and the unit-test ProspectStub satisfy this Protocol structurally.
# ---------------------------------------------------------------------------


class ProspectLike(Protocol):
    position: Optional[str]
    three_pct: Optional[float]
    apg: Optional[float]
    stocks: Optional[float]


# ---------------------------------------------------------------------------
# Lightweight copy of TeamNeed so we never mutate ORM objects in the session
# ---------------------------------------------------------------------------


@dataclass
class TeamNeedSnapshot:
    """In-memory copy of team needs for a single simulation run."""

    team_id: int
    year: int
    need_pg: int = 5
    need_sg: int = 5
    need_sf: int = 5
    need_pf: int = 5
    need_c: int = 5
    need_shooting: int = 6
    need_defense: int = 6
    need_creation: int = 6


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def clamp_need(value: float | int) -> int:
    """Clamp a need score to the valid range [1, 10]."""
    return max(1, min(10, int(round(value))))


def adjust_team_need_after_pick(team_need: TeamNeedSnapshot, prospect: object) -> None:
    """Decrease position and skill needs after a team selects a prospect.

    Position rules (decrease by 2 each):
      - PG / G  -> need_pg
      - SG / G  -> need_sg
      - SF / F  -> need_sf
      - PF / F  -> need_pf
      - C       -> need_c

    Skill rules (decrease by 1 each):
      - three_pct >= 36  -> need_shooting
      - apg >= 4         -> need_creation
      - stocks >= 1.8    -> need_defense

    All values are clamped to [1, 10].
    """
    pos = (prospect.position or "").upper()

    # Position needs — decrease by 2
    if "PG" in pos or pos == "G":
        team_need.need_pg = clamp_need(team_need.need_pg - 2)
    if "SG" in pos or pos == "G":
        team_need.need_sg = clamp_need(team_need.need_sg - 2)
    if "SF" in pos or pos == "F":
        team_need.need_sf = clamp_need(team_need.need_sf - 2)
    if "PF" in pos or pos == "F":
        team_need.need_pf = clamp_need(team_need.need_pf - 2)
    if "C" in pos:
        team_need.need_c = clamp_need(team_need.need_c - 2)

    # Skill needs — decrease by 1
    if (prospect.three_pct or 0) >= 36:
        team_need.need_shooting = clamp_need(team_need.need_shooting - 1)
    if (prospect.apg or 0) >= 4:
        team_need.need_creation = clamp_need(team_need.need_creation - 1)
    if (prospect.stocks or 0) >= 1.8:
        team_need.need_defense = clamp_need(team_need.need_defense - 1)
