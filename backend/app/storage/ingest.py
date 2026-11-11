import csv
import io
import math
from datetime import date

from sqlalchemy.orm import Session

from app.contracts import DatasetOut

from .models import Assessment, Dataset
from .repository import _to_out

REQUIRED = {"student_id", "topic", "textbook", "score", "max_score"}
OPTIONAL = {"assessment_date", "class_id", "grade", "subject"}


class CSVValidationError(ValueError):
    """Invalid CSV input; API callers should translate this to HTTP 422."""


def _text(row: dict[str, str | None], field: str, line: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise CSVValidationError(f"row {line}: {field} must be nonempty")
    if len(value) > 255:
        raise CSVValidationError(f"row {line}: {field} exceeds 255 characters")
    return value


def _number(row: dict[str, str | None], field: str, line: int) -> float:
    try:
        value = float(_text(row, field, line))
    except ValueError as exc:
        raise CSVValidationError(f"row {line}: {field} must be a number") from exc
    if not math.isfinite(value):
        raise CSVValidationError(f"row {line}: {field} must be finite")
    return value


def _parse(content: bytes) -> list[dict[str, object]]:
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CSVValidationError("CSV must be UTF-8") from exc
    if not decoded.strip():
        raise CSVValidationError("CSV is empty")
    stream = io.StringIO(decoded, newline="")
    try:
        reader = csv.DictReader(stream, strict=True)
        fields = reader.fieldnames
        if not fields or len(fields) != len(set(fields)) or not REQUIRED.issubset(fields):
            raise CSVValidationError(f"CSV headers must include {', '.join(sorted(REQUIRED))} without duplicates")
        if set(fields) - REQUIRED - OPTIONAL:
            raise CSVValidationError("CSV contains unknown columns")
        rows: list[dict[str, object]] = []
        for line, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise CSVValidationError(f"row {line}: incorrect column count")
            score = _number(row, "score", line)
            max_score = _number(row, "max_score", line)
            if max_score <= 0 or score < 0 or score > max_score:
                raise CSVValidationError(f"row {line}: require 0 <= score <= max_score and max_score > 0")
            raw_date = (row.get("assessment_date") or "").strip()
            try:
                assessment_date = date.fromisoformat(raw_date) if raw_date else None
            except ValueError as exc:
                raise CSVValidationError(f"row {line}: assessment_date must be an ISO date") from exc
            raw_grade = (row.get("grade") or "").strip()
            try:
                grade = int(raw_grade) if raw_grade else None
            except ValueError as exc:
                raise CSVValidationError(f"row {line}: grade must be an integer") from exc
            class_id = (row.get("class_id") or "").strip() or None
            if class_id and len(class_id) > 255:
                raise CSVValidationError(f"row {line}: class_id exceeds 255 characters")
            subject = (row.get("subject") or "").strip() or None
            if subject and len(subject) > 255:
                raise CSVValidationError(f"row {line}: subject exceeds 255 characters")
            rows.append({
                "student_id": _text(row, "student_id", line),
                "topic": _text(row, "topic", line),
                "subject": subject,
                "textbook": _text(row, "textbook", line),
                "score": score,
                "max_score": max_score,
                "assessment_date": assessment_date,
                "class_id": class_id,
                "grade": grade,
            })
    except csv.Error as exc:
        raise CSVValidationError(f"malformed CSV: {exc}") from exc
    if not rows:
        raise CSVValidationError("CSV has no assessment rows")
    return rows


def import_csv(session: Session, filename: str, content: bytes) -> DatasetOut:
    """Validate every row before writing; commit dataset and observations atomically."""
    if not filename or not filename.lower().endswith(".csv") or len(filename) > 255:
        raise CSVValidationError("filename must be a CSV filename of at most 255 characters")
    rows = _parse(content)
    try:
        dataset = Dataset(filename=filename, row_count=len(rows))
        session.add(dataset)
        session.flush()
        session.add_all(Assessment(dataset_id=dataset.id, **row) for row in rows)
        session.commit()
        session.refresh(dataset)
    except Exception:
        session.rollback()
        raise
    return _to_out(dataset)
