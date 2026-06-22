"""Tests for /api/recommend (Phase 6B-M1 board-aware).

Covers:
  1. pick=1 returns the top prospect (no prior board simulation).
  2. pick=N (with prior draft picks) excludes prospects that the
     prior picks would have auto-selected, *without* lowering
     anyone's score.
  3. A high-upside "dropper" can still be recommended when
     ``_compute_available_prospects_for_pick`` returns them in
     the available pool.
  4. /api/simulate behavior is unchanged.
  5. ranking_engine is not modified by the recommend path — the
     same ``rank_prospects`` import is used, and the change is
     the *input* pool size, not the formula.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.prospect import Prospect


# ---------------------------------------------------------------------------
# 1. pick #1 仍可推荐顶级 prospect
# ---------------------------------------------------------------------------


def test_recommend_pick_1_returns_top_prospect(
    client: TestClient, db_session: Session,
) -> None:
    """No prior draft pick exists for pick=1 in the conftest seed
    (draft_order 2/5/10/20), so both prospects are still on the
    board.  The recommendation at pick=1 must be the highest-
    upside prospect in the seed (data-driven — we don't hardcode
    a name).
    """
    top_prospect = db_session.scalars(
        select(Prospect)
        .where(Prospect.year == 2026)
        .order_by(Prospect.upside_score.desc())
    ).first()
    assert top_prospect is not None  # sanity: conftest has prospects

    response = client.post(
        "/api/recommend",
        json={
            "year": 2026,
            "team": "SAS",
            "pick": 1,
            "mode": "gm_decision",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["team"]["abbr"] == "SAS"
    assert body["recommended_player"]["prospect"]["id"] == top_prospect.id
    assert body["recommended_player"]["scores"]["final_score"] > 0
    # Exactly one alternative (the other seeded prospect).
    assert len(body["alternatives"]) == 1
    assert body["alternatives"][0]["prospect"]["id"] != top_prospect.id


# ---------------------------------------------------------------------------
# 2. pick #N 不应推荐前序 board 已选走的顶级 prospect
# ---------------------------------------------------------------------------


def test_recommend_pick_3_excludes_pick_2_taken_prospect(
    client: TestClient, db_session: Session,
) -> None:
    """At request pick=3, the prior pick (pick=2 SAS — seeded in
    conftest) auto-selects the top of the SAS board.  The
    recommendation at pick=3 must NOT be that top prospect — the
    available board must reflect prior consumption.

    We don't hardcode the prospect's name: we discover the top
    at pick=1 and then assert it's no longer recommended at
    pick=3.
    """
    # Discover the top prospect dynamically.
    top_prospect = db_session.scalars(
        select(Prospect)
        .where(Prospect.year == 2026)
        .order_by(Prospect.upside_score.desc())
    ).first()
    assert top_prospect is not None

    top_response = client.post(
        "/api/recommend",
        json={"year": 2026, "team": "SAS", "pick": 1, "mode": "gm_decision"},
    )
    assert top_response.status_code == 200
    assert top_response.json()["recommended_player"]["prospect"]["id"] == top_prospect.id

    later_response = client.post(
        "/api/recommend",
        json={"year": 2026, "team": "HOU", "pick": 3, "mode": "gm_decision"},
    )
    assert later_response.status_code == 200
    later_id = later_response.json()["recommended_player"]["prospect"]["id"]

    # The top prospect at pick=1 was auto-selected at pick=2 (SAS),
    # so pick=3 should NOT see them anymore — this proves the
    # board-aware filter is active.
    assert later_id != top_prospect.id
    # And pick=3's recommendation is some other prospect.
    all_prospect_ids = {
        p.id for p in db_session.scalars(
            select(Prospect).where(Prospect.year == 2026)
        )
    }
    assert later_id in all_prospect_ids


# ---------------------------------------------------------------------------
# 3. 如果高天赋球员真的在 available board 里，仍然可以被推荐
#    (this is the critical "we don't punish high-upside droppers" test)
# ---------------------------------------------------------------------------


def test_recommend_can_recommend_high_upside_dropper_in_available_board(
    client: TestClient, db_session: Session,
) -> None:
    """Monkey-patch the helper to return a single high-upside
    "dropper" prospect.  /api/recommend at any pick must recommend
    that prospect unchanged — proving the rank_prospects formula
    never penalises a high-upside prospect for appearing at a low
    pick_no.  The change is purely the *availability filter*, not
    the scoring.
    """
    dropper = db_session.scalars(
        select(Prospect).where(Prospect.year == 2026).order_by(Prospect.upside_score.desc())
    ).first()
    assert dropper is not None  # sanity: conftest has 2 prospects

    other = db_session.scalars(
        select(Prospect).where(
            Prospect.year == 2026,
            Prospect.id != dropper.id,
        )
    ).first()
    assert other is not None

    # /api/recommend at pick=25 (a low pick).  The helper is monkey
    # patched to return [dropper, other] (in that order).  The
    # final ranking should be dropper (upside 86) ranked above
    # other (upside 82) — both untouched, no score penalty.
    with patch(
        "app.services.recommendation_service._compute_available_prospects_for_pick",
        return_value=[dropper, other],
    ):
        response = client.post(
            "/api/recommend",
            json={"year": 2026, "team": "SAS", "pick": 25, "mode": "gm_decision"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["team"]["abbr"] == "SAS"
    # The dropper is the top recommended — and crucially, its
    # final_score is the *same* formula result as if it had been
    # at pick=1.  We don't check the exact number; we check that
    # the helper's return value flows unchanged to the final
    # ranking.  The dropper has the highest upside, so it ranks
    # first in any reasonable ``rank_prospects`` call.
    assert body["recommended_player"]["prospect"]["id"] == dropper.id
    # And the dropped prospect's score is *not* reduced by being
    # associated with pick=25 — it would be the same at pick=1.
    # We only assert the score is positive, not the exact value,
    # so the test is robust against future formula tweaks.
    dropper_scores = body["recommended_player"]["scores"]
    assert dropper_scores["final_score"] > 0
    assert dropper_scores["talent_score"] > 0
    # The dropper ranks above the other prospect (which has
    # strictly lower upside_score) — confirming the formula
    # does NOT penalise high-upside prospects at low pick
    # numbers.  The dropper is the top, not the alternative.
    assert len(body["alternatives"]) == 1
    assert body["alternatives"][0]["prospect"]["id"] == other.id


# ---------------------------------------------------------------------------
# 4. /api/simulate behavior is unchanged
# ---------------------------------------------------------------------------


def test_recommend_does_not_change_simulate(client: TestClient) -> None:
    """Smoke test: the recommend path change must not affect
    /api/simulate.  A simple 1-pick simulation should still
    return a pick for SAS (pick=2).

    M4-CL: Previously asserted 2 picks (SAS #2 + HOU #5), but
    Braylon Mullins is now in the return-to-school unavailable
    set, leaving only 1 available prospect in the conftest seed.
    /api/simulate respects the availability guard, so it can
    only fill 1 of the 2 draft slots.  The test now asserts 1
    pick — the smoke intent (recommend path doesn't break
    simulate) is preserved.
    """
    response = client.post(
        "/api/simulate",
        json={"year": 2026, "rounds": 1, "limit": 2, "evaluate_trades": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["picks"]) == 1
    assert body["picks"][0]["team"]["abbr"] == "SAS"
    assert body["picks"][0]["pick"] == 2
    # selected_player is still deterministic — must come from
    # rank_prospects on the live available board, not from
    # news / market context (Phase 5B-M1 invariant).
    for pick in body["picks"]:
        assert pick["selected_player"]["prospect"]["name"]
        assert pick["selected_player"]["scores"]["final_score"] > 0


# ---------------------------------------------------------------------------
# 5. ranking_engine is not modified by the recommend path
# ---------------------------------------------------------------------------


def test_recommend_uses_ranking_engine_on_filtered_pool(
    client: TestClient, db_session: Session,
) -> None:
    """``rank_prospects`` is the *only* ranking function on the
    recommend path.  The change is the *input* pool: smaller
    after the prior-board filter.  We assert (a) the module-level
    import is still the ranking_engine version, and (b) the
    final ``rank_prospects`` call receives a strictly smaller
    input pool than the unfiltered prospect list.
    """
    from app.services import recommendation_service as rec

    assert rec.rank_prospects.__module__ == "app.services.ranking_engine"

    total_prospects = len(
        list(db_session.scalars(select(Prospect).where(Prospect.year == 2026)))
    )
    assert total_prospects >= 2

    # When pick=1, the available board is the full list — the
    # helper returns all prospects.  When pick=3 (with prior
    # pick=2 in conftest), the helper consumes 1, so the final
    # rank_prospects input is total_prospects - 1.
    available_for_pick_3 = rec._compute_available_prospects_for_pick(
        db=db_session, year=2026, pick_no=3,
    )
    assert len(available_for_pick_3) == total_prospects - 1

    # Capture the final call's input pool via a recorder.  We
    # explicitly do NOT assert ``call_count == 1`` — board-aware
    # recommend calls ``rank_prospects`` once per prior draft
    # pick (the prior-board walk) plus once for the user's pick.
    # We only assert that the *last* call (the one feeding
    # ``recommended_player``) receives the *filtered* pool.
    original = rec.rank_prospects
    real_calls: list = []

    def recorder(*args, **kwargs):
        real_calls.append({
            "pick_no": kwargs.get("pick_no"),
            "prospects": kwargs.get("prospects"),
        })
        return original(*args, **kwargs)

    with patch(
        "app.services.recommendation_service.rank_prospects",
        side_effect=recorder,
    ):
        response = client.post(
            "/api/recommend",
            json={"year": 2026, "team": "HOU", "pick": 3, "mode": "gm_decision"},
        )
    assert response.status_code == 200
    # The last call is the user's pick — it must be at pick=3
    # and have the *filtered* pool.
    last = real_calls[-1]
    assert last["pick_no"] == 3
    assert len(last["prospects"]) == total_prospects - 1
    # And the response's recommended_player must be a real prospect.
    assert response.json()["recommended_player"]["prospect"]["id"] in {
        p.id for p in last["prospects"]
    }


# ---------------------------------------------------------------------------
# 6. Existing behaviors preserved
# ---------------------------------------------------------------------------


def test_recommend_pick_by_team_abbr(client: TestClient) -> None:
    """Regression: pre-Phase 6B-M1 happy path.  pick=2 has no
    prior picks in the conftest seed (draft_order starts at 2),
    so the available board is the full prospect list.
    """
    response = client.post(
        "/api/recommend",
        json={
            "year": 2026,
            "team": "SAS",
            "pick": 2,
            "mode": "gm_decision",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["team"]["abbr"] == "SAS"
    assert body["recommended_player"]["scores"]["final_score"] > 0
    assert len(body["alternatives"]) == 1
    assert body["recommended_player"]["reasons"]


def test_recommend_requires_team(client: TestClient) -> None:
    """Regression: 422 if neither team_id nor team is given."""
    response = client.post("/api/recommend", json={"year": 2026, "pick": 8})

    assert response.status_code == 422
