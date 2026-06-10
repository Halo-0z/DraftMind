from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    abbr: Mapped[str] = mapped_column(String(8), unique=True, index=True)
    nba_team_id: Mapped[int | None] = mapped_column(unique=True, index=True, nullable=True)
    city: Mapped[str | None] = mapped_column(String(80), nullable=True)
    conference: Mapped[str] = mapped_column(String(20))
    division: Mapped[str] = mapped_column(String(40))

    needs: Mapped[list["TeamNeed"]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
    )
    rosters: Mapped[list["Roster"]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
    )


class TeamNeed(Base):
    __tablename__ = "team_needs"
    __table_args__ = (UniqueConstraint("team_id", "year", name="uq_team_need_year"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    year: Mapped[int] = mapped_column(index=True)
    need_pg: Mapped[int] = mapped_column(default=0)
    need_sg: Mapped[int] = mapped_column(default=0)
    need_sf: Mapped[int] = mapped_column(default=0)
    need_pf: Mapped[int] = mapped_column(default=0)
    need_c: Mapped[int] = mapped_column(default=0)
    need_shooting: Mapped[int] = mapped_column(default=0)
    need_defense: Mapped[int] = mapped_column(default=0)
    need_creation: Mapped[int] = mapped_column(default=0)

    team: Mapped[Team] = relationship(back_populates="needs")
