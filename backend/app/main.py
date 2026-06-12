from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine
# Importing the models package ensures every model class is registered with
# Base.metadata before create_all() runs at app startup.  Without this the
# news_articles / prospects / etc. tables would not be auto-created when
# the backend boots for the first time against an empty SQLite file.
from app import models  # noqa: F401
from app.routers import agent, health, news, prospects, recommendations, scouting, simulations, teams


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="NBA draft decision agent backend.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _ensure_tables() -> None:
    """Idempotently create any missing tables.

    Production deploys should use Alembic migrations, but the MVP relies on
    SQLAlchemy's create_all so the SQLite file is usable on first boot.
    """
    Base.metadata.create_all(bind=engine)


app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(teams.router, prefix=settings.api_prefix)
app.include_router(prospects.router, prefix=settings.api_prefix)
app.include_router(recommendations.router, prefix=settings.api_prefix)
app.include_router(agent.router, prefix=settings.api_prefix)
app.include_router(simulations.router, prefix=settings.api_prefix)
app.include_router(news.router, prefix=settings.api_prefix)
app.include_router(scouting.router, prefix=settings.api_prefix)
