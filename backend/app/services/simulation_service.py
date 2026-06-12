from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.draft import DraftOrder
from app.models.prospect import Prospect
from app.models.scouting import ProspectScoutingProfile, TeamNeedProfile
from app.models.team import TeamNeed
from app.schemas.recommendation import RankedProspectRead, ScoreBreakdown
from app.schemas.simulation import (
    LockedPickRequest,
    SimulateRequest,
    SimulateResponse,
    SimulatedPickRead,
    TradeEvaluation,
)
from app.services.ranking_engine import ProspectRanking, rank_prospects
from app.services.team_need_adjustment import (
    TeamNeedSnapshot,
    adjust_team_need_after_pick,
)
from app.services.team_need_service import get_or_infer_team_need
from app.services.rumor_extractor import NewsSignal, extract_signals


# ---------------------------------------------------------------------------
# Helper: snapshot an ORM TeamNeed row into the in-memory TeamNeedSnapshot
# ---------------------------------------------------------------------------


def _snapshot_from_orm(orm: TeamNeed) -> TeamNeedSnapshot:
    return TeamNeedSnapshot(
        team_id=orm.team_id,
        year=orm.year,
        need_pg=orm.need_pg,
        need_sg=orm.need_sg,
        need_sf=orm.need_sf,
        need_pf=orm.need_pf,
        need_c=orm.need_c,
        need_shooting=orm.need_shooting,
        need_defense=orm.need_defense,
        need_creation=orm.need_creation,
    )


def _to_ranked_read(ranking: ProspectRanking) -> RankedProspectRead:
    return RankedProspectRead(
        prospect=ranking.prospect,
        scores=ScoreBreakdown(
            talent_score=ranking.talent_score,
            fit_score=ranking.fit_score,
            pick_value_score=ranking.pick_value_score,
            risk_penalty=ranking.risk_penalty,
            final_score=ranking.final_score,
        ),
        reasons=ranking.reasons,
        risks=ranking.risks,
        scouting_fit_score=ranking.scouting_fit_score,
        scouting_fit_positives=ranking.scouting_fit_positives,
        scouting_fit_risks=ranking.scouting_fit_risks,
        ranking_sort_score=ranking.ranking_sort_score,
        scouting_tiebreaker_applied=ranking.scouting_tiebreaker_applied,
        scouting_tiebreaker_delta=ranking.scouting_tiebreaker_delta,
    )


def _load_team_need_profile(
    db: Session,
    *,
    team_id: int,
    year: int,
) -> TeamNeedProfile | None:
    for horizon in ("next_season", "now"):
        profile = db.scalar(
            select(TeamNeedProfile).where(
                TeamNeedProfile.team_id == team_id,
                TeamNeedProfile.year == year,
                TeamNeedProfile.horizon == horizon,
            )
        )
        if profile is not None:
            return profile
    return None


def _load_prospect_scouting_profiles(
    db: Session,
    *,
    year: int,
    prospects: list[Prospect],
) -> dict[int, ProspectScoutingProfile]:
    prospect_ids = [prospect.id for prospect in prospects if prospect.id is not None]
    if not prospect_ids:
        return {}
    profiles = db.scalars(
        select(ProspectScoutingProfile).where(
            ProspectScoutingProfile.year == year,
            ProspectScoutingProfile.prospect_id.in_(prospect_ids),
        )
    )
    return {profile.prospect_id: profile for profile in profiles}


def _scouting_tiebreaker_line(ranking: ProspectRanking) -> str | None:
    if not ranking.scouting_tiebreaker_applied:
        return None
    positives = ranking.scouting_fit_positives or []
    addressed = ", ".join(positives[:4]) if positives else "profile fit"
    return (
        "Scouting fit tie-breaker applied: selected within same talent tier "
        f"because profile fit addressed {addressed}."
    )


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------

def _resolve_locked_prospect(
    db: Session,
    year: int,
    locked: LockedPickRequest,
) -> Prospect:
    """Resolve a single LockedPickRequest to a Prospect in the given year.

    Returns the resolved Prospect, or raises HTTPException(400).

    Rules:
      - Must provide prospect_id or non-empty prospect_name.
      - prospect_id must match an existing prospect with year == year.
      - prospect_name is matched case-insensitive (exact, after strip).
      - prospect_name matching multiple rows is rejected as ambiguous.
    """
    if locked.prospect_id is None and not (
        locked.prospect_name and locked.prospect_name.strip()
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"pick_no={locked.pick_no}: prospect_id or prospect_name is required"
            ),
        )

    if locked.prospect_id is not None:
        prospect = db.scalar(
            select(Prospect).where(
                Prospect.id == locked.prospect_id,
                Prospect.year == year,
            )
        )
        if prospect is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"pick_no={locked.pick_no}: prospect_id={locked.prospect_id} "
                    f"not found in year {year}"
                ),
            )
        return prospect

    # prospect_name: case-insensitive exact match
    name_norm = locked.prospect_name.strip().lower()
    matches = list(
        db.scalars(
            select(Prospect).where(
                Prospect.year == year,
                func.lower(Prospect.name) == name_norm,
            )
        )
    )
    if not matches:
        raise HTTPException(
            status_code=400,
            detail=(
                f"pick_no={locked.pick_no}: prospect_name={locked.prospect_name!r} "
                f"not found in year {year}"
            ),
        )
    if len(matches) > 1:
        raise HTTPException(
            status_code=400,
            detail=(
                f"pick_no={locked.pick_no}: prospect_name={locked.prospect_name!r} "
                f"is ambiguous ({len(matches)} matches)"
            ),
        )
    return matches[0]


def _validate_locked_picks(
    db: Session,
    request: SimulateRequest,
    draft_pick_nos: list[int],
) -> dict[int, Prospect]:
    """Validate the locked_picks block and return a `pick_no -> Prospect` map.

    All errors are HTTP 400 with a structured detail message. The map
    contains only those pick_nos that the user requested to lock; the main
    loop can simply check `pick_no in locked_prospects` to branch.
    """
    if not request.locked_picks:
        return {}

    valid_picks = set(draft_pick_nos)
    seen_pick_nos: set[int] = set()
    seen_prospect_ids: set[int] = set()
    resolved: dict[int, Prospect] = {}

    for locked in request.locked_picks:
        # duplicate pick_no
        if locked.pick_no in seen_pick_nos:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate locked pick_no={locked.pick_no}",
            )
        seen_pick_nos.add(locked.pick_no)

        # pick_no not in draft order
        if locked.pick_no not in valid_picks:
            raise HTTPException(
                status_code=400,
                detail=f"pick_no={locked.pick_no} is not in the draft order",
            )

        # resolve the prospect (this also enforces year, name, presence)
        prospect = _resolve_locked_prospect(db, request.year, locked)

        # duplicate prospect across two locked picks
        if prospect.id in seen_prospect_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Prospect {prospect.name!r} (id={prospect.id}) is already "
                    f"locked by another pick"
                ),
            )
        seen_prospect_ids.add(prospect.id)
        resolved[locked.pick_no] = prospect

    return resolved


def simulate_draft(db: Session, request: SimulateRequest) -> SimulateResponse:
    # 1. Compute effective_limit so that rounds actually constrains picks
    effective_limit = min(request.limit, 30 if request.rounds == 1 else 60)

    draft_order = list(
        db.scalars(
            select(DraftOrder)
            .where(DraftOrder.year == request.year)
            .options(selectinload(DraftOrder.team))
            .order_by(DraftOrder.pick_no)
            .limit(effective_limit)
        )
    )
    if not draft_order:
        raise HTTPException(status_code=404, detail="Draft order not found")

    # 2. Validate locked_picks BEFORE we walk the board. Any error here is
    #    a 400, not a 404 or 500. The map `locked_prospects[pick_no]` is the
    #    resolved Prospect object the main loop will use.
    draft_pick_nos = [draft_pick.pick_no for draft_pick in draft_order]
    locked_prospects = _validate_locked_picks(
        db=db, request=request, draft_pick_nos=draft_pick_nos,
    )

    prospects = list(
        db.scalars(
            select(Prospect)
            .where(Prospect.year == request.year)
            .order_by(Prospect.upside_score.desc())
        )
    )
    if not prospects:
        raise HTTPException(status_code=404, detail="No prospects found for year")

    selected_prospect_ids: set[int] = set()
    picks: list[SimulatedPickRead] = []

    # Dynamic team-need state: updated after each pick so that later picks
    # by the same team reflect already-addressed needs.
    team_need_state: dict[int, TeamNeedSnapshot] = {}
    team_need_profile_state: dict[int, TeamNeedProfile | None] = {}
    include_scouting_fit = (
        request.include_scouting_diagnostics
        or request.use_scouting_tiebreaker
    )

    # Market context (Phase 5B-M1): read cached news once per simulation
    # and pass it to decision_log. This MUST NOT touch selected_player,
    # ranking, or trade_evaluation — see _load_market_signals docstring.
    market_signals: list[NewsSignal] = _load_market_signals(db)

    for draft_pick in draft_order:
        available_prospects = [
            prospect for prospect in prospects if prospect.id not in selected_prospect_ids
        ]
        if not available_prospects:
            break

        # Fetch or reuse team need (snapshot, never ORM)
        if draft_pick.team_id not in team_need_state:
            orm_need = get_or_infer_team_need(
                db=db,
                team_id=draft_pick.team_id,
                year=request.year,
            )
            team_need_state[draft_pick.team_id] = _snapshot_from_orm(orm_need)

        team_need = team_need_state[draft_pick.team_id]
        team_need_profile = None
        scouting_profiles = None
        if include_scouting_fit:
            if draft_pick.team_id not in team_need_profile_state:
                team_need_profile_state[draft_pick.team_id] = _load_team_need_profile(
                    db=db,
                    team_id=draft_pick.team_id,
                    year=request.year,
                )
            team_need_profile = team_need_profile_state[draft_pick.team_id]
            scouting_profiles = _load_prospect_scouting_profiles(
                db=db,
                year=request.year,
                prospects=available_prospects,
            )

        # Rank the live board regardless of whether this is a locked pick.
        # Locked picks still want alternatives + candidate_board populated
        # so the frontend can render a side-by-side comparison.
        rankings = rank_prospects(
            team_need=team_need,
            pick_no=draft_pick.pick_no,
            prospects=available_prospects,
            team_need_profile=team_need_profile,
            scouting_profiles=scouting_profiles,
            include_scouting_fit=include_scouting_fit,
            enable_scouting_tiebreaker=request.use_scouting_tiebreaker,
        )

        if draft_pick.pick_no in locked_prospects:
            chosen = locked_prospects[draft_pick.pick_no]

            # Defence in depth: locked prospect must still be in the
            # available board (i.e. not already auto-picked above). The
            # validator already rejects duplicate prospect_ids across two
            # locked picks, so the only way this can fail is when an
            # earlier auto pick already took this prospect.
            chosen_ranking = next(
                (r for r in rankings if r.prospect.id == chosen.id), None,
            )
            if chosen_ranking is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"pick_no={draft_pick.pick_no}: locked prospect "
                        f"{chosen.name!r} is no longer available"
                    ),
                )

            # Surface the chosen prospect at position 0; the rest of the
            # board stays in score order. This keeps alternatives and
            # candidate_board meaningful for the UI.
            override_rankings = [chosen_ranking] + [
                r for r in rankings if r.prospect.id != chosen.id
            ]
            alternatives = override_rankings[1:4]
            trade_evaluation = evaluate_trade_market(
                pick_no=draft_pick.pick_no,
                top_score=chosen_ranking.final_score,
                alternative_scores=[r.final_score for r in alternatives],
                evaluate_trades=request.evaluate_trades,
            )
            decision_log = build_decision_log(
                pick_no=draft_pick.pick_no,
                team_abbr=draft_pick.team.abbr,
                selected_name=chosen.name,
                selected_score=chosen_ranking.final_score,
                alternatives=alternatives,
                trade_evaluation=trade_evaluation,
                draft_order_note=draft_pick.notes,
                locked=True,
                market_context_lines=_market_context_lines_for_pick(
                    signals=market_signals,
                    team_abbr=draft_pick.team.abbr,
                    pick_no=draft_pick.pick_no,
                    selected_prospect_name=chosen.name,
                ),
            )
            selected_prospect_ids.add(chosen.id)
            adjust_team_need_after_pick(team_need, chosen)

            picks.append(
                SimulatedPickRead(
                    pick=draft_pick.pick_no,
                    team=draft_pick.team,
                    original_team=draft_pick.original_team,
                    draft_order_note=draft_pick.notes,
                    selected_player=_to_ranked_read(chosen_ranking),
                    alternatives=[_to_ranked_read(r) for r in alternatives],
                    candidate_board=[
                        _to_ranked_read(r) for r in override_rankings[:5]
                    ],
                    trade_evaluation=trade_evaluation,
                    decision_log=decision_log,
                )
            )
        else:
            # ---- AUTO PICK BRANCH (v1) ----
            selected = rankings[0]
            alternatives = rankings[1:4]
            trade_evaluation = evaluate_trade_market(
                pick_no=draft_pick.pick_no,
                top_score=selected.final_score,
                alternative_scores=[ranking.final_score for ranking in alternatives],
                evaluate_trades=request.evaluate_trades,
            )
            decision_log = build_decision_log(
                pick_no=draft_pick.pick_no,
                team_abbr=draft_pick.team.abbr,
                selected_name=selected.prospect.name,
                selected_score=selected.final_score,
                alternatives=alternatives,
                trade_evaluation=trade_evaluation,
                draft_order_note=draft_pick.notes,
                scouting_tiebreaker_line=_scouting_tiebreaker_line(selected),
                market_context_lines=_market_context_lines_for_pick(
                    signals=market_signals,
                    team_abbr=draft_pick.team.abbr,
                    pick_no=draft_pick.pick_no,
                    selected_prospect_name=selected.prospect.name,
                ),
            )
            selected_prospect_ids.add(selected.prospect.id)
            adjust_team_need_after_pick(team_need, selected.prospect)

            picks.append(
                SimulatedPickRead(
                    pick=draft_pick.pick_no,
                    team=draft_pick.team,
                    original_team=draft_pick.original_team,
                    draft_order_note=draft_pick.notes,
                    selected_player=_to_ranked_read(selected),
                    alternatives=[_to_ranked_read(ranking) for ranking in alternatives],
                    candidate_board=[
                        _to_ranked_read(ranking) for ranking in rankings[:5]
                    ],
                    trade_evaluation=trade_evaluation,
                    decision_log=decision_log,
                )
            )

    return SimulateResponse(
        year=request.year,
        rounds=request.rounds,
        total_picks=len(picks),
        source=draft_order[0].source if draft_order else None,
        picks=picks,
    )


# ---------------------------------------------------------------------------
# Trade evaluation (signal only — never executes real trades)
# ---------------------------------------------------------------------------

def evaluate_trade_market(
    pick_no: int,
    top_score: float,
    alternative_scores: list[float],
    evaluate_trades: bool,
) -> TradeEvaluation:
    # MVP only evaluates trade market signals. It does not execute real trades.
    if not evaluate_trades:
        return TradeEvaluation(
            action="keep_pick",
            probability=0.0,
            rationale="Trade evaluation disabled for this simulation.",
        )

    next_best = alternative_scores[0] if alternative_scores else 0.0
    score_gap = top_score - next_best

    if pick_no <= 10 and top_score >= 82:
        return TradeEvaluation(
            action="field_trade_up_calls",
            probability=0.35,
            rationale=(
                "A high-value prospect is available in the lottery, so other teams "
                "may call about moving up. Current GM keeps the pick unless an "
                "overpay arrives."
            ),
        )

    if pick_no <= 20 and score_gap <= 2.0:
        return TradeEvaluation(
            action="shop_down",
            probability=0.42,
            rationale=(
                "The board is flat at this range, so trading down is plausible if "
                "the team can add a future second or move into a similar tier."
            ),
        )

    if pick_no > 35 and top_score < 67:
        return TradeEvaluation(
            action="sell_pick_or_two_way",
            probability=0.28,
            rationale=(
                "Late second-round value is modest; a cash, stash, or two-way path "
                "is realistic."
            ),
        )

    return TradeEvaluation(
        action="keep_pick",
        probability=0.16,
        rationale="The top ranked player separates enough from the board to submit the pick.",
    )


# ---------------------------------------------------------------------------
# Decision log
# ---------------------------------------------------------------------------

def build_decision_log(
    pick_no: int,
    team_abbr: str,
    selected_name: str,
    selected_score: float,
    alternatives,
    trade_evaluation: TradeEvaluation,
    draft_order_note: str | None,
    locked: bool = False,
    scouting_tiebreaker_line: str | None = None,
    market_context_lines: list[str] | None = None,
) -> list[str]:
    alt_summary = ", ".join(
        f"{ranking.prospect.name} ({ranking.final_score})" for ranking in alternatives
    )
    log = [
        f"Pick {pick_no}: {team_abbr} goes on the clock.",
    ]
    if draft_order_note:
        log.append(f"Draft-order context: {draft_order_note}.")
    log.extend(
        [
            f"Agent filters out already selected prospects and re-ranks the live board.",
            f"Top candidate: {selected_name} with final score {selected_score}.",
            f"Alternatives checked: {alt_summary or 'none available'}.",
            (
                f"Trade check: {trade_evaluation.action} "
                f"({round(trade_evaluation.probability * 100)}%). "
                f"{trade_evaluation.rationale}"
            ),
            f"GM submits {selected_name}; player is removed from later picks.",
        ]
    )
    if scouting_tiebreaker_line:
        log.append(scouting_tiebreaker_line)
    if locked:
        log.append("This pick was locked by user override.")
    log.append("Team needs are updated after the pick for later selections.")
    if market_context_lines:
        log.extend(market_context_lines)
    return log


# ---------------------------------------------------------------------------
# Market context (Phase 5B-M1, decision_log only)
# ---------------------------------------------------------------------------
#
# These helpers only feed decision_log. They DO NOT touch:
#   * ranking_engine / final_score
#   * selected_player
#   * evaluate_trade_market / TradeEvaluation
#   * trade action, probability, or rationale
#   * any API response shape
#
# A signal only appears in decision_log for a given pick if it matches
# the pick's team_abbr, pick_no, or the selected prospect's name.
# Mismatched signals (e.g. an LAL rumor on a SAS pick) are filtered out.

MARKET_CONTEXT_LIMIT = 3
MARKET_CONTEXT_LABEL = "Market context:"
_NEWS_KEYWORD_QUERY = "draft trade prospect workout pick"

# Imports kept inside helpers to keep top-of-file imports stable.
def _load_market_signals(db: Session, *, limit: int = 30) -> list[NewsSignal]:
    """Read cached news from the database and convert them to
    ``NewsSignal`` view objects. Pure read-only: no network, no
    ``fetch_recent_articles`` call. Returns ``[]`` on any failure
    (the simulation must never break because of an unrelated news
    table problem).
    """
    try:
        from app.services.news_service import search_articles

        articles = search_articles(
            db,
            keyword=_NEWS_KEYWORD_QUERY,
            limit=limit,
        )
    except Exception:  # noqa: BLE001
        return []
    try:
        return extract_signals(list(articles))
    except Exception:  # noqa: BLE001
        return []


def _signal_matches_pick(
    signal: NewsSignal,
    *,
    team_abbr: str,
    pick_no: int,
    selected_prospect_name: str | None,
) -> bool:
    """Decide whether a cached news signal is relevant to a given pick.

    The decision is **conservative on cross-team leak**: a signal that
    explicitly names a *different* team is *never* allowed to leak into
    the current pick via ``pick_no`` or ``prospect_name`` fallbacks. This
    is the strong guarantee that README §7.4 advertises.

    Matching rules, in order:

    1. **Hard team guard.** If ``signal.team_abbr`` is set (non-empty),
       and it normalises to a team *different* from the current pick's
       team, the signal is dropped (``return False``). It is irrelevant
       regardless of whether ``pick_no`` or ``prospect_name`` happen to
       match.
    2. **Same-team signal** (including empty-team signals that we
       already eliminated above). A same-team signal is shown when:
       - it is team-level (no ``pick_no`` and no ``prospect_name``), or
       - it is pick-specific (``signal.pick_no == pick_no``), or
       - it names the selected prospect (case-insensitive substring).
    3. **Teamless signal** (``signal.team_abbr`` empty/``None``) was
       short-circuited in step 1. We re-check it here: it may match
       by ``pick_no`` or by ``prospect_name`` only. A teamless signal
       that matches neither is dropped.

    Signals with no team, no pick, and no prospect context are *never*
    shown: there is no way to tie them to a specific draft situation.
    """
    signal_team = (signal.team_abbr or "").strip().upper()
    pick_team = (team_abbr or "").strip().upper()

    has_pick_match = (
        signal.pick_no is not None and signal.pick_no == pick_no
    )
    has_prospect_match = bool(
        signal.prospect_name
        and selected_prospect_name
        and signal.prospect_name.lower() in selected_prospect_name.lower()
    )

    # Step 1: hard cross-team guard.  A signal that names a different
    # team must never leak via pick_no / prospect_name fallbacks.
    if signal_team:
        if signal_team != pick_team:
            return False
        # Step 2: same-team signal is relevant if it is team-level,
        # pick-specific, or prospect-specific.
        is_team_level = (
            signal.pick_no is None and not signal.prospect_name
        )
        return is_team_level or has_pick_match or has_prospect_match

    # Step 3: teamless signals may only match by pick_no or prospect.
    return has_pick_match or has_prospect_match


def _format_market_line(signal: NewsSignal) -> str:
    """Render a single signal as a short, non-prescriptive line.

    The wording is intentionally *observational* ("recent cached news
    links ...") rather than prescriptive ("system recommends ...").
    """
    confidence_pct = int(round(signal.confidence * 100))
    parts: list[str] = []
    if signal.team_abbr:
        parts.append(signal.team_abbr)
    intent_label = signal.intent.value.replace("_", " ")
    parts.append(f"has a recent {intent_label} signal")
    if signal.pick_no is not None:
        parts.append(f"around pick #{signal.pick_no}")
    summary = signal.summary
    if summary:
        snippet = summary if len(summary) <= 50 else summary[:47] + "..."
        parts.append(f"({snippet})")
    return (
        f"{MARKET_CONTEXT_LABEL} "
        + " ".join(parts)
        + f" (confidence {confidence_pct}%)."
    )


def _market_context_lines_for_pick(
    *,
    signals: list[NewsSignal],
    team_abbr: str,
    pick_no: int,
    selected_prospect_name: str | None = None,
    limit: int = MARKET_CONTEXT_LIMIT,
) -> list[str]:
    """Filter the global signal list down to the subset that is
    relevant to one pick, then return up to ``limit`` rendered lines.

    The filter is team/pick/prospect based — see
    :func:`_signal_matches_pick`. The input ``signals`` is assumed to
    be sorted by ``-confidence`` (this is what
    :func:`app.services.rumor_extractor.extract_signals` already
    returns), so we keep the top ``limit`` matches in that order.
    """
    if not signals:
        return []
    matches = [
        s for s in signals
        if _signal_matches_pick(
            s,
            team_abbr=team_abbr,
            pick_no=pick_no,
            selected_prospect_name=selected_prospect_name,
        )
    ]
    return [_format_market_line(s) for s in matches[:limit]]
