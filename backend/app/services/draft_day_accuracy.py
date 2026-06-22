"""Draft-Day Accuracy Mode (M4-CF): consensus-priority selection policy.

This module implements the S1 ``consensus-priority`` selection policy
recommended by the M4-CE preflight. It is an **opt-in** mode that the
default Auto Simulation does NOT use. When enabled, the selection order
strongly follows the public projection board (``ProspectDraftProjection``)
instead of the model's internal ``final_score``.

Design rules (M4-CF):
  * Does NOT replace the default Auto Simulation.
  * Does NOT change ``ranking_engine``, ``talent_score``, ``final_score``,
    ``prediction_sort_score`` weights, DB, CSV, or seed data.
  * Does NOT hardcode the Final Accuracy Board.
  * Still applies the M4-CC official availability guard (caller's duty).
  * Selection is purely algorithmic: it reads existing
    ``ProspectDraftProjection`` rows and uses ``TeamPickProjection`` as a
    team signal tie-breaker.

S1 sort key (per M4-CE section 12, lower tuple = higher priority):
  1. Has valid projection (True first => 0 before 1)
  2. Lower ``expected_pick`` first
  3. Current pick falls inside projected range (True first)
  4. Higher ``confidence`` first (negated so higher sorts earlier)
  5. Has team projection signal for this pick (True first)
  6. Higher model ``final_score`` as final tie-breaker (negated)
  7. Prospect id as deterministic final tie-breaker

Prospects without a projection remain selectable but are sorted after all
projected candidates.
"""

from __future__ import annotations

from typing import Mapping

from app.models.projection import ProspectDraftProjection, TeamPickProjection
from app.models.prospect import Prospect
from app.services.ranking_engine import ProspectRanking


# Sentinel for "no projection" expected_pick. Must be larger than any real
# expected_pick (which is capped at 100 by the DB check constraint).
_NO_PROJECTION_EXPECTED_PICK = 10_000


def _expected_pick(projection: ProspectDraftProjection | None) -> int:
    if projection is None:
        return _NO_PROJECTION_EXPECTED_PICK
    value = projection.expected_pick
    if value is None:
        return _NO_PROJECTION_EXPECTED_PICK
    return int(value)


def _range_hit(
    projection: ProspectDraftProjection | None, pick_no: int
) -> bool:
    if projection is None:
        return False
    rmin = projection.draft_range_min
    rmax = projection.draft_range_max
    if rmin is None or rmax is None:
        return False
    return int(rmin) <= pick_no <= int(rmax)


def _confidence(projection: ProspectDraftProjection | None) -> float:
    if projection is None:
        return 0.0
    value = projection.confidence
    if value is None:
        return 0.0
    return float(value)


def _has_team_signal(
    team_projection_map: Mapping[int, TeamPickProjection] | None,
    prospect_id: int | None,
) -> bool:
    if team_projection_map is None or prospect_id is None:
        return False
    return prospect_id in team_projection_map


def consensus_priority_sort_key(
    ranking: ProspectRanking,
    *,
    prospect_projection_map: Mapping[int, ProspectDraftProjection] | None,
    team_projection_map: Mapping[int, TeamPickProjection] | None,
    pick_no: int,
):
    """Return a sort key that orders candidates by S1 consensus-priority.

    Lower tuple = higher priority. Use with ``sorted(..., key=...)``.
    """
    prospect = ranking.prospect
    prospect_id = prospect.id if prospect is not None else None
    projection = None
    if prospect_id is not None and prospect_projection_map is not None:
        projection = prospect_projection_map.get(prospect_id)

    has_projection = projection is not None
    expected_pick = _expected_pick(projection)
    range_hit = _range_hit(projection, pick_no)
    confidence = _confidence(projection)
    team_signal = _has_team_signal(team_projection_map, prospect_id)
    final_score = float(ranking.final_score)
    pid = prospect_id if prospect_id is not None else 0

    # Booleans sort False(0) before True(1). We want "has_projection=True"
    # to come first, so we negate via ``not``. Same for range_hit and
    # team_signal. For confidence and final_score, higher is better, so we
    # negate them.
    return (
        0 if has_projection else 1,
        expected_pick,
        0 if range_hit else 1,
        -confidence,
        0 if team_signal else 1,
        -final_score,
        pid,
    )


def reorder_rankings_by_consensus_priority(
    rankings: list[ProspectRanking],
    *,
    prospect_projection_map: Mapping[int, ProspectDraftProjection] | None,
    team_projection_map: Mapping[int, TeamPickProjection] | None,
    pick_no: int,
) -> list[ProspectRanking]:
    """Return a new list of rankings ordered by S1 consensus-priority.

    The input list is not mutated. The returned list contains the same
    ProspectRanking objects in the new order.
    """
    return sorted(
        rankings,
        key=lambda ranking: consensus_priority_sort_key(
            ranking,
            prospect_projection_map=prospect_projection_map,
            team_projection_map=team_projection_map,
            pick_no=pick_no,
        ),
    )


__all__ = [
    "consensus_priority_sort_key",
    "reorder_rankings_by_consensus_priority",
]
