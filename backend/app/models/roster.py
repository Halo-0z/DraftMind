from sqlalchemy import Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.team import Team


class Roster(Base):
    __tablename__ = "rosters"
    __table_args__ = (
        UniqueConstraint("team_id", "season", "player_name", name="uq_roster_player"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    season: Mapped[str] = mapped_column(String(12), index=True)
    nba_player_id: Mapped[int | None] = mapped_column(index=True, nullable=True)
    player_name: Mapped[str] = mapped_column(String(120), index=True)
    position: Mapped[str | None] = mapped_column(String(16), nullable=True)
    age: Mapped[float | None] = mapped_column(Float, nullable=True)
    height: Mapped[str | None] = mapped_column(String(24), nullable=True)
    weight: Mapped[int | None] = mapped_column(nullable=True)
    jersey: Mapped[str | None] = mapped_column(String(12), nullable=True)
    experience: Mapped[str | None] = mapped_column(String(24), nullable=True)
    school: Mapped[str | None] = mapped_column(String(120), nullable=True)

    team: Mapped[Team] = relationship(back_populates="rosters")
