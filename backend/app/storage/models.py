from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded", server_default="uploaded")
    assessments: Mapped[list["Assessment"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")
    reports: Mapped[list["AnalysisReport"]] = relationship(back_populates="dataset", cascade="all, delete-orphan")


class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (
        Index("ix_assessments_dataset_topic", "dataset_id", "topic"),
        Index("ix_assessments_dataset_textbook", "dataset_id", "textbook"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(String(255), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    textbook: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    max_score: Mapped[float] = mapped_column(Float, nullable=False)
    assessment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    class_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dataset: Mapped[Dataset] = relationship(back_populates="assessments")


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"
    __table_args__ = (UniqueConstraint("dataset_id", "request_hash", name="uq_analysis_report_request"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    report_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    dataset: Mapped[Dataset] = relationship(back_populates="reports")
