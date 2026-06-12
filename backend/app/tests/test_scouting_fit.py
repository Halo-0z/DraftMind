from types import SimpleNamespace

from app.services.scouting_fit import (
    ScoutingFitResult,
    _profile_source_weight,
    calculate_scouting_fit,
)


def _team_profile(**overrides):
    defaults = {
        "need_rim_protection": 5,
        "need_defensive_rebounding": 5,
        "need_offensive_rebounding": 5,
        "need_spacing": 5,
        "need_shooting_volume": 5,
        "need_movement_shooting": 5,
        "need_self_creation": 5,
        "need_secondary_creation": 5,
        "need_playmaking": 5,
        "need_rim_pressure": 5,
        "need_finishing": 5,
        "need_point_of_attack_defense": 5,
        "need_switchability": 5,
        "need_team_defense": 5,
        "need_physicality": 5,
        "need_nba_ready": 5,
        "need_upside": 5,
        "need_center": 5,
        "need_big_depth": 5,
        "need_wing_depth": 5,
        "need_size": 5,
        "source": "manual",
        "need_confidence": 1.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _prospect_profile(**overrides):
    defaults = {
        "rim_protection": 5,
        "defensive_rebounding": 5,
        "offensive_rebounding": 5,
        "spacing_value": 5,
        "shooting_volume": 5,
        "shooting_versatility": 5,
        "self_creation": 5,
        "secondary_creation": 5,
        "passing_feel": 5,
        "rim_pressure": 5,
        "finishing": 5,
        "point_of_attack_defense": 5,
        "switchability": 5,
        "team_defense": 5,
        "physicality": 5,
        "nba_readiness": 5,
        "upside": 5,
        "medical_risk": 5,
        "foul_discipline": 5,
        "height": "6-6",
        "position": "SF",
        "source": "manual",
        "profile_confidence": 1.0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_scouting_fit_rewards_rim_protection_match() -> None:
    team_profile = _team_profile(need_rim_protection=10)
    prospect_profile = _prospect_profile(rim_protection=10)

    result = calculate_scouting_fit(team_profile, prospect_profile)

    assert result.score > 6
    assert result.adjustment > 0
    assert "rim_protection_fit" in result.positives


def test_scouting_fit_flags_spacing_risk() -> None:
    team_profile = _team_profile(need_spacing=10, need_shooting_volume=9)
    prospect_profile = _prospect_profile(spacing_value=2, shooting_volume=3)

    result = calculate_scouting_fit(team_profile, prospect_profile)

    assert "spacing_risk" in result.risks


def test_news_display_only_source_weight_is_zero() -> None:
    assert _profile_source_weight("news_display_only") == 0.0

    team_profile = _team_profile(source="news_display_only", need_rim_protection=10)
    prospect_profile = _prospect_profile(rim_protection=10)

    result = calculate_scouting_fit(team_profile, prospect_profile)

    assert result.source_weight == 0.0
    assert result.confidence_weight == 0.0
    assert result.adjustment == 0.0


def test_api_inferred_weight_is_lower_than_manual_and_seed() -> None:
    assert _profile_source_weight("api_inferred") < _profile_source_weight("seed")
    assert _profile_source_weight("api_inferred") < _profile_source_weight("manual")


def test_missing_profiles_return_safe_default() -> None:
    result = calculate_scouting_fit(None, None)

    assert isinstance(result, ScoutingFitResult)
    assert result.score == 0.0
    assert result.adjustment == 0.0
    assert result.positives == []
    assert result.risks == []


def test_missing_profile_fields_use_conservative_defaults() -> None:
    team_profile = SimpleNamespace(source="manual", need_confidence=1.0)
    prospect_profile = SimpleNamespace(source="manual", profile_confidence=1.0)

    result = calculate_scouting_fit(team_profile, prospect_profile)

    assert 0.0 <= result.score <= 10.0
    assert 0.0 <= result.adjustment <= 2.0
    assert result.positives == []
