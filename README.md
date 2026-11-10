# EduInsight

**Educational analytics and curriculum decision support.** Upload assessment results, inspect topic and textbook patterns, calculate a constrained teaching-hours allocation, and generate a Russian, English, or Kazakh report. All scores and hour allocations are calculated by the backend; OpenRouter can only select approved recommendation actions.

## What works

- CSV upload to PostgreSQL with validation and a stable `dataset_id`.
- Dashboard-ready analytics for KPIs, topic mastery, dated trends, score distribution, and textbook comparisons.
- Curriculum optimization and a what-if simulator.
- Stored, retry-safe reports with deterministic fallback when OpenRouter is unavailable.
- FastAPI interactive docs at `/docs` and a frontend contract in [`.openapi.json`](.openapi.json).

## Quick start

**Requirements:** Python 3.12+, a Neon PostgreSQL database, and Git. An OpenRouter key is optional.

```bash
cd backend
py -m pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env` and set `DATABASE_URL` to your **Neon direct connection URL**. Set `OPENAI_API_KEY` to your OpenRouter key if you want AI-assisted action selection. Keep the key on the backend only. The example file already sets `OPENAI_BASE_URL=https://openrouter.ai/api/v1`; you can change `OPENAI_MODEL` there too.

```bash
py -m alembic upgrade head
py seed.py
py -m uvicorn app.main:app --reload
```

Run these commands from `backend/`. On systems where `python` points to a real Python installation, replace `py` with `python`. From the repository root, the server command is `py -m uvicorn app.main:app --app-dir backend --reload`.

Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) or check [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health). The seed script imports `backend/data/synthetic_assessments.csv` once. The database URL is normalized to the Psycopg 3 SQLAlchemy dialect; retain Neon's SSL query parameters.

## CSV to report

The CSV must be UTF-8 with these required columns:

```csv
student_id,topic,textbook,score,max_score,assessment_date,class_id,grade
s1,Algebra,Book A,4,10,2026-01-01,7A,7
s2,Geometry,Book B,8,10,2026-01-02,7A,7
```

The first five columns are required; the remaining columns are optional. Scores must satisfy `0 <= score <= max_score` and `max_score > 0`. See the [data dictionary](docs/data-dictionary.md) for details.

1. `POST /api/datasets/upload` with multipart field `file`. Keep the returned `dataset_id`.
2. `GET /api/datasets/{dataset_id}/analytics` for chart data. Optional filters: `grade`, `textbook`, `topic`, and `subject`.
3. `POST /api/curriculum/optimize` with actual topic names and a `current_hours` map, for example `{"dataset_id": 1, "current_hours": {"Algebra": 8, "Geometry": 6}, "minimum_hours": 3}`.
4. `POST /api/recommendations/analyze` with `{"dataset_id": 1, "language": "ru", "optimization": <complete optimize response>, "data_quality": {}}`. The `optimization` field is optional.
5. Retrieve the saved report at `GET /api/datasets/{dataset_id}/report`.

Use real topic names from `GET /api/analytics/topics?dataset_id=1`; examples will not match every dataset. Reports are cached per dataset and request. No raw CSV or individual student records are sent to OpenRouter.

**Current data limits:** the CSV schema has no subject or per-question answer counts. `available_filters.subjects` and `topic_performance` are empty, with warnings in the analytics response. A subject filter cannot match records until the upload schema includes a subject field.

## Development

```bash
cd backend
py -m unittest discover -s tests -v
```

The API is a modular FastAPI monolith: `storage`, `analytics`, `curriculum`, and `explanations` live under `backend/app/`. PostgreSQL migrations live under `backend/alembic/`. Read the [architecture](docs/architecture.md), [API contract](docs/api-contract.md), and [workflow](docs/workflow.md) for integration details.
