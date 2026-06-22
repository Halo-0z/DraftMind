"""M4-CF: Draft-Day Accuracy Mode tests.

Tests cover:
  1. Default ``draft_day_accuracy_mode=False`` keeps Auto Simulation unchanged.
  2. ``draft_day_accuracy_mode=True`` selects unique players (no duplicates).
  3. ``draft_day_accuracy_mode=True`` does not select withdrawn / unavailable.
  4. Safety anchors (Brayden / Yaxel / Cameron) stay in range.
     (Niko Bundalo anchor CANCELLED in M4-CL — he is now unavailable.)
  5. Market-risk players are improved (selected / earlier) vs default mode.
  6. API accepts ``draft_day_accuracy_mode`` and returns ``mode`` identifier.
  7. Default API call (no field) still passes.
  8. M4-CL: return-to-school / not-final-entrant players are not selected.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.draft import DraftOrder
from app.models.projection import ProspectDraftProjection
from app.models.prospect import Prospect
from app.models.team import Team
from scripts import seed_db


# ---------------------------------------------------------------------------
# Test data: safety anchors + market-risk + withdrawn prospects
# ---------------------------------------------------------------------------

# (name, position, upside_score, expected_pick, range_min, range_max, tier)
# M4-CL: Niko Bundalo anchor CANCELLED — he is now in the return-to-school /
# not-final-entrant unavailable set, so he can no longer be a safety anchor.
_SAFETY_ANCHOR_SPECS: tuple[tuple[str, str, float, int, int, int, int], ...] = (
    ("Brayden Burries", "SG", 84.0, 10, 8, 13, 3),
    ("Yaxel Lendeborg", "PF", 82.0, 12, 11, 14, 3),
    ("Cameron Carr", "PG", 75.0, 14, 12, 17, 3),
)

# Market-risk players from M4-CE section 7. These are players S0 misses or
# slides; S1 should select them (or select them earlier).
_MARKET_RISK_SPECS: tuple[tuple[str, str, float, int, int, int, int], ...] = (
    # (name, position, upside_score, expected_pick, range_min, range_max, tier)
    ("Kingston Flemings", "PG", 78.0, 7, 5, 12, 2),
    ("Hannes Steinbach", "C", 70.0, 13, 10, 20, 3),
    ("Christian Anderson", "PG", 72.0, 19, 15, 25, 4),
    ("Aday Mara", "C", 74.0, 8, 5, 14, 2),
    ("Dailyn Swain", "SF", 71.0, 18, 14, 24, 4),
    ("Henri Veesaar", "PF", 69.0, 22, 18, 30, 4),
    ("Alex Karaban", "PF", 68.0, 27, 22, 35, 5),
    ("Tarris Reed Jr.", "C", 70.0, 26, 20, 34, 5),
)

_WITHDRAWN_NAMES: tuple[str, ...] = (
    "Tounde Yessoufou",
    "Isiah Harwell",
    "Malachi Moreno",
    "Bassala Bagayoko",
    "Marc-Owen Fodzo Dada",
    "Pavle Backo",
    "Francesco Ferrari",
    "Luigi Suigo",
)

# M4-CL: return-to-school / not-in-final-early-entry unavailable names.
# These underclass / return-to-school / transfer players are not draftable
# for the 2026 NBA Draft final board and must be filtered out by the
# availability guard before S1 selection.
_RETURN_TO_SCHOOL_NAMES: tuple[str, ...] = (
    "Cayden Boozer",
    "Braylon Mullins",
    "Nikolas Khamenia",
    "Jasper Johnson",
    "Niko Bundalo",
)

# M4-CL: projections for return-to-school players. These are seeded into
# the test fixture WITH attractive projections (matching the positions
# where the buggy final board originally selected them) so that S1 would
# WANT to pick them. The availability guard must filter them out before
# S1 selection, proving the guard overrides the S1 temptation.
# (name, position, upside_score, expected_pick, range_min, range_max, tier)
_RETURN_TO_SCHOOL_SPECS: tuple[tuple[str, str, float, int, int, int, int], ...] = (
    ("Braylon Mullins", "SG", 76.0, 13, 10, 18, 3),
    ("Nikolas Khamenia", "PF", 74.0, 21, 18, 25, 4),
    ("Cayden Boozer", "PG", 75.0, 25, 20, 30, 4),
    ("Jasper Johnson", "SG", 72.0, 29, 25, 34, 5),
    ("Niko Bundalo", "PF", 73.0, 33, 28, 38, 5),
)

# Combined unavailable names (withdrawn + return-to-school) for tests that
# want to assert NONE of these are selected.
_UNAVAILABLE_NAMES: tuple[str, ...] = _WITHDRAWN_NAMES + _RETURN_TO_SCHOOL_NAMES


def _clear_2026_draft_order(db: Session) -> None:
    db.query(DraftOrder).filter(DraftOrder.year == 2026).delete(
        synchronize_session=False
    )
    db.flush()


def _seed_extra_draft_order(db: Session, count: int = 60) -> None:
    """Seed draft_order rows 1..count using the teams from seed_demo_data.

    Skips any (year, pick_no) rows that already exist so we don't violate
    the UNIQUE constraint on (year, pick_no) when seed_demo_data has
    already inserted picks 1..20.
    """
    teams = db.query(Team).order_by(Team.id).all()
    if not teams:
        return
    existing_pick_nos = {
        row[0]
        for row in db.query(DraftOrder.pick_no)
        .filter(DraftOrder.year == 2026)
        .all()
    }
    for pick_no in range(1, count + 1):
        if pick_no in existing_pick_nos:
            continue
        team = teams[(pick_no - 1) % len(teams)]
        db.add(DraftOrder(year=2026, pick_no=pick_no, team_id=team.id))
    db.flush()


def _seed_prospect_with_projection(
    db: Session,
    *,
    name: str,
    position: str,
    upside: float,
    expected: int,
    rmin: int,
    rmax: int,
    tier: int,
    risk: float = 20.0,
) -> Prospect:
    existing = (
        db.query(Prospect)
        .filter(Prospect.year == 2026, Prospect.name == name)
        .first()
    )
    if existing is None:
        prospect = Prospect(
            year=2026,
            name=name,
            position=position,
            age=19.0,
            height="6-6",
            weight=200,
            school_or_league="M4-CF U",
            ppg=15.0,
            rpg=5.0,
            apg=3.5,
            fg_pct=46.0,
            three_pct=36.0,
            ft_pct=78.0,
            stocks=1.5,
            archetype="Versatile",
            upside_score=upside,
            risk_score=risk,
        )
        db.add(prospect)
        db.flush()
    else:
        prospect = existing
        prospect.upside_score = upside
        prospect.risk_score = risk

    proj = (
        db.query(ProspectDraftProjection)
        .filter_by(
            prospect_id=prospect.id,
            year=2026,
            source="manual_projection",
        )
        .first()
    )
    payload = {
        "prospect_id": prospect.id,
        "year": 2026,
        "consensus_rank": expected,
        "big_board_rank": expected,
        "expected_pick": expected,
        "draft_range_min": rmin,
        "draft_range_max": rmax,
        "tier": tier,
        "source": "manual_projection",
        "source_count": 1,
        "confidence": 0.65,
        "notes": "M4-CF test projection",
    }
    if proj is None:
        db.add(ProspectDraftProjection(**payload))
    else:
        for k, v in payload.items():
            setattr(proj, k, v)
    return prospect


def _seed_full_test_fixture(db: Session) -> None:
    """Seed demo data + safety anchors + market-risk + extra draft order.

    M4-CL: also seeds return-to-school / not-final-entrant prospects WITH
    attractive projections. These players are in the DB (so the candidate
    list would include them) but the availability guard must filter them
    out before S1 selection.
    """
    _clear_2026_draft_order(db)
    seed_db.seed_demo_data(db)
    # Overlay safety anchors and market-risk prospects with projections.
    for spec in _SAFETY_ANCHOR_SPECS:
        _seed_prospect_with_projection(
            db,
            name=spec[0], position=spec[1], upside=spec[2],
            expected=spec[3], rmin=spec[4], rmax=spec[5], tier=spec[6],
        )
    for spec in _MARKET_RISK_SPECS:
        _seed_prospect_with_projection(
            db,
            name=spec[0], position=spec[1], upside=spec[2],
            expected=spec[3], rmin=spec[4], rmax=spec[5], tier=spec[6],
        )
    # M4-CL: seed return-to-school players with attractive projections.
    # The availability guard must filter them out before selection.
    for spec in _RETURN_TO_SCHOOL_SPECS:
        _seed_prospect_with_projection(
            db,
            name=spec[0], position=spec[1], upside=spec[2],
            expected=spec[3], rmin=spec[4], rmax=spec[5], tier=spec[6],
        )
    # Ensure draft order covers 60 picks.
    _seed_extra_draft_order(db, count=60)
    db.commit()


def _pick_of(body: dict, name: str) -> int | None:
    for pick in body["picks"]:
        if pick["selected_player"]["prospect"]["name"] == name:
            return pick["pick"]
    return None


def _selected_names(body: dict) -> set[str]:
    return {
        pick["selected_player"]["prospect"]["name"]
        for pick in body["picks"]
    }


# ---------------------------------------------------------------------------
# 1. Default mode unchanged
# ---------------------------------------------------------------------------


class TestDefaultModeUnchanged:
    """When draft_day_accuracy_mode is False / omitted, behaviour is unchanged."""

    def test_default_mode_identifier(
        self, client: TestClient, db_session: Session,
    ) -> None:
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={"year": 2026, "rounds": 1, "limit": 5, "evaluate_trades": False},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["mode"] == "auto_simulation"
        assert body["draft_day_accuracy_mode"] is False

    def test_omitted_field_defaults_false(
        self, client: TestClient, db_session: Session,
    ) -> None:
        _seed_full_test_fixture(db_session)
        # Do NOT pass draft_day_accuracy_mode in the request.
        response = client.post(
            "/api/simulate",
            json={"year": 2026, "rounds": 1, "limit": 5, "evaluate_trades": False},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["draft_day_accuracy_mode"] is False
        assert body["mode"] == "auto_simulation"

    def test_default_and_accuracy_mode_produce_different_boards(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """The opt-in mode must actually change selection (not be a no-op).

        We compare pick-by-pick order, not just the set of selected names:
        if both modes select the same 60 prospects in the same order, the
        S1 policy is a no-op. A difference in ordering (or in the set) is
        enough to prove the mode is wired up.
        """
        _seed_full_test_fixture(db_session)

        default_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
            },
        )
        accuracy_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "draft_day_accuracy_mode": True,
            },
        )
        assert default_resp.status_code == 200
        assert accuracy_resp.status_code == 200
        default_order = [
            pick["selected_player"]["prospect"]["name"]
            for pick in default_resp.json()["picks"]
        ]
        accuracy_order = [
            pick["selected_player"]["prospect"]["name"]
            for pick in accuracy_resp.json()["picks"]
        ]
        # The two boards should differ in order or in set — otherwise the
        # mode is a no-op.
        assert default_order != accuracy_order, (
            "Draft-Day Accuracy Mode produced the same board (same order) "
            "as default Auto Simulation; the S1 policy may not be wired up."
        )


# ---------------------------------------------------------------------------
# 2. Unique players, no duplicates
# ---------------------------------------------------------------------------


class TestUniqueSelections:
    def test_60_pick_no_duplicates(
        self, client: TestClient, db_session: Session,
    ) -> None:
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "draft_day_accuracy_mode": True,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        ids = [
            pick["selected_player"]["prospect"]["id"]
            for pick in body["picks"]
        ]
        assert len(ids) == len(set(ids)), "Duplicate prospect selected"


# ---------------------------------------------------------------------------
# 3. No withdrawn / unavailable players
# ---------------------------------------------------------------------------


class TestNoWithdrawnSelected:
    def test_60_pick_excludes_all_withdrawn(
        self, client: TestClient, db_session: Session,
    ) -> None:
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "draft_day_accuracy_mode": True,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        selected = _selected_names(body)
        for name in _WITHDRAWN_NAMES:
            assert name not in selected, (
                f"Withdrawn player {name!r} was selected in "
                f"Draft-Day Accuracy Mode"
            )


# ---------------------------------------------------------------------------
# 3b. M4-CL: No return-to-school / not-final-entrant players selected
# ---------------------------------------------------------------------------


class TestNoReturnToSchoolSelected:
    """M4-CL: return-to-school / not-final-entrant players must NOT be
    selected in any simulation mode.

    These players are not draftable for the 2026 NBA Draft final board:
      * Cayden Boozer
      * Braylon Mullins
      * Nikolas Khamenia
      * Jasper Johnson
      * Niko Bundalo

    The availability guard must filter them out before S1 selection, in
    both default Auto Simulation and Draft-Day Accuracy Mode.
    """

    def test_60_pick_excludes_all_return_to_school_in_s1(
        self, client: TestClient, db_session: Session,
    ) -> None:
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "draft_day_accuracy_mode": True,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        selected = _selected_names(body)
        for name in _RETURN_TO_SCHOOL_NAMES:
            assert name not in selected, (
                f"Return-to-school / not-final-entrant player {name!r} "
                f"was selected in Draft-Day Accuracy Mode"
            )

    def test_60_pick_excludes_all_return_to_school_in_default(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """Default Auto Simulation must also exclude return-to-school
        players (the guard runs before any mode-specific selection)."""
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        selected = _selected_names(body)
        for name in _RETURN_TO_SCHOOL_NAMES:
            assert name not in selected, (
                f"Return-to-school / not-final-entrant player {name!r} "
                f"was selected in default Auto Simulation"
            )

    def test_60_pick_excludes_all_unavailable_in_s1(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """Combined check: neither withdrawn nor return-to-school players
        may appear in the Draft-Day Accuracy Mode 60-pick board."""
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "draft_day_accuracy_mode": True,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        selected = _selected_names(body)
        for name in _UNAVAILABLE_NAMES:
            assert name not in selected, (
                f"Unavailable player {name!r} was selected in "
                f"Draft-Day Accuracy Mode"
            )

    def test_60_pick_excludes_all_unavailable_in_both_flags(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """When both flags are on (frontend default), the availability
        guard must still exclude all unavailable players."""
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "use_prediction_calibration": True,
                "include_projection_diagnostics": True,
                "draft_day_accuracy_mode": True,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        selected = _selected_names(body)
        for name in _UNAVAILABLE_NAMES:
            assert name not in selected, (
                f"Unavailable player {name!r} was selected in "
                f"Both-Flags mode"
            )


# ---------------------------------------------------------------------------
# 4. Safety anchors in range
# ---------------------------------------------------------------------------


class TestSafetyAnchors:
    """Brayden / Yaxel / Cameron must stay within their ranges.

    M4-CL: Niko Bundalo's safety anchor [24,34] is CANCELLED because he is
    now in the return-to-school / not-final-entrant unavailable set. The
    former ``test_niko_bundalo_range_24_34`` is replaced by
    ``test_niko_bundalo_not_selected`` below, which asserts he is NOT
    selected at all.
    """

    @pytest.fixture(autouse=True)
    def _setup_fixture(self, client: TestClient, db_session: Session):
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "draft_day_accuracy_mode": True,
            },
        )
        assert response.status_code == 200, response.text
        self._body = response.json()

    def test_brayden_burries_range_8_13(self):
        pick = _pick_of(self._body, "Brayden Burries")
        assert pick is not None, "Brayden Burries not selected"
        assert 8 <= pick <= 13, f"Brayden Burries at #{pick}, expected [8,13]"

    def test_yaxel_lendeborg_range_11_14(self):
        pick = _pick_of(self._body, "Yaxel Lendeborg")
        assert pick is not None, "Yaxel Lendeborg not selected"
        assert 11 <= pick <= 14, f"Yaxel Lendeborg at #{pick}, expected [11,14]"

    def test_cameron_carr_range_12_17(self):
        pick = _pick_of(self._body, "Cameron Carr")
        assert pick is not None, "Cameron Carr not selected"
        assert 12 <= pick <= 17, f"Cameron Carr at #{pick}, expected [12,17]"

    def test_niko_bundalo_not_selected(self):
        """M4-CL: Niko Bundalo is now unavailable (return-to-school /
        not-final-entrant). He must NOT be selected anywhere in the
        60-pick board — his previous [24,34] safety anchor is cancelled.
        """
        pick = _pick_of(self._body, "Niko Bundalo")
        assert pick is None, (
            f"Niko Bundalo was selected at #{pick} but is unavailable "
            f"(return-to-school / not-final-entrant) per M4-CL"
        )


# ---------------------------------------------------------------------------
# 5. Market-risk players improved
# ---------------------------------------------------------------------------


# Map market-risk player name -> (expected_pick, range_min, range_max)
# from _MARKET_RISK_SPECS.
_MARKET_RISK_PROJECTION: dict[str, tuple[int, int, int]] = {
    spec[0]: (spec[3], spec[4], spec[5]) for spec in _MARKET_RISK_SPECS
}


def _is_market_risk_improved(
    default_body: dict, accuracy_body: dict, name: str,
) -> bool:
    """M4-CE definition: S1 is "improved" if it selects the player closer
    to their public expected_pick, or selects them when S0 did not.

    Returns True if S1 improved on S0 for this player.
    """
    s0 = _pick_of(default_body, name)
    s1 = _pick_of(accuracy_body, name)
    if s1 is None:
        return False  # S1 didn't select — not improved
    if s0 is None:
        return True  # S0 missed, S1 selected => improved
    expected, _, _ = _MARKET_RISK_PROJECTION.get(name, (None, None, None))
    if expected is None:
        return s1 <= s0  # fallback: earlier
    return abs(s1 - expected) <= abs(s0 - expected)


class TestMarketRiskImproved:
    """Market-risk players should be selected by S1 within their projected
    range, and the majority should be improved versus S0.

    M4-CE section 7 defines "improved" as: S1 selects the player closer to
    their public expected_pick, or selects them when S0 did not. Because
    our test fixture's S0 baseline differs from the M4-CE preflight S0
    (seed_demo_data already selects some market-risk players close to
    their expected_pick), we test two things:

    1. Individual test: S1 selects the player within their projected
       draft_range_min..draft_range_max. This is the S1 consensus-priority
       guarantee — the player lands where the public board expects.
    2. Majority test: at least 6/8 players are "improved" by the M4-CE
       metric (closer to expected_pick, or newly selected).
    """

    @pytest.fixture(autouse=True)
    def _run_both_modes(self, client: TestClient, db_session: Session):
        _seed_full_test_fixture(db_session)
        default_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
            },
        )
        accuracy_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "draft_day_accuracy_mode": True,
            },
        )
        assert default_resp.status_code == 200
        assert accuracy_resp.status_code == 200
        self._default = default_resp.json()
        self._accuracy = accuracy_resp.json()

    def _assert_within_range(self, name: str) -> None:
        pick = _pick_of(self._accuracy, name)
        assert pick is not None, f"{name} not selected in S1"
        _, rmin, rmax = _MARKET_RISK_PROJECTION[name]
        assert rmin <= pick <= rmax, (
            f"{name} at #{pick} in S1, expected range [{rmin},{rmax}]"
        )

    def test_kingston_flemings_within_range(self):
        self._assert_within_range("Kingston Flemings")

    def test_aday_mara_within_range(self):
        self._assert_within_range("Aday Mara")

    def test_dailyn_swain_within_range(self):
        self._assert_within_range("Dailyn Swain")

    def test_henri_veesaar_within_range(self):
        self._assert_within_range("Henri Veesaar")

    def test_alex_karaban_within_range(self):
        self._assert_within_range("Alex Karaban")

    def test_tarris_reed_within_range(self):
        self._assert_within_range("Tarris Reed Jr.")

    def test_hannes_steinbach_within_range(self):
        self._assert_within_range("Hannes Steinbach")

    def test_christian_anderson_within_range(self):
        self._assert_within_range("Christian Anderson")

    def test_majority_of_market_risk_improved(self):
        """At least 6 of 8 market-risk players must improve (M4-CE metric)."""
        improved = sum(
            1
            for spec in _MARKET_RISK_SPECS
            if _is_market_risk_improved(
                self._default, self._accuracy, spec[0]
            )
        )
        assert improved >= 6, (
            f"Only {improved}/8 market-risk players improved; expected >= 6"
        )


# ---------------------------------------------------------------------------
# 6. API contract
# ---------------------------------------------------------------------------


class TestAPIContract:
    def test_response_includes_mode_field(self, client: TestClient, db_session: Session):
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 1, "limit": 5,
                "evaluate_trades": False,
                "draft_day_accuracy_mode": True,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "draft_day_accuracy"
        assert body["draft_day_accuracy_mode"] is True

    def test_30_pick_mode_works(self, client: TestClient, db_session: Session):
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 1, "limit": 30,
                "evaluate_trades": False,
                "draft_day_accuracy_mode": True,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["mode"] == "draft_day_accuracy"
        assert len(body["picks"]) <= 30
        # No withdrawn / return-to-school in 30-pick either.
        selected = _selected_names(body)
        for name in _UNAVAILABLE_NAMES:
            assert name not in selected


# ---------------------------------------------------------------------------
# 7. M4-CF-B: S1 must not be swallowed by use_prediction_calibration
# ---------------------------------------------------------------------------


class TestS1NotSwallowedByCalibration:
    """M4-CF-B regression: when the frontend sends both
    ``use_prediction_calibration=True`` (the frontend default) and
    ``draft_day_accuracy_mode=True``, the S1 consensus-priority branch
    must take precedence and actually drive selection.

    Before M4-CF-B the code was::

        if use_prediction_calibration and prediction_selection_map:
            ...
        elif draft_day_accuracy_mode:
            ...

    so the S1 branch was never reached when calibration was on.  These
    tests pin the fix.
    """

    def test_s1_takes_precedence_over_calibration(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """When both flags are True, the board must match S1 (not
        calibration-only) and must differ from the default board."""
        _seed_full_test_fixture(db_session)

        # Default Auto Simulation (no flags).
        default_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
            },
        )
        # S1 only.
        s1_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "draft_day_accuracy_mode": True,
            },
        )
        # Both flags on — this is what the frontend actually sends when
        # the user toggles Draft-Day Accuracy Mode on (because the
        # frontend default for use_prediction_calibration is True).
        both_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "use_prediction_calibration": True,
                "include_projection_diagnostics": True,
                "draft_day_accuracy_mode": True,
            },
        )
        assert default_resp.status_code == 200
        assert s1_resp.status_code == 200
        assert both_resp.status_code == 200

        default_order = [
            pick["selected_player"]["prospect"]["name"]
            for pick in default_resp.json()["picks"]
        ]
        s1_order = [
            pick["selected_player"]["prospect"]["name"]
            for pick in s1_resp.json()["picks"]
        ]
        both_order = [
            pick["selected_player"]["prospect"]["name"]
            for pick in both_resp.json()["picks"]
        ]

        # The "both flags" board must equal the S1-only board (S1 wins).
        assert both_order == s1_order, (
            "When use_prediction_calibration=True AND "
            "draft_day_accuracy_mode=True are both set, the board should "
            "match S1-only. The S1 branch is being swallowed by "
            "prediction_calibration."
        )
        # And it must differ from the default Auto Simulation board.
        assert both_order != default_order, (
            "Draft-Day Accuracy Mode had no effect when "
            "use_prediction_calibration was also True."
        )
        # Response mode identifier must reflect S1.
        assert both_resp.json()["mode"] == "draft_day_accuracy"
        assert both_resp.json()["draft_day_accuracy_mode"] is True

    def test_s1_mode_reflected_in_selected_players(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """When mode="draft_day_accuracy", the selected players must
        actually reflect S1 results — not just the label."""
        _seed_full_test_fixture(db_session)

        s1_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "draft_day_accuracy_mode": True,
            },
        )
        both_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "use_prediction_calibration": True,
                "include_projection_diagnostics": True,
                "draft_day_accuracy_mode": True,
            },
        )
        assert s1_resp.status_code == 200
        assert both_resp.status_code == 200
        assert both_resp.json()["mode"] == "draft_day_accuracy"

        # The pick-by-pick selected players must be identical.
        s1_picks = [
            (pick["pick"], pick["selected_player"]["prospect"]["name"])
            for pick in s1_resp.json()["picks"]
        ]
        both_picks = [
            (pick["pick"], pick["selected_player"]["prospect"]["name"])
            for pick in both_resp.json()["picks"]
        ]
        assert s1_picks == both_picks, (
            "mode='draft_day_accuracy' label is set but selected players "
            "do not match S1 results — calibration is still driving "
            "selection."
        )

    def test_s1_not_swallowed_no_withdrawn(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """When both flags are True, withdrawn players must still be
        excluded (the availability guard must still run before S1)."""
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "use_prediction_calibration": True,
                "include_projection_diagnostics": True,
                "draft_day_accuracy_mode": True,
            },
        )
        assert response.status_code == 200
        selected = _selected_names(response.json())
        for name in _UNAVAILABLE_NAMES:
            assert name not in selected

    def test_s1_kingston_not_slipped_when_calibration_on(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """Kingston Flemings must not stay at the default-mode slip
        position (#32) when S1 is on, even if calibration is also on."""
        _seed_full_test_fixture(db_session)

        default_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
            },
        )
        both_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "use_prediction_calibration": True,
                "include_projection_diagnostics": True,
                "draft_day_accuracy_mode": True,
            },
        )
        assert default_resp.status_code == 200
        assert both_resp.status_code == 200

        default_kingston = _pick_of(default_resp.json(), "Kingston Flemings")
        both_kingston = _pick_of(both_resp.json(), "Kingston Flemings")
        # Kingston should be selected, and should not be at the default
        # slip position.  In S1 he lands near #8 (expected_pick=7).
        assert both_kingston is not None, (
            "Kingston Flemings not selected in S1+calibration mode"
        )
        assert both_kingston <= 15, (
            f"Kingston Flemings at #{both_kingston} in S1+calibration "
            f"mode; expected near #8 (default was #{default_kingston})"
        )
        # And it must differ from the default position.
        assert both_kingston != default_kingston, (
            f"Kingston Flemings still at #{both_kingston} (same as "
            f"default) — S1 is being swallowed by calibration."
        )

    def test_s1_aday_and_hannes_not_slipped_when_calibration_on(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """Aday Mara and Hannes Steinbach must not stay at the default
        slip positions when S1 is on, even if calibration is also on."""
        _seed_full_test_fixture(db_session)

        both_resp = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
                "use_prediction_calibration": True,
                "include_projection_diagnostics": True,
                "draft_day_accuracy_mode": True,
            },
        )
        assert both_resp.status_code == 200
        body = both_resp.json()

        aday = _pick_of(body, "Aday Mara")
        hannes = _pick_of(body, "Hannes Steinbach")
        assert aday is not None, "Aday Mara not selected in S1+calibration"
        assert hannes is not None, "Hannes Steinbach not selected in S1+calibration"
        # Aday expected_pick=8, should land near #9 (not #25).
        assert aday <= 15, (
            f"Aday Mara at #{aday}; expected near #9 (default was #25)"
        )
        # Hannes expected_pick=13, should land near #15 (not #34).
        assert hannes <= 22, (
            f"Hannes Steinbach at #{hannes}; expected near #15 (default was #34)"
        )

    def test_default_mode_unchanged_when_calibration_off(
        self, client: TestClient, db_session: Session,
    ) -> None:
        """Default Auto Simulation (both flags off) must be unchanged."""
        _seed_full_test_fixture(db_session)
        response = client.post(
            "/api/simulate",
            json={
                "year": 2026, "rounds": 2, "limit": 60,
                "evaluate_trades": False,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mode"] == "auto_simulation"
        assert body["draft_day_accuracy_mode"] is False
        # No withdrawn / return-to-school in default mode either.
        selected = _selected_names(body)
        for name in _UNAVAILABLE_NAMES:
            assert name not in selected
