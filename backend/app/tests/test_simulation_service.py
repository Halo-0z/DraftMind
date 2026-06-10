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
