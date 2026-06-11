from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TeamNeedProfile(Base):
    __tablename__ = "team_need_profiles"
    __table_args__ = (
        UniqueConstraint(
            "team_id",
            "year",
            "horizon",
            name="uq_team_need_profile_team_year_horizon",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    year: Mapped[int] = mapped_column(index=True)

    need_guard_depth: Mapped[int] = mapped_column(default=5)
    need_wing_depth: Mapped[int] = mapped_column(default=5)
    need_big_depth: Mapped[int] = mapped_column(default=5)
    need_center: Mapped[int] = mapped_column(default=5)
    need_size: Mapped[int] = mapped_column(default=5)
    need_youth: Mapped[int] = mapped_column(default=5)
    need_nba_ready: Mapped[int] = mapped_column(default=5)
    need_upside: Mapped[int] = mapped_column(default=5)

    need_spacing: Mapped[int] = mapped_column(default=5)
    need_shooting_volume: Mapped[int] = mapped_column(default=5)
    need_movement_shooting: Mapped[int] = mapped_column(default=5)
    need_self_creation: Mapped[int] = mapped_column(default=5)
    need_secondary_creation: Mapped[int] = mapped_column(default=5)
    need_playmaking: Mapped[int] = mapped_column(default=5)
    need_rim_pressure: Mapped[int] = mapped_column(default=5)
    need_finishing: Mapped[int] = mapped_column(default=5)

    need_rim_protection: Mapped[int] = mapped_column(default=5)
    need_defensive_rebounding: Mapped[int] = mapped_column(default=5)
    need_offensive_rebounding: Mapped[int] = mapped_column(default=5)
    need_point_of_attack_defense: Mapped[int] = mapped_column(default=5)
    need_switchability: Mapped[int] = mapped_column(default=5)
    need_team_defense: Mapped[int] = mapped_column(default=5)
    need_foul_discipline: Mapped[int] = mapped_column(default=5)
    need_physicality: Mapped[int] = mapped_column(default=5)

    team_timeline: Mapped[str] = mapped_column(String(24), default="unknown")
    core_age_curve: Mapped[float | None] = mapped_column(Float, nullable=True)
    contract_pressure: Mapped[int] = mapped_column(default=5)
    pending_free_agents: Mapped[str] = mapped_column(String(500), default="")
    development_bandwidth: Mapped[int] = mapped_column(default=5)
    scheme_tags: Mapped[str] = mapped_column(String(500), default="")

    source: Mapped[str] = mapped_column(String(32), default="seed")
    horizon: Mapped[str] = mapped_column(String(32), default="now")
    need_confidence: Mapped[float] = mapped_column(Float, default=0.5)
    manual_override_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    team = relationship("Team", back_populates="need_profiles")


class ProspectScoutingProfile(Base):
    __tablename__ = "prospect_scouting_profiles"
    __table_args__ = (
        UniqueConstraint(
            "prospect_id",
            "year",
            name="uq_prospect_scouting_profile_prospect_year",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    prospect_id: Mapped[int] = mapped_column(ForeignKey("prospects.id"), index=True)
    year: Mapped[int] = mapped_column(index=True)

    shooting_volume: Mapped[int] = mapped_column(default=5)
    shooting_versatility: Mapped[int] = mapped_column(default=5)
    spacing_value: Mapped[int] = mapped_column(default=5)
    rim_pressure: Mapped[int] = mapped_column(default=5)
    self_creation: Mapped[int] = mapped_column(default=5)
    secondary_creation: Mapped[int] = mapped_column(default=5)
    passing_feel: Mapped[int] = mapped_column(default=5)
    finishing: Mapped[int] = mapped_column(default=5)

    rim_protection: Mapped[int] = mapped_column(default=5)
    defensive_rebounding: Mapped[int] = mapped_column(default=5)
    offensive_rebounding: Mapped[int] = mapped_column(default=5)
    point_of_attack_defense: Mapped[int] = mapped_column(default=5)
    switchability: Mapped[int] = mapped_column(default=5)
    team_defense: Mapped[int] = mapped_column(default=5)
    foul_discipline: Mapped[int] = mapped_column(default=5)
    physicality: Mapped[int] = mapped_column(default=5)

    height: Mapped[str | None] = mapped_column(String(24), nullable=True)
    wingspan: Mapped[str | None] = mapped_column(String(24), nullable=True)
    age: Mapped[float | None] = mapped_column(Float, nullable=True)
    nba_readiness: Mapped[int] = mapped_column(default=5)
    upside: Mapped[int] = mapped_column(default=5)
    medical_risk: Mapped[int] = mapped_column(default=5)
    role_projection: Mapped[str] = mapped_column(String(120), default="")
    scheme_fit_tags: Mapped[str] = mapped_column(String(500), default="")

    source: Mapped[str] = mapped_column(String(32), default="seed")
    profile_confidence: Mapped[float] = mapped_column(Float, default=0.5)
    manual_override_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    prospect = relationship("Prospect", back_populates="scouting_profiles")
