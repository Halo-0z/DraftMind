from __future__ import annotations

from dataclasses import dataclass
from typing import Any


TEAM_PROJECTION_TYPE_SCORE = {
    "manual_prediction": 95.0,
    "team_report": 84.0,
    "workout_signal": 76.0,
    "consensus_mock": 64.0,
}
PROSPECT_PROJECTION_SOURCE_WEIGHT = {
    "manual_projection": 1.0,
    "seed_projection": 0.7,
    "consensus_reference": 0.45,
}
TEAM_PROJECTION_TYPE_ADJUSTMENT = {
    "manual_prediction": 6.0,
    "team_report": 4.8,
    "workout_signal": 3.6,
    "consensus_mock": 2.4,
}
MAX_CALIBRATION_FINAL_SCORE_GAP = 8.0
VERY_STRONG_MANUAL_FINAL_SCORE_GAP = 16.0

# ---------------------------------------------------------------------------
# B0-I: high market-prior availability guardrail
#
# A top-market-prior prospect (mock expected top-8, high confidence, currently
# inside his projected draft range) must not silently slide into the 30s just
# because DraftMind's own final_score is lower than the consensus.  The reach
# guardrail (MAX_CALIBRATION_FINAL_SCORE_GAP) already blocks "early reach", but
# there was no symmetric "availability floor" to stop the same prospect from
# slipping through his whole range with no one selecting him.
#
# When ALL the MARKET_PRIOR_* gate conditions hold, this layer:
#   1. relaxes the gap guardrail from 8.0 to MARKET_PRIOR_RELAXED_GAP (so the
#      prospect becomes eligible to compete on sort_score instead of being
#      pinned below the original top); and
#   2. raises his prediction_sort_score to a floor just under the original
#      top final_score, so he can actually win the pick.
#
# A separate HARD_REJECT_GAP keeps DraftMind's independent veto: if the raw
# score gap is enormous, the model's disagreement is honoured and the floor is
# NOT applied.  This is the difference between "consensus-informed" and
# "consensus-controlled".
# ---------------------------------------------------------------------------
MARKET_PRIOR_MAX_EXPECTED_PICK = 8
MARKET_PRIOR_MIN_CONFIDENCE = 0.70
MARKET_PRIOR_AVAILABILITY_GRACE = 2
MARKET_PRIOR_RELAXED_GAP = 16.0
MARKET_PRIOR_HARD_REJECT_GAP = 20.0
# When the current pick has a matching TeamPickProjection for this player,
# the floor sits very close to the original top (a near-tie) so a strong
# same-team market signal can realistically win.  Without such a team
# signal, the floor is a little lower: it still prevents an abnormal slide
# but does not overpower an in-range competitor from a different team.
MARKET_PRIOR_TEAM_MATCH_FLOOR_GAP = 0.5
MARKET_PRIOR_GENERIC_FLOOR_GAP = 3.0
NEAR_EXPECTED_PICK_BONUS = 0.50
NEAR_EXPECTED_PICK_MAX_DISTANCE = 1
# Only genuine market / human projection sources may trigger the floor.
# ``consensus_reference`` = market prior; ``manual_projection`` = explicit
# human prediction.  ``seed_projection`` is demo/development data and must
# NOT gain the strong selection floor (it can still participate in the
# ordinary weak prediction-calibration adjustment).  ``news_display_only``
# and any unknown source are excluded for the same reason as before.
MARKET_PRIOR_AVAILABILITY_SOURCES = frozenset(
    {"consensus_reference", "manual_projection"}
)
# A TeamPickProjection counts as a strong same-team match only when its own
# source is a real weighted projection source.  ``seed_projection`` is
# allowed here (it is a legitimate weighted source) but display-only /
# unknown sources are not — they must not upgrade a prospect to the
# stronger team-match floor.
MARKET_PRIOR_TEAM_MATCH_SOURCES = frozenset(
    {"consensus_reference", "manual_projection", "seed_projection"}
)


def _is_market_prior_availability_source(source: str | None) -> bool:
    return source in MARKET_PRIOR_AVAILABILITY_SOURCES


def _is_market_prior_team_match_source(source: str | None) -> bool:
    return source in MARKET_PRIOR_TEAM_MATCH_SOURCES


@dataclass(frozen=True)
class PredictionCalibrationResult:
    range_score: float
    tier_score: float
    team_projection_score: float
    confidence_weight: float
    shadow_score: float
    notes: list[str]


@dataclass(frozen=True)
class PredictionSelectionResult:
    sort_score: float
    rank: int
    delta: int
    applied: bool
    eligible: bool
    notes: list[str]


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _get_number(obj: Any, attr: str) -> float | None:
    value = getattr(obj, attr, None)
    if value is None:
        return None
    return float(value)


def team_projection_type_score(projection_type: str | None) -> float:
    if not projection_type:
        return 0.0
    return TEAM_PROJECTION_TYPE_SCORE.get(projection_type, 50.0)


def _source_weight(source: str | None) -> float:
    if not source:
        return 0.0
    return PROSPECT_PROJECTION_SOURCE_WEIGHT.get(source, 0.0)


def _team_adjustment(projection_type: str | None) -> float:
    if not projection_type:
        return 0.0
    return TEAM_PROJECTION_TYPE_ADJUSTMENT.get(projection_type, 0.0)


def _range_score(
    *,
    pick_no: int,
    prospect_projection: Any | None,
    notes: list[str],
) -> float:
    if prospect_projection is None:
        notes.append("No prospect projection signal available.")
        return 50.0

    range_min = _get_number(prospect_projection, "draft_range_min")
    range_max = _get_number(prospect_projection, "draft_range_max")
    expected_pick = _get_number(prospect_projection, "expected_pick")

    if range_min is None and range_max is None and expected_pick is None:
        notes.append("Projection signal has no expected pick or draft range.")
        return 50.0

    if range_min is None:
        range_min = expected_pick
    if range_max is None:
        range_max = expected_pick
    if range_min is None or range_max is None:
        return 50.0

    if range_min > range_max:
        range_min, range_max = range_max, range_min

    if range_min <= pick_no <= range_max:
        notes.append("Pick is within projected draft range.")
        return 90.0

    if pick_no < range_min:
        distance = range_min - pick_no
        if distance <= 3:
            notes.append("Pick is slightly earlier than projected range.")
            return 68.0
        notes.append("Pick is much earlier than projected range; possible reach.")
        return 32.0

    distance = pick_no - range_max
    if distance <= 3:
        notes.append("Pick is slightly later than projected range.")
        return 72.0
    notes.append("Pick is much later than projected range; availability risk.")
    return 36.0


def _tier_band(tier: int | None) -> tuple[int, int] | None:
    if tier is None:
        return None
    if tier <= 1:
        return (1, 5)
    if tier == 2:
        return (6, 10)
    if tier == 3:
        return (1, 14)
    if tier == 4:
        return (1, 30)
    return (1, 60)


def _tier_score(
    *,
    pick_no: int,
    prospect_projection: Any | None,
    notes: list[str],
) -> float:
    if prospect_projection is None:
        return 50.0
    tier_value = getattr(prospect_projection, "tier", None)
    if tier_value is None:
        return 50.0
    band = _tier_band(int(tier_value))
    if band is None:
        return 50.0
    low, high = band
    if low <= pick_no <= high:
        notes.append(f"Pick is reasonable for projected tier {int(tier_value)}.")
        return 85.0
    distance = min(abs(pick_no - low), abs(pick_no - high))
    if distance <= 5:
        notes.append(f"Pick is near projected tier {int(tier_value)} band.")
        return 65.0
    notes.append(f"Pick is outside projected tier {int(tier_value)} band.")
    return 42.0


def _confidence_weight(
    *,
    prospect_projection: Any | None,
    team_projection: Any | None,
) -> float:
    prospect_confidence = _get_number(prospect_projection, "confidence") or 0.0
    team_confidence = _get_number(team_projection, "confidence") or 0.0
    return _clamp(max(prospect_confidence, team_confidence), 0.0, 1.0)


@dataclass(frozen=True)
class MarketPriorAvailabilityResult:
    """Outcome of the high market-prior availability gate (B0-I).

    ``active`` is True only when every gate condition holds.  ``hard_rejected``
    is True when the final_score gap is so large that DraftMind's own model
    vetoes the consensus regardless of the other conditions; in that case the
    floor must NOT be applied even though the prospect otherwise looks like a
    top-market-prior player.
    """

    active: bool
    hard_rejected: bool
    team_match: bool
    relaxed_gap: float
    floor_gap: float


def _market_prior_availability(
    *,
    pick_no: int,
    final_score: float,
    original_top_final_score: float,
    prospect_projection: Any | None,
    team_projection: Any | None,
) -> MarketPriorAvailabilityResult:
    """Evaluate the B0-I high market-prior availability gate.

    Gate (ALL must hold for ``active`` to be True):
      * ``expected_pick <= MARKET_PRIOR_MAX_EXPECTED_PICK``
      * ``confidence >= MARKET_PRIOR_MIN_CONFIDENCE``
      * ``draft_range_min`` and ``draft_range_max`` are both present
      * ``draft_range_min <= pick_no <= draft_range_max + GRACE``  (the pick
        has entered, and not yet left, the projected range window)
      * the final_score gap does not exceed ``MARKET_PRIOR_HARD_REJECT_GAP``
        (otherwise DraftMind's independent disagreement is honoured)

    ``hard_rejected`` is reported separately so callers can distinguish
    "gate not satisfied" (e.g. pick too early, low confidence) from
    "gate satisfied but DraftMind hard-vetoed the consensus".
    """
    team_match = (
        team_projection is not None
        and _is_market_prior_team_match_source(
            getattr(team_projection, "source", None)
        )
    )
    inactive_no_veto = MarketPriorAvailabilityResult(
        active=False,
        hard_rejected=False,
        team_match=team_match,
        relaxed_gap=MAX_CALIBRATION_FINAL_SCORE_GAP,
        floor_gap=MARKET_PRIOR_GENERIC_FLOOR_GAP,
    )

    if prospect_projection is None:
        return inactive_no_veto

    # Only genuine market / human projection sources may trigger the floor.
    # ``seed_projection`` (demo/development data), ``news_display_only`` and
    # any unknown source are excluded — they must not gain the strong
    # selection floor even if their other gate signals look strong.  They
    # can still participate in the ordinary weak prediction-calibration
    # adjustment, which is computed separately and is unaffected here.
    source = getattr(prospect_projection, "source", None)
    if not _is_market_prior_availability_source(source):
        return inactive_no_veto

    expected_pick = _get_number(prospect_projection, "expected_pick")
    range_min = _get_number(prospect_projection, "draft_range_min")
    range_max = _get_number(prospect_projection, "draft_range_max")
    confidence = _confidence_weight(
        prospect_projection=prospect_projection,
        team_projection=team_projection,
    )

    if expected_pick is None or expected_pick > MARKET_PRIOR_MAX_EXPECTED_PICK:
        return inactive_no_veto
    if confidence < MARKET_PRIOR_MIN_CONFIDENCE:
        return inactive_no_veto
    if range_min is None or range_max is None:
        return inactive_no_veto

    final_gap = original_top_final_score - final_score
    hard_rejected = final_gap > MARKET_PRIOR_HARD_REJECT_GAP
    if hard_rejected:
        return MarketPriorAvailabilityResult(
            active=False,
            hard_rejected=True,
            team_match=team_match,
            relaxed_gap=MAX_CALIBRATION_FINAL_SCORE_GAP,
            floor_gap=MARKET_PRIOR_GENERIC_FLOOR_GAP,
        )

    # Pick must have entered the projected range and not have left it by
    # more than the grace window.  Being below range_min would be a reach;
    # being above range_max + grace means the slide has run past the
    # protection window.
    window_max = range_max + MARKET_PRIOR_AVAILABILITY_GRACE
    if pick_no < range_min or pick_no > window_max:
        return inactive_no_veto

    # ``team_match`` was resolved at the top of the function against the
    # MARKET_PRIOR_TEAM_MATCH_SOURCES allow-list, so a display-only /
    # unknown team source falls back to the weaker generic floor here.
    return MarketPriorAvailabilityResult(
        active=True,
        hard_rejected=False,
        team_match=team_match,
        relaxed_gap=MARKET_PRIOR_RELAXED_GAP,
        floor_gap=(
            MARKET_PRIOR_TEAM_MATCH_FLOOR_GAP
            if team_match
            else MARKET_PRIOR_GENERIC_FLOOR_GAP
        ),
    )


def has_same_team_projection_priority(
    *,
    pick_no: int,
    final_score: float,
    original_top_final_score: float,
    prospect_projection: Any | None,
    team_projection: Any | None,
) -> bool:
    """Return whether a same-team TeamPickProjection earns priority.

    This is the B0-K2b guardrail: the underlying B0-I availability gate still
    owns all validation (trusted source, top-8 expected pick, confidence,
    range/grace, and hard-reject).  This helper only narrows that result to
    a real same-team projection match that is also eligible under the current
    prediction-selection gap rules.
    """
    availability = _market_prior_availability(
        pick_no=pick_no,
        final_score=final_score,
        original_top_final_score=original_top_final_score,
        prospect_projection=prospect_projection,
        team_projection=team_projection,
    )
    if not availability.active or not availability.team_match:
        return False

    strong_manual_signal = (
        getattr(team_projection, "projection_type", None) == "manual_prediction"
        and getattr(team_projection, "source", None) == "manual_projection"
        and (_get_number(team_projection, "confidence") or 0.0) >= 0.85
    )
    base_max_gap = (
        VERY_STRONG_MANUAL_FINAL_SCORE_GAP
        if strong_manual_signal
        else MAX_CALIBRATION_FINAL_SCORE_GAP
    )
    max_gap = max(base_max_gap, availability.relaxed_gap)
    final_gap = original_top_final_score - final_score
    return final_gap <= max_gap


def calculate_prediction_calibration(
    *,
    pick_no: int,
    ranking: Any,
    prospect_projection: Any | None,
    team_projection: Any | None,
) -> PredictionCalibrationResult:
    notes: list[str] = []
    range_score = _range_score(
        pick_no=pick_no,
        prospect_projection=prospect_projection,
        notes=notes,
    )
    tier_score = _tier_score(
        pick_no=pick_no,
        prospect_projection=prospect_projection,
        notes=notes,
    )
    team_score = team_projection_type_score(
        getattr(team_projection, "projection_type", None),
    )
    if team_projection is not None:
        notes.append(
            f"Team-specific projection signal: {team_projection.projection_type}.",
        )

    confidence = _confidence_weight(
        prospect_projection=prospect_projection,
        team_projection=team_projection,
    )
    base_final_score = _clamp(float(getattr(ranking, "final_score", 0.0)))
    market_component = (
        range_score * 0.45
        + tier_score * 0.20
        + team_score * 0.35
    )
    market_weight = confidence * 0.35
    shadow_score = (
        base_final_score * (1.0 - market_weight)
        + market_component * market_weight
    )

    return PredictionCalibrationResult(
        range_score=round(range_score, 1),
        tier_score=round(tier_score, 1),
        team_projection_score=round(team_score, 1),
        confidence_weight=round(confidence, 3),
        shadow_score=round(shadow_score, 2),
        notes=notes,
    )


def calculate_prediction_sort_score(
    *,
    pick_no: int,
    ranking: Any,
    prospect_projection: Any | None,
    team_projection: Any | None,
    original_top_final_score: float,
) -> tuple[float, bool, list[str]]:
    """Return an opt-in selection score for actual-outcome prediction mode.

    This deliberately does not mutate ``final_score`` or any ranking-engine
    component.  It is a separate sort key with guardrails so weak consensus
    signals cannot hard-lock a large reach.
    """
    notes: list[str] = []
    final_score = float(getattr(ranking, "final_score", 0.0))
    final_gap = original_top_final_score - final_score
    prospect_confidence = _get_number(prospect_projection, "confidence") or 0.0
    team_confidence = _get_number(team_projection, "confidence") or 0.0
    confidence = _clamp(max(prospect_confidence, team_confidence), 0.0, 1.0)
    source_weight = _source_weight(getattr(prospect_projection, "source", None))
    team_type = getattr(team_projection, "projection_type", None)
    team_source_weight = _source_weight(getattr(team_projection, "source", None))

    strong_manual_signal = (
        team_type == "manual_prediction"
        and getattr(team_projection, "source", None) == "manual_projection"
        and team_confidence >= 0.85
    )
    # B0-I: evaluate the high market-prior availability gate up front so the
    # relaxed gap (and later the floor) can take effect for in-range top-8
    # consensus prospects.  A hard-reject still leaves max_gap at 8.0.
    availability = _market_prior_availability(
        pick_no=pick_no,
        final_score=final_score,
        original_top_final_score=original_top_final_score,
        prospect_projection=prospect_projection,
        team_projection=team_projection,
    )
    base_max_gap = (
        VERY_STRONG_MANUAL_FINAL_SCORE_GAP
        if strong_manual_signal
        else MAX_CALIBRATION_FINAL_SCORE_GAP
    )
    # The availability gate may relax the gap from 8.0 up to 16.0, but only
    # when active (never when hard-rejected).  A strong manual team signal
    # already grants an even larger 16.0 window and wins ties.
    max_gap = (
        max(base_max_gap, availability.relaxed_gap)
        if availability.active
        else base_max_gap
    )
    eligible = final_gap <= max_gap
    if not eligible:
        notes.append(
            f"Calibration guardrail blocked selection: final_score gap {round(final_gap, 2)} exceeds {max_gap}."
        )
    if availability.hard_rejected:
        # Reported independently of the ``eligible`` outcome above: this says
        # the high-market-prior floor was deliberately withheld because
        # DraftMind's own score disagreed with the consensus by more than the
        # HARD_REJECT threshold.  When hard-rejected the gap is necessarily
        # also > 8.0, so both lines may appear together.
        notes.append(
            "High market-prior availability guardrail vetoed by DraftMind "
            f"final_score gap {round(final_gap, 2)} > {MARKET_PRIOR_HARD_REJECT_GAP}."
        )

    range_score = _range_score(
        pick_no=pick_no,
        prospect_projection=prospect_projection,
        notes=notes,
    )
    tier_score = _tier_score(
        pick_no=pick_no,
        prospect_projection=prospect_projection,
        notes=notes,
    )
    adjustment = 0.0
    adjustment += (range_score - 50.0) * 0.12 * confidence * source_weight
    adjustment += (tier_score - 50.0) * 0.06 * confidence * source_weight

    if team_projection is not None:
        adjustment += _team_adjustment(team_type) * team_confidence * team_source_weight
        notes.append(f"Team projection adjustment from {team_type}.")

    expected_pick = _get_number(prospect_projection, "expected_pick")
    range_min = _get_number(prospect_projection, "draft_range_min")
    range_max = _get_number(prospect_projection, "draft_range_max")
    tier = getattr(prospect_projection, "tier", None)
    if (
        tier is not None
        and int(tier) <= 1
        and expected_pick is not None
        and expected_pick <= 3
        and range_min is not None
        and range_max is not None
        and range_min <= pick_no <= range_max
    ):
        adjustment += 2.5 * confidence * source_weight
        notes.append("Top-tier early-pick protection applied.")

    if range_min is not None and pick_no < range_min - 2:
        reach_penalty = min(14.0, 6.0 + (range_min - pick_no - 2) * 1.5)
        adjustment -= reach_penalty * max(source_weight, 0.3)
        notes.append(f"Reach penalty applied: {round(reach_penalty, 1)}.")

    if (
        expected_pick is not None
        and _is_market_prior_availability_source(
            getattr(prospect_projection, "source", None)
        )
        and abs(pick_no - expected_pick) <= NEAR_EXPECTED_PICK_MAX_DISTANCE
    ):
        adjustment += NEAR_EXPECTED_PICK_BONUS
        notes.append("Near expected-pick bonus applied.")

    sort_score = final_score + adjustment
    if not eligible:
        sort_score = min(sort_score, original_top_final_score - 0.01)

    # B0-I: high market-prior availability floor.  When the gate is active,
    # raise the sort_score to just under the original top final_score so the
    # prospect can actually compete for the pick instead of being buried by
    # his own (lower) raw final_score.  The floor is never allowed to exceed
    # the "eligible ceiling" (original_top - 0.01), so an availability-floor
    # prospect can at most tie the original top from below — never leapfrog
    # it.  This keeps the protection symmetric with the reach guardrail and
    # prevents consensus from hard-locking the selection.
    if availability.active and eligible:
        floor = original_top_final_score - availability.floor_gap
        if sort_score < floor:
            sort_score = floor
            expected_pick_value = _get_number(prospect_projection, "expected_pick")
            expected_pick_repr = (
                f"#{int(expected_pick_value)}" if expected_pick_value is not None else "top market prior"
            )
            signal_clause = (
                " with matching team projection signal"
                if availability.team_match
                else ""
            )
            notes.append(
                "High market-prior availability protection applied"
                f"{signal_clause}: expected {expected_pick_repr} and current "
                f"pick {pick_no} is inside projected range."
            )

    return round(sort_score, 2), eligible, notes
