# EduInsight backend architecture

Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL, Alembic, Pandas, NumPy, SciPy, and the official OpenAI SDK. One deployable modular monolith. Run with `uvicorn app.main:app --reload` from `backend`.

## Ownership and integration

Every agent reads all three documents in `docs/` before editing. API contracts are frozen; changes require lead approval. Agents only edit their owned paths.

| Owner | Paths | Responsibility |
|---|---|---|
| Lead | `docs/`, `backend/app/contracts.py`, `backend/app/main.py`, `backend/app/config.py`, `backend/requirements.txt`, `backend/.env.example` | Shared schemas, wiring, integration |
| Agent 1 | `backend/app/storage/`, `backend/alembic/`, `backend/alembic.ini` | ORM, PostgreSQL, migrations, CSV ingest |
| Agent 2 | `backend/app/analytics/` | Topic mastery, overview, textbook comparisons |
| Agent 3 | `backend/app/curriculum/` | Deterministic optimization and simulation |
| Agent 4 | `backend/app/api/`, `backend/app/explanations/` | Routes and OpenAI explanation with fallback |

No Redis, Celery, Kubernetes, or microservices. SQLAlchemy sessions are request scoped. Analytics and optimization use typed inputs and return contract models. OpenAI receives computed results only and cannot calculate scores or allocate hours.

## Service boundaries

`storage.ingest.import_csv(session, filename, content) -> DatasetOut`

`storage.repository.list_datasets(session) -> list[DatasetOut]`

`analytics.service.overview(session, dataset_id) -> OverviewOut`

`analytics.service.topics(session, dataset_id) -> TopicsOut`

`analytics.service.textbooks(session, dataset_id) -> TextbooksOut`

`curriculum.service.optimize(request: OptimizeRequest, topics: TopicsOut) -> OptimizeOut`

`curriculum.service.simulate(request: SimulateRequest, topics: TopicsOut) -> SimulateOut`

`explanations.service.explain(request: ExplainRequest) -> ExplainOut`

The API layer resolves dataset IDs, opens sessions, and calls these functions. Empty data yields valid zero/empty responses; unknown dataset IDs yield 404. CSV errors yield 422. Database connection errors must surface clearly at startup or request time.

## Report lifecycle

CSV ingestion commits a dataset and its assessment rows atomically with status `uploaded`. Analysis uses the dataset ID to load aggregate metrics. A unique `(dataset_id, request_hash)` report row prevents repeated work for identical requests. The dataset row is locked while reserving a report, so concurrent requests see `processing` rather than creating duplicate reports. Successful AI action selection or deterministic fallback is persisted as a `completed` JSON report; unexpected failures set `failed` and may be retried. Stale processing reservations can be retried after `ANALYSIS_STALE_SECONDS`. Reports are retrieved by dataset ID. The model receives only opaque topic references, mastery ratios, and sample sizes. CSV text, textbook names, assessment rows, and student identifiers stay in the backend.
