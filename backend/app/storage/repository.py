import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import AnalysisRequest, DatasetOut, DatasetStatusOut, EduInsightAnalysisResponse, StoredReportOut
from app.config import ANALYSIS_STALE_SECONDS

from .models import AnalysisReport, Dataset


def _to_out(dataset: Dataset) -> DatasetOut:
    return DatasetOut(id=dataset.id, dataset_id=dataset.id, filename=dataset.filename,
                      row_count=dataset.row_count, created_at=dataset.created_at, status=dataset.status)


def list_datasets(session: Session) -> list[DatasetOut]:
    rows = session.scalars(select(Dataset).order_by(Dataset.created_at.desc(), Dataset.id.desc())).all()
    return [_to_out(row) for row in rows]


def resolve_dataset(session: Session, dataset_id: int | None = None) -> Dataset | None:
    if dataset_id is not None:
        return session.get(Dataset, dataset_id)
    return session.scalar(select(Dataset).order_by(Dataset.created_at.desc(), Dataset.id.desc()).limit(1))


def analysis_request_hash(request: AnalysisRequest, dataset_id: int, skills: list | None = None) -> str:
    payload = request.model_copy(update={"dataset_id": dataset_id}).model_dump(mode="json")
    payload["report_version"] = 5
    if skills:
        payload["skills"] = [skill.model_dump(mode="json") for skill in skills]
    # The context is accepted for compatibility but is not used in the report.
    payload.pop("school_context", None)
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reserve_report(session: Session, dataset_id: int, request_hash: str) -> tuple[str, AnalysisReport | None]:
    """Serialize starts on the dataset row; completed requests are reused."""
    dataset = session.scalar(select(Dataset).where(Dataset.id == dataset_id).with_for_update())
    if dataset is None:
        return "missing", None
    report = session.scalar(select(AnalysisReport).where(
        AnalysisReport.dataset_id == dataset_id,
        AnalysisReport.request_hash == request_hash,
    ))
    if report is not None and report.status == "completed" and report.report_data is not None:
        session.commit()
        return "cached", report
    if dataset.status == "processing":
        active = session.scalar(select(AnalysisReport).where(
            AnalysisReport.dataset_id == dataset_id, AnalysisReport.status == "processing",
        ).order_by(AnalysisReport.id.desc()).limit(1))
        if active is not None:
            updated = active.updated_at.replace(tzinfo=timezone.utc) if active.updated_at.tzinfo is None else active.updated_at
            if datetime.now(timezone.utc) - updated < timedelta(seconds=ANALYSIS_STALE_SECONDS):
                session.commit()
                return "processing", active
            active.status = "failed"
            dataset.status = "failed"
    if report is None:
        report = AnalysisReport(dataset_id=dataset_id, request_hash=request_hash, status="processing")
        session.add(report)
    else:
        report.status = "processing"
        report.report_data = None
    dataset.status = "processing"
    session.commit()
    return "reserved", report


def complete_report(session: Session, report_id: int, result: EduInsightAnalysisResponse) -> None:
    report = session.get(AnalysisReport, report_id)
    report.report_data = result.model_dump(mode="json")
    report.status = "completed"
    report.dataset.status = "completed"
    session.commit()


def fail_report(session: Session, report_id: int) -> None:
    session.rollback()
    report = session.get(AnalysisReport, report_id)
    if report is not None:
        report.status = "failed"
        report.dataset.status = "failed"
        session.commit()


def dataset_status(session: Session, dataset_id: int) -> DatasetStatusOut | None:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        return None
    latest = session.scalar(select(AnalysisReport).where(AnalysisReport.dataset_id == dataset_id)
                            .order_by(AnalysisReport.id.desc()).limit(1))
    return DatasetStatusOut(dataset_id=dataset_id, status=dataset.status,
                            report_id=latest.id if latest is not None else None)


def latest_completed_report(session: Session, dataset_id: int) -> StoredReportOut | None:
    report = session.scalar(select(AnalysisReport).where(
        AnalysisReport.dataset_id == dataset_id, AnalysisReport.status == "completed",
    ).order_by(AnalysisReport.id.desc()).limit(1))
    if report is None or report.report_data is None:
        return None
    return StoredReportOut(id=report.id, dataset_id=dataset_id, status="completed",
                           report=EduInsightAnalysisResponse.model_validate(report.report_data),
                           created_at=report.created_at)
