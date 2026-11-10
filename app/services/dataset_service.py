"""Transactional dataset ingestion facade for multipart upload handlers.

Call import_dataset(session, upload.file, upload.filename, school_name) from a router.
The caller owns and closes the SQLAlchemy session; this service commits only after
all rows validate and persist. Invalid imports leave the database unchanged.
"""

from sqlalchemy.orm import Session

from app.services.csv_importer import ImportSummary, import_csv


def import_dataset(session: Session, file, filename: str, school_name: str = "Imported School", *, synthetic: bool = False) -> ImportSummary:
    return import_csv(session, file, filename, school_name, synthetic=synthetic)
