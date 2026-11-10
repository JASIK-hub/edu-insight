# Database integration

Install Python 3.12+ with `sqlalchemy>=2`, `alembic`, `pandas`, `pydantic>=2`, and `psycopg[binary]`. Set `DATABASE_URL` to the Neon PostgreSQL connection URL through your shell or secret manager. Both `postgresql://` and `postgresql+psycopg://` schemes are accepted. The URL is required; there is no local database fallback. Keep the credential out of tracked files.

From the repository root, run `alembic -c alembic/alembic.ini upgrade head`. Run `python -m scripts.seed_demo` only against a database where synthetic data is wanted; it creates a clearly named synthetic school with 600 students and assessment data.

For multipart uploads, pass `UploadFile.file`, `UploadFile.filename`, and optionally a school name to `app.services.dataset_service.import_dataset(session, file, filename, school_name)`. It returns an `ImportSummary`: `ok`, `total_rows`, `imported_rows`, `dataset_id`, and `errors` with one based CSV line numbers. The service commits successful imports and rolls back failed persistence. It rejects the whole CSV if any row fails validation. The CSV contract is documented in `app/services/csv_importer.py`. The shared API contract currently declares integer dataset IDs; this UUID schema requires that contract and its API adapters to be updated by their owners before end-to-end integration.
