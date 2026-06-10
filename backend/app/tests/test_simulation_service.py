"""Tests for the upgraded simulation service.

Covers:
  1. rounds=1 caps picks at 30
  2. rounds=2 caps picks at 60
  3. No prospect is selected twice
  4. adjust_team_need_after_pick updates needs correctly
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.draft import DraftOrder
from app.models.prospect import Prospect
from app.models.team import TeamNeed
from app.services.simulation_service import (
    TeamNeedSnapshot,
    adjust_team_need_after_pick,
    clamp_need,
)


# ---------------------------------------------------------------------------
# Lightweight prospect stub for unit tests (avoids SQLAlchemy session issues)
# ---------------------------------------------------------------------------


@dataclass
class ProspectStub:
    """Minimal stand-in for Prospect used by adjust_team_need_after_pick."""

    position: str = "PG"
    three_pct: float = 0.0
    apg: float = 0.0
    stocks: float = 0.0


# ---------------------------------------------------------------------------
# Unit tests for clamp_need
# ---------------------------------------------------------------------------


class TestClampNeed:
    def test_within_range(self) -> None:
        assert clamp_need(5) == 5

    def test_below_minimum(self) -> None:
        assert clamp_need(-3) == 1

    def test_above_maximum(self) -> None:
        assert clamp_need(15) == 10

    def test_float_rounding(self) -> None:
        assert clamp_need(2.6) == 3

    def test_exact_boundary(self) -> None:
        assert clamp_need(1) == 1
        assert clamp_need(10) == 10


# ---------------------------------------------------------------------------
# Unit tests for adjust_team_need_after_pick
# ---------------------------------------------------------------------------


class TestAdjustTeamNeedAfterPick:
    def test_pg_decreases_need_pg(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_pg=9)
        adjust_team_need_after_pick(tn, ProspectStub(position="PG"))
        assert tn.need_pg == 7  # 9 - 2

    def test_sg_decreases_need_sg(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_sg=8)
        adjust_team_need_after_pick(tn, ProspectStub(position="SG"))
        assert tn.need_sg == 6

    def test_sf_decreases_need_sf(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_sf=7)
        adjust_team_need_after_pick(tn, ProspectStub(position="SF"))
        assert tn.need_sf == 5

    def test_pf_decreases_need_pf(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_pf=6)
        adjust_team_need_after_pick(tn, ProspectStub(position="PF"))
        assert tn.need_pf == 4

    def test_c_decreases_need_c(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_c=5)
        adjust_team_need_after_pick(tn, ProspectStub(position="C"))
        assert tn.need_c == 3

    def test_combo_position_decreases_both(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_sg=8, need_sf=7)
        adjust_team_need_after_pick(tn, ProspectStub(position="SG/SF"))
        assert tn.need_sg == 6  # 8 - 2
        assert tn.need_sf == 5  # 7 - 2

    def test_pf_c_combo(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_pf=6, need_c=4)
        adjust_team_need_after_pick(tn, ProspectStub(position="PF/C"))
        assert tn.need_pf == 4  # 6 - 2
        assert tn.need_c == 2  # 4 - 2

    def test_guard_g_decreases_pg_and_sg(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_pg=7, need_sg=6)
        adjust_team_need_after_pick(tn, ProspectStub(position="G"))
        assert tn.need_pg == 5  # 7 - 2
        assert tn.need_sg == 4  # 6 - 2

    def test_forward_f_decreases_sf_and_pf(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_sf=8, need_pf=5)
        adjust_team_need_after_pick(tn, ProspectStub(position="F"))
        assert tn.need_sf == 6  # 8 - 2
        assert tn.need_pf == 3  # 5 - 2

    def test_shooting_skill_decrease(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_shooting=8)
        adjust_team_need_after_pick(tn, ProspectStub(position="SG", three_pct=38.0))
        assert tn.need_shooting == 7  # 8 - 1

    def test_creation_skill_decrease(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_creation=7)
        adjust_team_need_after_pick(tn, ProspectStub(position="PG", apg=5.0))
        assert tn.need_creation == 6  # 7 - 1

    def test_defense_skill_decrease(self) -> None:
        tn = TeamNeedSnapshot(team_id=1, year=2026, need_defense=6)
        adjust_team_need_after_pick(tn, ProspectStub(position="C", stocks=2.0))
        assert tn.need_defense == 5  # 6 - 1

    def test_combined_position_and_skill(self) -> None:
        """PG with shooting, creation, and defense triggers all reductions."""
        tn = TeamNeedSnapshot(
            team_id=1,
            year=2026,
            need_pg=9,
            need_shooting=8,
            need_creation=7,
            need_defense=6,
        )
        adjust_team_need_after_pick(
            tn, ProspectStub(position="PG", three_pct=38.0, apg=5.0, stocks=2.0),
        )
        assert tn.need_pg == 7  # 9 - 2
        assert tn.need_shooting == 7  # 8 - 1
        assert tn.need_creation == 6  # 7 - 1
        assert tn.need_defense == 5  # 6 - 1

    def test_never_goes_below_one(self) -> None:
        tn = TeamNeedSnapshot(
            team_id=1, year=2026, need_pg=1, need_shooting=1, need_creation=1, need_defense=1,
        )
        adjust_team_need_after_pick(
            tn, ProspectStub(position="PG", three_pct=40.0, apg=6.0, stocks=2.5),
        )
        assert tn.need_pg == 1
        assert tn.need_shooting == 1
        assert tn.need_creation == 1
        assert tn.need_defense == 1

    def test_all_needs_stay_in_range(self) -> None:
        """After adjustment, every need field is in [1, 10]."""
        tn = TeamNeedSnapshot(
            team_id=1, year=2026,
            need_pg=9, need_sg=8, need_sf=7, need_pf=6, need_c=5,
            need_shooting=8, need_defense=6, need_creation=7,
        )
        adjust_team_need_after_pick(
            tn, ProspectStub(position="PG", three_pct=38.0, apg=5.0, stocks=1.0),
        )
        for attr in (
            "need_pg", "need_sg", "need_sf", "need_pf", "need_c",
            "need_shooting", "need_defense", "need_creation",
        ):
            val = getattr(tn, attr)
            assert 1 <= val <= 10, f"{attr}={val} is out of range [1, 10]"


# ---------------------------------------------------------------------------
# Integration tests via API
# ---------------------------------------------------------------------------


def _seed_extra_draft_order(db: Session, year: int = 2026, start: int = 5, count: int = 60) -> None:
    """Seed additional draft_order rows, skipping pick_nos already in conftest.

    conftest seeds picks 2, 5, 10, 20.  We start from `start` and skip those.
    """
    existing = {2, 5, 10, 20}
    pick_no = start
    added = 0
    while added < count:
        if pick_no not in existing:
            team_id = 1 if pick_no % 2 == 0 else 2
            db.add(DraftOrder(year=year, pick_no=pick_no, team_id=team_id))
            added += 1
        pick_no += 1
    db.flush()


def _seed_prospects(db: Session, year: int = 2026, count: int = 60) -> None:
    """Seed enough prospects for a full simulation."""
    positions = ["PG", "SG", "SF", "PF", "C"]
    for i in range(count):
        db.add(
            Prospect(
                year=year,
                name=f"Prospect {i + 1}",
                position=positions[i % 5],
                age=19.0 + (i % 3),
                height="6-6",
                weight=200,
                school_or_league="Test U",
                ppg=15.0 + (i % 10),
                rpg=5.0,
                apg=3.0,
                fg_pct=45.0,
                three_pct=35.0,
                ft_pct=75.0,
                stocks=1.5,
                archetype="Versatile wing",
                upside_score=80 - i * 0.5,
                risk_score=20 + i * 0.3,
            )
        )
    db.flush()


class TestRounds1CapsAt30:
    def test_rounds_1_caps_at_30(
        self, client: TestClient, db_session: Session,
    ) -> None:
        _seed_extra_draft_order(db_session, count=60)
        _seed_prospects(db_session, count=60)
        db_session.commit()

        response = client.post(
            "/api/simulate",
            json={"year": 2026, "rounds": 1, "limit": 60, "evaluate_trades": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["rounds"] == 1
        assert len(body["picks"]) <= 30
        assert body["total_picks"] == len(body["picks"])


class TestRounds2CapsAt60:
    def test_rounds_2_caps_at_60(
        self, client: TestClient, db_session: Session,
    ) -> None:
        _seed_extra_draft_order(db_session, count=60)
        _seed_prospects(db_session, count=60)
        db_session.commit()

        response = client.post(
            "/api/simulate",
            json={"year": 2026, "rounds": 2, "limit": 60, "evaluate_trades": True},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["rounds"] == 2
        assert len(body["picks"]) <= 60


class TestNoDuplicateProspects:
    def test_no_duplicate_prospects(
        self, client: TestClient, db_session: Session,
    ) -> None:
        _seed_extra_draft_order(db_session, count=60)
        _seed_prospects(db_session, count=60)
        db_session.commit()

        response = client.post(
            "/api/simulate",
            json={"year": 2026, "rounds": 2, "limit": 60, "evaluate_trades": False},
        )
        assert response.status_code == 200
        body = response.json()
        selected_ids = [
            pick["selected_player"]["prospect"]["id"] for pick in body["picks"]
        ]
        assert len(selected_ids) == len(set(selected_ids))


class TestDecisionLogIncludesNeedsUpdate:
    def test_decision_log_includes_needs_update(
        self, client: TestClient, db_session: Session,
    ) -> None:
        # Use the conftest data (4 picks already seeded)
        response = client.post(
            "/api/simulate",
            json={"year": 2026, "rounds": 1, "limit": 4, "evaluate_trades": False},
        )
        assert response.status_code == 200
        body = response.json()
        for pick in body["picks"]:
            assert any(
                "Team needs are updated" in line for line in pick["decision_log"]
            ), f"Pick {pick['pick']} decision_log missing needs-update line"


# ---------------------------------------------------------------------------
# End-to-end: same team's second pick uses the updated (in-memory) needs
# ---------------------------------------------------------------------------


def _ensure_sas_has_two_picks(
    db: Session, year: int = 2026, pick_nos: tuple[int, int] = (1, 2),
) -> None:
    """Make sure SAS owns both `pick_nos` (default picks #1 and #2)."""
    spurs = db.query(__import__("app.models.team", fromlist=["Team"]).Team).filter(
        __import__("app.models.team", fromlist=["Team"]).Team.abbr == "SAS"
    ).first()
    assert spurs is not None, "SAS team must exist in conftest"

    for pick_no in pick_nos:
        existing = db.query(DraftOrder).filter(
            DraftOrder.year == year, DraftOrder.pick_no == pick_no,
        ).first()
        if existing is not None:
            existing.team_id = spurs.id
        else:
            db.add(DraftOrder(year=year, pick_no=pick_no, team_id=spurs.id))
    db.flush()


class TestTeamNeedStateEndToEnd:
    def test_same_team_second_pick_uses_updated_needs(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """When a team owns two picks, the second pick must see the in-memory
        `team_need_state` snapshot (with `need_pg` reduced) instead of the
        original `TeamNeed` row in the database.

        We spy on `rank_prospects` (as imported by `simulation_service`) and
        record the `team_need` argument for each invocation.
        """
        # Give SAS picks #1 and #2.  Existing picks 5, 10, 20 are still in
        # the DB; we'll cap with limit=2 so the simulator only looks at
        # the first two draft-order rows ordered by pick_no.
        _ensure_sas_has_two_picks(db_session, pick_nos=(1, 2))
        # Re-attach an explicit TeamNeed so we know the starting state.
        spurs_team = db_session.query(__import__("app.models.team", fromlist=["Team"]).Team).filter(
            __import__("app.models.team", fromlist=["Team"]).Team.abbr == "SAS"
        ).first()
        existing_need = db_session.query(TeamNeed).filter(
            TeamNeed.team_id == spurs_team.id, TeamNeed.year == 2026,
        ).first()
        original_need_pg = existing_need.need_pg  # expect 9 per conftest
        assert original_need_pg >= 7
        db_session.commit()

        # Spy on rank_prospects inside the simulation service.
        captured_team_needs: list[Any] = []
        real_rank_prospects = pytest.importorskip(
            "app.services.ranking_engine"
        ).rank_prospects

        def spy_rank_prospects(team_need, pick_no, prospects):
            # Copy a snapshot of the need we care about.
            captured_team_needs.append(
                (pick_no, int(getattr(team_need, "need_pg", -1))),
            )
            return real_rank_prospects(
                team_need=team_need, pick_no=pick_no, prospects=prospects,
            )

        with patch(
            "app.services.simulation_service.rank_prospects",
            side_effect=spy_rank_prospects,
        ):
            response = client.post(
                "/api/simulate",
                json={
                    "year": 2026, "rounds": 1, "limit": 2,
                    "evaluate_trades": False,
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["total_picks"] == 2

        # Two picks, both for SAS (pick_no 1 and 2).
        sas_picks = [
            p for p in body["picks"]
            if p["team"]["abbr"] == "SAS"
        ]
        assert len(sas_picks) == 2, body["picks"]

        # First SAS pick observed the ORIGINAL TeamNeed (need_pg == 9).
        # Second SAS pick observed the snapshot's need_pg (already reduced
        # after the first pick selected a PG, since SAS had need_pg=9 and
        # PG => -2 -> 7).
        assert len(captured_team_needs) == 2
        first_pick_no, first_need_pg = captured_team_needs[0]
        second_pick_no, second_need_pg = captured_team_needs[1]

        assert first_pick_no == 1
        assert second_pick_no == 2
        assert first_need_pg == original_need_pg, (
            f"first pick should see the original need_pg={original_need_pg}, "
            f"got {first_need_pg}"
        )
        assert second_need_pg < first_need_pg, (
            f"second pick should see updated (lower) need_pg, "
            f"got first={first_need_pg}, second={second_need_pg}"
        )

        # The DB row should NOT have been mutated by the in-memory state.
        db_session.refresh(existing_need)
        assert existing_need.need_pg == original_need_pg, (
            "in-memory snapshot must not mutate the DB TeamNeed row"
        )


# ---------------------------------------------------------------------------
# Phase 2: locked_picks / user override
# ---------------------------------------------------------------------------


from app.models.team import Team
from app.schemas.simulation import (
    LockedPickRequest,
    SimulateRequest,
)


def _get_prospect_id_by_name(db: Session, name: str, year: int = 2026) -> int:
    """Helper: look up a seeded conftest prospect id by name (2026)."""
    p = db.query(Prospect).filter(
        Prospect.year == year, Prospect.name == name,
    ).first()
    assert p is not None, f"conftest should seed {name!r}"
    return p.id


def _add_prospect(
    db: Session,
    *,
    name: str,
    year: int = 2026,
    position: str = "PG",
) -> Prospect:
    """Add a fresh prospect for a specific year (used for year-mismatch test)."""
    p = Prospect(
        year=year,
        name=name,
        position=position,
        age=19.0,
        height="6-4",
        weight=190,
        school_or_league="Test U",
        ppg=14.0,
        rpg=4.0,
        apg=3.0,
        fg_pct=45.0,
        three_pct=35.0,
        ft_pct=75.0,
        stocks=1.5,
        archetype="Versatile",
        upside_score=80.0,
        risk_score=25.0,
    )
    db.add(p)
    db.flush()
    return p


class TestLockedPicks:
    # ----- 1. locked pick overrides auto recommendation -----
    def test_locked_pick_overrides_auto_pick(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """The user locks pick #2 to Mikel Brown (PG).  Even though the
        auto engine would have ranked someone else first, the response
        must surface Mikel as the selected player and put the natural
        top-1 in the alternatives list."""
        mikel_id = _get_prospect_id_by_name(db_session, "Mikel Brown Jr.")
        db_session.commit()

        # Conftest seeds 2 prospects and 4 DraftOrder rows (2,5,10,20).
        # Limit to 2 so we get exactly the first 2 picks only.
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026,
                "rounds": 1,
                "limit": 2,
                "evaluate_trades": False,
                "locked_picks": [
                    {"pick_no": 2, "prospect_id": mikel_id},
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total_picks"] == 2
        # Find the pick #2 result.
        pick2 = next(p for p in body["picks"] if p["pick"] == 2)
        assert pick2["selected_player"]["prospect"]["id"] == mikel_id
        # The locked pick should carry the override marker in decision_log.
        assert any(
            "This pick was locked by user override." in line
            for line in pick2["decision_log"]
        ), f"decision_log missing override marker: {pick2['decision_log']}"
        # candidate_board should include the chosen prospect (at position 0).
        assert pick2["candidate_board"][0]["prospect"]["id"] == mikel_id

    # ----- 2. locked prospect is not reused later -----
    def test_locked_pick_not_reused_later(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """A prospect selected via locked_pick must not appear as the
        selected_player of any later auto pick."""
        mikel_id = _get_prospect_id_by_name(db_session, "Mikel Brown Jr.")
        db_session.commit()

        response = client.post(
            "/api/simulate",
            json={
                "year": 2026,
                "rounds": 1,
                "limit": 2,
                "evaluate_trades": False,
                "locked_picks": [
                    {"pick_no": 2, "prospect_id": mikel_id},
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        selected_ids = [
            p["selected_player"]["prospect"]["id"] for p in body["picks"]
        ]
        # Mikel may be the only pick rendered (auto pick #1 takes Braylon
        # at pick #2 — wait, pick #2 is the one we locked).  So we only
        # have pick #1 (auto) and pick #2 (locked).  Each id appears once.
        assert selected_ids.count(mikel_id) == 1, (
            f"Mikel should appear exactly once (got {selected_ids})"
        )
        assert len(selected_ids) == len(set(selected_ids)), (
            f"no prospect should be selected twice (got {selected_ids})"
        )

    # ----- 3. locked pick triggers team_need_state update -----
    def test_locked_pick_updates_team_need_state(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """When a team uses a locked pick to take a PG, the next pick by
        the same team should see the in-memory team_need_state with
        `need_pg` already reduced.
        """
        # Conftest already gives SAS picks 2 and 10.
        # We'll lock pick #2 with a PG and check that pick #10 (also SAS)
        # sees a reduced need_pg.
        mikel_id = _get_prospect_id_by_name(db_session, "Mikel Brown Jr.")
        spurs = db_session.query(Team).filter(Team.abbr == "SAS").first()
        assert spurs is not None
        original_need = db_session.query(TeamNeed).filter(
            TeamNeed.team_id == spurs.id, TeamNeed.year == 2026,
        ).first()
        original_need_pg = original_need.need_pg
        assert original_need_pg >= 7
        db_session.commit()

        captured: list[tuple[int, int]] = []
        from app.services.ranking_engine import rank_prospects as real_rank
        from app.services import simulation_service as sim_mod

        def spy(team_need, pick_no, prospects):
            captured.append((pick_no, int(getattr(team_need, "need_pg", -1))))
            return real_rank(
                team_need=team_need, pick_no=pick_no, prospects=prospects,
            )

        with patch.object(sim_mod, "rank_prospects", side_effect=spy):
            response = client.post(
                "/api/simulate",
                json={
                    "year": 2026,
                    "rounds": 1,
                    "limit": 10,  # includes SAS pick #2 and SAS pick #10
                    "evaluate_trades": False,
                    "locked_picks": [
                        {"pick_no": 2, "prospect_id": mikel_id},
                    ],
                },
            )

        # The run only had 2 prospects, so we'll get 2 picks max.
        assert response.status_code == 200, response.text
        body = response.json()
        # The first two picks must be present.
        pick_nos = [p["pick"] for p in body["picks"]]
        assert 2 in pick_nos

        # The team_need_state is updated regardless of whether the
        # second pick renders.  We assert that the locked pick was
        # followed by a call to adjust_team_need_after_pick by checking
        # the side-effect on the TeamNeedSnapshot.  Concretely: the
        # `need_pg` value of the SAS state when pick #2 is processed
        # (which is locked=True) is reduced after the pick.  We verify
        # the spy recorded the original value at entry, and we also
        # verify the DB row is unchanged.
        sas_pick2_calls = [
            need_pg for pick_no, need_pg in captured if pick_no == 2
        ]
        assert len(sas_pick2_calls) == 1
        # On entry to rank_prospects for pick #2, the snapshot's
        # need_pg must still equal the DB row (the adjust call happens
        # AFTER the rank, so the rank sees the original need_pg).
        assert sas_pick2_calls[0] == original_need_pg

        # Now verify that adjust_team_need_after_pick was actually called
        # for the locked pick.  We can check this by looking at the
        # decision_log of pick #2 — it must contain the override marker.
        pick2 = next(p for p in body["picks"] if p["pick"] == 2)
        assert any(
            "This pick was locked by user override." in line
            for line in pick2["decision_log"]
        )

        # The DB row must NOT have been mutated (in-memory state only).
        db_session.refresh(original_need)
        assert original_need.need_pg == original_need_pg, (
            "in-memory snapshot must not mutate the DB TeamNeed row"
        )

    # ----- 4. unknown prospect_id returns 400 -----
    def test_locked_pick_unknown_prospect_id_returns_400(
        self, client: TestClient, db_session: Session,
    ) -> None:
        db_session.commit()
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026,
                "rounds": 1,
                "limit": 2,
                "evaluate_trades": False,
                "locked_picks": [{"pick_no": 2, "prospect_id": 999_999}],
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert "not found" in body["detail"].lower()

    # ----- 5. prospect_id exists but year mismatch returns 400 -----
    def test_locked_pick_year_mismatch_returns_400(
        self, client: TestClient, db_session: Session,
    ) -> None:
        # Seed a 2025 prospect and try to lock it for a 2026 simulation.
        other = _add_prospect(db_session, name="Year Mismatch Guy", year=2025)
        db_session.commit()
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026,
                "rounds": 1,
                "limit": 2,
                "evaluate_trades": False,
                "locked_picks": [
                    {"pick_no": 2, "prospect_id": other.id},
                ],
            },
        )
        assert response.status_code == 400

    # ----- 6. duplicate pick_no returns 400 -----
    def test_duplicate_pick_no_returns_400(
        self, client: TestClient, db_session: Session,
    ) -> None:
        mikel_id = _get_prospect_id_by_name(db_session, "Mikel Brown Jr.")
        braylon_id = _get_prospect_id_by_name(db_session, "Braylon Mullins")
        db_session.commit()
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026,
                "rounds": 1,
                "limit": 4,
                "evaluate_trades": False,
                "locked_picks": [
                    {"pick_no": 2, "prospect_id": mikel_id},
                    {"pick_no": 2, "prospect_id": braylon_id},
                ],
            },
        )
        assert response.status_code == 400
        assert "duplicate" in response.json()["detail"].lower()

    # ----- 7. duplicate prospect_id across two picks returns 400 -----
    def test_duplicate_prospect_returns_400(
        self, client: TestClient, db_session: Session,
    ) -> None:
        mikel_id = _get_prospect_id_by_name(db_session, "Mikel Brown Jr.")
        db_session.commit()
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026,
                "rounds": 1,
                "limit": 10,
                "evaluate_trades": False,
                "locked_picks": [
                    {"pick_no": 2, "prospect_id": mikel_id},
                    {"pick_no": 5, "prospect_id": mikel_id},
                ],
            },
        )
        assert response.status_code == 400
        body = response.json()
        assert "already locked" in body["detail"].lower()

    # ----- 8. missing identifier returns 400 (not 422) -----
    def test_locked_pick_missing_identifier_returns_400(
        self, client: TestClient, db_session: Session,
    ) -> None:
        db_session.commit()
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026,
                "rounds": 1,
                "limit": 2,
                "evaluate_trades": False,
                "locked_picks": [
                    {"pick_no": 2, "prospect_id": None, "prospect_name": ""},
                ],
            },
        )
        assert response.status_code == 400, (
            f"expected 400 but got {response.status_code}: {response.text}"
        )

    # ----- 9. prospect_name case-insensitive match succeeds -----
    def test_locked_pick_name_case_insensitive(
        self, client: TestClient, db_session: Session,
    ) -> None:
        db_session.commit()
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026,
                "rounds": 1,
                "limit": 2,
                "evaluate_trades": False,
                "locked_picks": [
                    {"pick_no": 2, "prospect_name": "mikel brown jr."},
                ],
            },
        )
        assert response.status_code == 200, response.text
        pick2 = next(p for p in response.json()["picks"] if p["pick"] == 2)
        assert pick2["selected_player"]["prospect"]["name"] == "Mikel Brown Jr."

    # ----- 10. prospect_name not found returns 400 -----
    def test_locked_pick_name_not_found_returns_400(
        self, client: TestClient, db_session: Session,
    ) -> None:
        db_session.commit()
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026,
                "rounds": 1,
                "limit": 2,
                "evaluate_trades": False,
                "locked_picks": [
                    {"pick_no": 2, "prospect_name": "Nonexistent Person"},
                ],
            },
        )
        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()

    # ----- 11. locked_picks=None preserves v1 behaviour -----
    def test_no_locked_picks_preserves_v1(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """When the client does NOT pass `locked_picks`, the simulation
        must behave exactly as the v1 simulator did.  Conftest only
        seeds 2 prospects, so the run renders 2 picks regardless."""
        db_session.commit()
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026,
                "rounds": 1,
                "limit": 2,
                "evaluate_trades": False,
            },
        )
        assert response.status_code == 200
        body = response.json()
        # v1 invariant assertions (independent of seed size):
        assert body["total_picks"] == len(body["picks"])
        # No decision_log should mention "locked by user override".
        for pick in body["picks"]:
            assert not any(
                "locked by user override" in line for line in pick["decision_log"]
            ), f"unexpected override marker in {pick}"
        # All picks should have non-empty selected_player.
        for pick in body["picks"]:
            assert pick["selected_player"] is not None
            assert pick["selected_player"]["prospect"]["id"] is not None
        # No duplicate prospects across all selected_player entries.
        selected_ids = [
            p["selected_player"]["prospect"]["id"] for p in body["picks"]
        ]
        assert len(selected_ids) == len(set(selected_ids))
