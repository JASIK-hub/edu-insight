"""Load the bundled synthetic dataset after running Alembic migrations."""

from pathlib import Path

from sqlalchemy import select

from app.storage.database import session_factory
from app.storage.ingest import import_csv
from app.storage.models import Dataset


def main() -> None:
    source = Path(__file__).resolve().parent / "data" / "synthetic_assessments.csv"
    with session_factory() as session:
        existing = session.scalar(select(Dataset).where(Dataset.filename == source.name).limit(1))
        if existing is not None:
            print(f"Synthetic dataset already present: id={existing.id}")
            return
        result = import_csv(session, source.name, source.read_bytes())
        print(f"Seeded dataset id={result.id}, rows={result.row_count}")


if __name__ == "__main__":
    main()
