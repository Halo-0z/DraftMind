from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, SessionLocal, engine
from app.services.news_service import fetch_recent_articles


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        articles = fetch_recent_articles(db=db, refresh=True)
        print(f"Imported / refreshed {len(articles)} NBA draft news articles.")


if __name__ == "__main__":
    main()
