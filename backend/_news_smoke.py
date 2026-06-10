"""Quick smoke test of the refactored news fetcher."""
import os
import traceback

LOG = []
try:
    import requests
    from app.database import Base, engine
    from app.services.news_service import FETCHERS, SOURCES

    Base.metadata.create_all(bind=engine)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    total = 0
    for src in SOURCES:
        try:
            items = FETCHERS[src["kind"]](src, session)
            sample = items[0]["title"][:60] if items else "(empty)"
            LOG.append(f"[OK] {src['name']:14s}  fetched={len(items):3d}  sample={sample!r}")
            total += len(items)
        except Exception as exc:
            LOG.append(f"[ERR] {src['name']:14s}  {str(exc)[:120]}")

    LOG.append(f"\nTOTAL raw items: {total}")
except Exception:
    LOG.append("FATAL:\n" + traceback.format_exc())

# Write to a known host path that we can read back.
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_news_smoke_result.txt")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(LOG))
print("WROTE", out_path)
