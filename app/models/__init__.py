"""EduInsight persistence schema. Import Base.metadata for Alembic."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Record(Base):
    __abstract__ = True
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class School(Record):
    __tablename__ = "schools"
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    classrooms: Mapped[list[Classroom]] = relationship(back_populates="school")


class Classroom(Record):
    __tablename__ = "classrooms"
    __table_args__ = (UniqueConstraint("school_id", "name", "grade"), CheckConstraint("grade BETWEEN 1 AND 12"))
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    grade: Mapped[int] = mapped_column(Integer)
    school: Mapped[School] = relationship(back_populates="classrooms")
    students: Mapped[list[Student]] = relationship(back_populates="classroom")


class Student(Record):
    __tablename__ = "students"
    __table_args__ = (UniqueConstraint("school_id", "external_id"),)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), index=True)
    classroom_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classrooms.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(200))
    classroom: Mapped[Classroom] = relationship(back_populates="students")
    results: Mapped[list[TestResult]] = relationship(back_populates="student")


class Subject(Record):
    __tablename__ = "subjects"
    name: Mapped[str] = mapped_column(String(150), unique=True)
    topics: Mapped[list[Topic]] = relationship(back_populates="subject")


class Topic(Record):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("subject_id", "name"),)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    subject: Mapped[Subject] = relationship(back_populates="topics")


class Textbook(Record):
    __tablename__ = "textbooks"
    __table_args__ = (UniqueConstraint("subject_id", "grade", "title"), CheckConstraint("grade BETWEEN 1 AND 12"))
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id"), index=True)
    grade: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(250))


class Dataset(Record):
    __tablename__ = "datasets"
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    is_synthetic: Mapped[bool] = mapped_column(default=False)
    assessments: Mapped[list[Assessment]] = relationship(back_populates="dataset")


class Assessment(Record):
    __tablename__ = "assessments"
    __table_args__ = (UniqueConstraint("dataset_id", "student_id", "topic_id", "textbook_id", "assessment_date"), CheckConstraint("max_score > 0"))
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"), index=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"), index=True)
    textbook_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("textbooks.id"), index=True)
    assessment_date: Mapped[date | None] = mapped_column(Date, index=True)
    max_score: Mapped[float] = mapped_column(Numeric(10, 2))
    dataset: Mapped[Dataset] = relationship(back_populates="assessments")
    result: Mapped[TestResult] = relationship(back_populates="assessment", uselist=False)


class TestResult(Record):
    __tablename__ = "test_results"
    __table_args__ = (CheckConstraint("score >= 0 AND normalized_score >= 0 AND normalized_score <= 100"),)
    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assessments.id"), unique=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id"), index=True)
    score: Mapped[float] = mapped_column(Numeric(10, 2))
    normalized_score: Mapped[float] = mapped_column(Numeric(5, 2))
    assessment: Mapped[Assessment] = relationship(back_populates="result")
    student: Mapped[Student] = relationship(back_populates="results")


class Curriculum(Record):
    __tablename__ = "curricula"
    __table_args__ = (UniqueConstraint("school_id", "subject_id", "grade", "name"), CheckConstraint("grade BETWEEN 1 AND 12"))
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), index=True)
    subject_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subjects.id"), index=True)
    grade: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    allocations: Mapped[list[CurriculumAllocation]] = relationship(back_populates="curriculum")


class CurriculumAllocation(Record):
    __tablename__ = "curriculum_allocations"
    __table_args__ = (UniqueConstraint("curriculum_id", "topic_id"), CheckConstraint("hours > 0"))
    curriculum_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("curricula.id"), index=True)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"), index=True)
    hours: Mapped[int] = mapped_column(Integer)
    curriculum: Mapped[Curriculum] = relationship(back_populates="allocations")


Index("ix_assessment_topic_date", Assessment.topic_id, Assessment.assessment_date)
