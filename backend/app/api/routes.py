from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics import service as analytics
from app.analytics.dashboard import dataset_analytics
from app.contracts import (
    AnalysisRequest, DatasetAnalyticsOut, DatasetListOut, DatasetOut, DatasetStatusOut, EduInsightAnalysisResponse,
    ExplainOut, ExplainRequest, HealthOut,
    OptimizeOut, OptimizeRequest, OverviewOut, SimulateOut, SimulateRequest,
    StoredReportOut, TextbooksOut, TopicsOut,
)
from app.curriculum import service as curriculum
from app.explanations.service import explain
from app.explanations.analysis import analyze
from app.config import MAX_UPLOAD_BYTES
from app.storage.database import get_session
from app.storage.ingest import import_csv
from app.storage.repository import (
    analysis_request_hash, complete_report, dataset_status, fail_report,
    latest_completed_report, list_datasets, reserve_report, resolve_dataset,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_session)]


def _selected_id(session: Session, dataset_id: int | None) -> int | None:
    dataset = resolve_dataset(session, dataset_id)
    if dataset_id is not None and dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset.id if dataset else None


@router.get("/health", response_model=HealthOut)
def health(session: DbSession) -> HealthOut:
    try:
        session.execute(text("SELECT 1"))
        return HealthOut(database="ok")
    except Exception:
        return HealthOut(database="unavailable")


@router.post("/datasets/upload", response_model=DatasetOut)
async def upload_dataset(session: DbSession, file: UploadFile = File(...)) -> DatasetOut:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds upload limit")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=422, detail="A CSV file is required")
    try:
        return import_csv(session, file.filename or "upload.csv", content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/datasets", response_model=DatasetListOut)
def datasets(session: DbSession) -> DatasetListOut:
    return DatasetListOut(datasets=list_datasets(session))


@router.get("/datasets/{dataset_id}/status", response_model=DatasetStatusOut)
def get_dataset_status(dataset_id: int, session: DbSession) -> DatasetStatusOut:
    result = dataset_status(session, dataset_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return result


@router.get("/datasets/{dataset_id}/analytics", response_model=DatasetAnalyticsOut)
def get_dataset_analytics(dataset_id: int, session: DbSession,
                          grade: int | None = None, subject: str | None = None,
                          textbook: str | None = None, topic: str | None = None) -> DatasetAnalyticsOut:
    try:
        return dataset_analytics(session, dataset_id, grade=grade, subject=subject,
                                 textbook=textbook, topic=topic)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/datasets/{dataset_id}/report", response_model=StoredReportOut)
def get_dataset_report(dataset_id: int, session: DbSession) -> StoredReportOut:
    status = dataset_status(session, dataset_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if status.status == "processing":
        raise HTTPException(status_code=409, detail="Analysis is processing")
    report = latest_completed_report(session, dataset_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/analytics/overview", response_model=OverviewOut)
def overview(session: DbSession, dataset_id: int | None = None) -> OverviewOut:
    return analytics.overview(session, _selected_id(session, dataset_id))


@router.get("/analytics/topics", response_model=TopicsOut)
def topics(
    session: DbSession,
    dataset_id: int | None = None,
    weak_threshold: Annotated[float, Query(ge=0, le=1)] = 0.6,
) -> TopicsOut:
    return analytics.topics(session, _selected_id(session, dataset_id), weak_threshold)


@router.get("/analytics/textbooks", response_model=TextbooksOut)
def textbooks(session: DbSession, dataset_id: int | None = None) -> TextbooksOut:
    return analytics.textbooks(session, _selected_id(session, dataset_id))


@router.post("/curriculum/optimize", response_model=OptimizeOut)
def optimize(request: OptimizeRequest, session: DbSession) -> OptimizeOut:
    selected = _selected_id(session, request.dataset_id)
    metrics = analytics.topics(session, selected, request.weak_threshold)
    return curriculum.optimize(request, metrics)


@router.post("/curriculum/simulate", response_model=SimulateOut)
def simulate(request: SimulateRequest, session: DbSession) -> SimulateOut:
    selected = _selected_id(session, request.dataset_id)
    metrics = analytics.topics(session, selected)
    return curriculum.simulate(request, metrics)


@router.post("/recommendations/explain", response_model=ExplainOut)
async def explain_recommendation(request: ExplainRequest) -> ExplainOut:
    try:
        return await explain(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/recommendations/analyze", response_model=EduInsightAnalysisResponse)
async def analyze_recommendation(request: AnalysisRequest, session: DbSession) -> EduInsightAnalysisResponse:
    selected = _selected_id(session, request.dataset_id)
    if selected is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    overview_result = analytics.overview(session, selected)
    topic_result = analytics.topics(session, selected)
    textbook_result = analytics.textbooks(session, selected)
    if request.optimization is not None:
        allocation = request.optimization
        topic_mastery = {topic.topic: topic.mastery for topic in topic_result.topics}
        if allocation.dataset_id != selected:
            raise HTTPException(status_code=422, detail="Optimization dataset does not match selected dataset")
        if sum(row.current_hours for row in allocation.allocations) != allocation.total_hours or sum(row.recommended_hours for row in allocation.allocations) != allocation.total_hours:
            raise HTTPException(status_code=422, detail="Optimization hours do not preserve the budget")
        if len({row.topic for row in allocation.allocations}) != len(allocation.allocations) or any(row.topic not in topic_mastery for row in allocation.allocations):
            raise HTTPException(status_code=422, detail="Optimization topics do not match dataset topics")
        if any(row.current_hours < 0 or row.recommended_hours < 0 or row.change != row.recommended_hours - row.current_hours or abs(row.mastery - topic_mastery[row.topic]) > 1e-9 for row in allocation.allocations):
            raise HTTPException(status_code=422, detail="Optimization metrics do not match backend data")
    request_hash = analysis_request_hash(request, selected)
    state, report = reserve_report(session, selected, request_hash)
    if state == "cached":
        return EduInsightAnalysisResponse.model_validate(report.report_data)
    if state == "processing":
        raise HTTPException(status_code=409, detail={"status": "processing", "dataset_id": selected})
    if state == "missing":
        raise HTTPException(status_code=404, detail="Dataset not found")
    try:
        result = await analyze(request, overview_result, topic_result, textbook_result)
        # Validate the complete report before persistence, including deterministic fallback.
        result = EduInsightAnalysisResponse.model_validate(result)
        complete_report(session, report.id, result)
        return result
    except ValueError as exc:
        fail_report(session, report.id)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        fail_report(session, report.id)
        raise

