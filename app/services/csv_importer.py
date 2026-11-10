"""CSV contract (one assessment per row, UTF-8 or UTF-8 BOM):

Required: student_id,topic,textbook,score,max_score.
Optional: assessment_date,class_id,grade,classroom,subject.

student_id is a school-scoped external identifier. classroom/class_id, subject,
topic and textbook are names; grade is an integer 1..12; scores are finite decimals
with 0 <= score <= max_score and max_score > 0; assessment_date is ISO YYYY-MM-DD.
The normalized score is a percentage. A duplicate is the same student, topic,
textbook and date within a dataset. Any invalid row rejects the entire import.
"""

from __future__ import annotations

import io
import csv
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import BinaryIO

import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assessment, Classroom, Dataset, School, Student, Subject, TestResult, Textbook, Topic

REQUIRED_COLUMNS = ("student_id", "topic", "textbook", "score", "max_score")
OPTIONAL_COLUMNS = ("assessment_date", "class_id", "grade", "classroom", "subject")


class CsvRow(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    student_id: str
    classroom: str = "Unassigned"
    grade: int = 1
    subject: str = "General"
    topic: str
    textbook: str
    score: Decimal
    max_score: Decimal
    assessment_date: date | None = None

    @field_validator("student_id", "classroom", "subject", "topic", "textbook")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value:
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def field_lengths(self):
        limits = {"student_id": 100, "classroom": 80, "subject": 150, "topic": 200, "textbook": 250}
        for name, limit in limits.items():
            if len(getattr(self, name)) > limit:
                raise ValueError(f"{name} exceeds {limit} characters")
        return self

    @field_validator("assessment_date", mode="before")
    @classmethod
    def iso_date(cls, value: str | None) -> date | None:
        if value is None or value == "":
            return None
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError("expected YYYY-MM-DD")
        return date.fromisoformat(value)

    @model_validator(mode="after")
    def valid_values(self):
        if not 1 <= self.grade <= 12:
            raise ValueError("grade must be 1..12")
        if not self.score.is_finite() or not self.max_score.is_finite() or self.max_score <= 0 or self.score < 0 or self.score > self.max_score:
            raise ValueError("scores require 0 <= score <= max_score and max_score > 0")
        if self.score.as_tuple().exponent < -2 or self.max_score.as_tuple().exponent < -2 or self.max_score > Decimal("99999999.99"):
            raise ValueError("scores support at most two decimal places")
        return self


@dataclass
class RowError:
    row: int
    message: str


@dataclass
class ImportSummary:
    filename: str
    total_rows: int = 0
    imported_rows: int = 0
    dataset_id: str | None = None
    errors: list[RowError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def import_csv(session: Session, file: BinaryIO, filename: str, school_name: str, *, synthetic: bool = False) -> ImportSummary:
    summary = ImportSummary(filename=filename)
    if not filename.lower().endswith(".csv"):
        summary.errors.append(RowError(0, "filename must end in .csv"))
        return summary
    try:
        raw = file.read()
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        content = raw.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(content, newline=""), strict=True)
        header = next(reader, None)
        if header is None:
            raise ValueError("empty CSV")
        if len(header) != len(set(header)):
            raise ValueError("duplicate CSV headers")
        missing = sorted(set(REQUIRED_COLUMNS) - set(header))
        if missing:
            raise ValueError(f"missing columns: {missing}")
        records = []
        line_numbers = []
        previous_line = reader.line_num
        for fields in reader:
            line = previous_line + 1
            previous_line = reader.line_num
            if len(fields) != len(header):
                raise ValueError(f"line {line} has {len(fields)} fields; expected {len(header)}")
            records.append(fields)
            line_numbers.append(line)
        frame = pd.DataFrame(records, columns=header, dtype=str)
    except (UnicodeError, csv.Error, pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        summary.errors.append(RowError(0, f"invalid CSV: {exc}"))
        return summary
    summary.total_rows = len(frame)
    rows: list[CsvRow] = []
    seen = set()
    student_class = {}
    for index, record in frame.iterrows():
        line = line_numbers[int(index)]
        try:
            values = {key: record[key] for key in REQUIRED_COLUMNS}
            values.update({key: record[key] for key in OPTIONAL_COLUMNS if key in frame.columns and record[key] != ""})
            if "classroom" not in values and "class_id" in values:
                values["classroom"] = values["class_id"]
            values.pop("class_id", None)
            row = CsvRow.model_validate(values)
            key = (row.student_id, row.topic, row.subject, row.textbook, row.assessment_date)
            if key in seen:
                raise ValueError("duplicate assessment in CSV")
            seen.add(key)
            location = (row.classroom, row.grade)
            if row.student_id in student_class and student_class[row.student_id] != location:
                raise ValueError("student appears in multiple classrooms")
            student_class[row.student_id] = location
            rows.append(row)
        except Exception as exc:
            summary.errors.append(RowError(line, str(exc)))
    if not rows and not summary.errors:
        summary.errors.append(RowError(1, "CSV contains no data rows"))
    if summary.errors:
        return summary

    try:
        school = session.scalar(select(School).where(School.name == school_name))
        if school is None:
            school = School(name=school_name)
            session.add(school)
            session.flush()
        dataset = Dataset(school_id=school.id, filename=filename, row_count=len(rows), is_synthetic=synthetic)
        session.add(dataset)
        session.flush()
        classrooms = {(c.name, c.grade): c for c in session.scalars(select(Classroom).where(Classroom.school_id == school.id))}
        students = {s.external_id: s for s in session.scalars(select(Student).where(Student.school_id == school.id))}
        subjects = {s.name: s for s in session.scalars(select(Subject))}
        topics = {(t.subject_id, t.name): t for t in session.scalars(select(Topic))}
        textbooks = {(t.subject_id, t.grade, t.title): t for t in session.scalars(select(Textbook))}

        def obtain(cache, key, factory):
            if key not in cache:
                obj = factory()
                session.add(obj)
                session.flush()
                cache[key] = obj
            return cache[key]

        for row in rows:
            classroom = obtain(classrooms, (row.classroom, row.grade), lambda: Classroom(school_id=school.id, name=row.classroom, grade=row.grade))
            student = obtain(students, row.student_id, lambda: Student(school_id=school.id, classroom_id=classroom.id, external_id=row.student_id))
            if student.classroom_id != classroom.id:
                raise ValueError(f"student {row.student_id} belongs to another classroom")
            subject = obtain(subjects, row.subject, lambda: Subject(name=row.subject))
            topic = obtain(topics, (subject.id, row.topic), lambda: Topic(subject_id=subject.id, name=row.topic))
            textbook = obtain(textbooks, (subject.id, row.grade, row.textbook), lambda: Textbook(subject_id=subject.id, grade=row.grade, title=row.textbook))
            assessment = Assessment(dataset_id=dataset.id, student_id=student.id, topic_id=topic.id, textbook_id=textbook.id, assessment_date=row.assessment_date, max_score=row.max_score)
            session.add(assessment)
            session.flush()
            normalized = (row.score * 100 / row.max_score).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            session.add(TestResult(assessment_id=assessment.id, student_id=student.id, score=row.score, normalized_score=normalized))
        session.commit()
        summary.imported_rows = len(rows)
        summary.dataset_id = str(dataset.id)
    except Exception as exc:
        session.rollback()
        summary.errors.append(RowError(0, f"database import failed: {exc}"))
    return summary
