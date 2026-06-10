from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.team import Team


class DraftOrder(Base):
    __tablename__ = "draft_order"
    __table_args__ = (UniqueConstraint("year", "pick_no", name="uq_draft_pick_year"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    year: Mapped[int] = mapped_column(index=True)
    pick_no: Mapped[int] = mapped_column(index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    original_team: Mapped[str | None] = mapped_column(nullable=True)
    source: Mapped[str | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(nullable=True)

    team: Mapped[Team] = relationship()
