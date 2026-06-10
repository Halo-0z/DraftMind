# AGENTS.md

## Project

DraftMind is an NBA draft decision agent. It helps users simulate an NBA general manager making draft picks based on team needs, prospect data, historical draft data, scouting reports, and a ranking engine.

## Tech Stack

- Backend: Python, FastAPI, SQLite, Pandas
- Frontend: Next.js, TypeScript, TailwindCSS
- AI: LLM API for explanation only
- Retrieval: FAISS or Chroma
- Testing: pytest

## Architecture Rules

- Do not let the LLM invent player statistics.
- All player recommendations must come from the ranking_engine first.
- LLM output should explain model results, not replace model results.
- Keep API responses structured as JSON.
- Write tests for ranking logic before changing scoring behavior.

## Backend Commands

- Install: `cd backend && pip install -e .`
- Run API: `cd backend && uvicorn app.main:app --reload`
- Seed DB: `cd backend && python scripts/seed_db.py`
- Test: `cd backend && pytest`

## Frontend Commands

- Install: `cd frontend && npm install`
- Dev: `cd frontend && npm run dev`

## MVP Scope

Implement:

1. Team list
2. Prospect list
3. Recommend pick API
4. Ranking engine
5. Basic RAG explanation
6. Draft recommendation UI

Do not implement:

- Real-time NBA scraping
- Payment system
- User login
- Complex multi-agent orchestration
