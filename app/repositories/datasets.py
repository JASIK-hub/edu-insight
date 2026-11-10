"""Dataset queries shared by ingestion consumers."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Dataset


def list_datasets(session: Session) -> list[Dataset]:
    return list(session.scalars(select(Dataset).order_by(Dataset.created_at.desc(), Dataset.id.desc())))


def get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset | None:
    return session.get(Dataset, dataset_id)


def newest_dataset(session: Session) -> Dataset | None:
    return session.scalar(select(Dataset).order_by(Dataset.created_at.desc(), Dataset.id.desc()).limit(1))
