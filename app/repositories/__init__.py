"""Database session construction. Set DATABASE_URL before importing the application."""

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def database_url() -> str:
    raw = os.environ.get("DATABASE_URL")
    if not raw:
        raise RuntimeError("DATABASE_URL is required and must point to PostgreSQL")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        raise ValueError("DATABASE_URL must point to PostgreSQL")
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def make_engine(url: str | None = None):
    if url is not None:
        parsed = make_url(url)
        if parsed.get_backend_name() != "postgresql":
            raise ValueError("Database URL must point to PostgreSQL")
        if parsed.drivername == "postgresql":
            url = parsed.set(drivername="postgresql+psycopg").render_as_string(hide_password=False)
    return create_engine(url or database_url(), pool_pre_ping=True)


def session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(url), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with session_factory()() as session:
        yield session
