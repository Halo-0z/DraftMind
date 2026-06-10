# DraftMind

NBA draft decision agent for simulating a general manager's draft pick process.

DraftMind uses structured team, prospect, draft order, and scouting report data to rank prospects before any LLM explanation is generated. The MVP starts with mock data and a mock AI layer so the product can run locally without external services.

## Stack

- Backend: FastAPI, Python
- Frontend: Next.js, TypeScript, Tailwind CSS
- Data: local CSV/JSON/SQLite-ready folders
- AI: mock first, provider API later

## Project Layout

```text
backend/
  app/
    main.py
    config.py
    routers/
      health.py
frontend/
  app/
    page.tsx
  components/
  lib/
data/
  raw/
  processed/
```

## Backend

```bash
cd backend
pip install -e .
python scripts/seed_db.py
python scripts/import_nba_rosters.py --season 2025-26 --abbr SAS --abbr HOU
python scripts/import_2026_draft_order.py
python scripts/import_nba_prospects.py
uvicorn app.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/api/health
```

Core mock-data endpoints:

```bash
curl http://127.0.0.1:8000/api/teams
curl "http://127.0.0.1:8000/api/teams/1/roster?season=2025-26"
curl "http://127.0.0.1:8000/api/prospects?year=2026"
curl -X POST http://127.0.0.1:8000/api/recommend \
  -H "Content-Type: application/json" \
  -d '{"year":2026,"team":"SAS","pick":8,"mode":"gm_decision"}'
curl -X POST http://127.0.0.1:8000/api/agent/ask \
  -H "Content-Type: application/json" \
  -d '{"year":2026,"team":"SAS","pick":8,"question":"为什么不选 AJ Dybantsa？"}'
curl -X POST http://127.0.0.1:8000/api/simulate \
  -H "Content-Type: application/json" \
  -d '{"year":2026,"rounds":1,"limit":20}'
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

## MVP Guardrails

- Do not let the LLM invent player statistics.
- Recommendations must come from a ranking engine first.
- LLM output explains structured results instead of replacing them.
- Keep API responses structured as JSON.
- Cache live NBA.com roster imports in SQLite so demos can survive API rate limits or network issues.

## NBA Roster Import

DraftMind uses `nba_api` to import NBA.com roster data from the `CommonTeamRoster` endpoint into local SQLite.

Import selected teams:

```bash
cd backend
python scripts/import_nba_rosters.py --season 2025-26 --abbr SAS --abbr HOU
```

Import all teams:

```bash
cd backend
python scripts/import_nba_rosters.py --season 2025-26
```

## Draft Order Import

DraftMind can cache the current NBA.com 2026 draft order in SQLite:

```bash
cd backend
python scripts/import_2026_draft_order.py
```

The import includes 60 picks, pick owners, traded-pick notes, and source metadata:

```text
NBA.com 2026 Draft Order, updated 2026-06-04
```

## NBA Prospect Import

DraftMind can cache NBA.com 2026 prospect bio data into SQLite:

```bash
cd backend
python scripts/import_nba_prospects.py
```

The importer reads NBA.com prospect names, positions, height, weight, school or league, status, age, country, and profile links from:

```text
https://www.nba.com/draft/2026/prospects
```

Existing manually scored seed prospects keep their scoring fields. New NBA.com prospects receive DraftMind heuristic scoring estimates so the full 60-pick simulation can run end to end. Those estimates are marked in the generated scouting report text and should not be presented as official NBA projections.

The API reads from the SQLite cache:

```bash
curl "http://127.0.0.1:8000/api/teams/1/roster?season=2025-26"
```

## Demo Script

1. Start the backend and frontend, then open http://127.0.0.1:3000/draft.
2. Select `SAS · San Antonio Spurs`, set pick `8`, and click `生成推荐`.
3. Walk through the recommended player card: final score, score bars, reasons, risks, and alternatives.
4. In `Agent 追问`, ask `为什么不选 AJ Dybantsa？`.
5. Point out that the answer cites structured scores from `ranking_engine`, not invented stats.
6. Click `模拟前 20 顺位` to show the full board simulation with no duplicate selected players.

Talk track:

DraftMind is not a generic chatbot. It first computes prospect rankings from team needs, talent, pick value, and risk. The Agent layer only explains those structured results in GM language.
