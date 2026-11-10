"""Chart data derived only from persisted assessment observations."""

from datetime import datetime, timezone
import math

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import (
    DashboardFilters, DashboardOverview, DatasetAnalyticsOut,
    PerformanceTrendPoint, ScoreDistributionPoint, TextbookComparisonPoint,
    TopicMasteryPoint,
)
from app.storage.models import Assessment, Dataset


def dataset_analytics(session: Session, dataset_id: int, *, grade: int | None = None,
                      textbook: str | None = None, topic: str | None = None,
                      subject: str | None = None) -> DatasetAnalyticsOut:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise LookupError("Dataset not found")

    rows = session.execute(select(
        Assessment.student_id, Assessment.topic, Assessment.textbook,
        Assessment.score, Assessment.max_score, Assessment.assessment_date,
        Assessment.grade,
    ).where(Assessment.dataset_id == dataset_id)).all()
    frame = pd.DataFrame(rows, columns=[
        "student_id", "topic", "textbook", "score", "max_score",
        "assessment_date", "grade",
    ])
    warnings: list[str] = []
    filters = DashboardFilters(grades=[], subjects=[], textbooks=[], topics=[])
    if not frame.empty:
        filters = DashboardFilters(
            grades=sorted(int(value) for value in frame["grade"].dropna().unique()),
            subjects=[],
            textbooks=sorted(str(value) for value in frame["textbook"].dropna().unique()),
            topics=sorted(str(value) for value in frame["topic"].dropna().unique()),
        )
    warnings.append("Subject is not stored in the current CSV schema; subject filtering is unavailable.")
    warnings.append("Answer counts are not stored; topic_performance is unavailable.")
    if subject is not None:
        # There is no subject column. An explicit filter cannot match any records.
        frame = frame.iloc[0:0]
        warnings.append("Requested subject cannot be matched because subject data is unavailable.")
    if grade is not None:
        frame = frame.loc[frame["grade"] == grade]
    if textbook is not None:
        frame = frame.loc[frame["textbook"] == textbook]
    if topic is not None:
        frame = frame.loc[frame["topic"] == topic]

    if not frame.empty:
        frame = frame.copy()
        frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
        frame["max_score"] = pd.to_numeric(frame["max_score"], errors="coerce")
        valid = (frame["student_id"].notna() & frame["topic"].notna()
                 & frame["textbook"].notna() & frame["score"].notna()
                 & frame["max_score"].notna() & (frame["max_score"] > 0)
                 & (frame["score"] >= 0) & (frame["score"] <= frame["max_score"]))
        valid &= frame["score"].map(math.isfinite) & frame["max_score"].map(math.isfinite)
        invalid_count = int((~valid).sum())
        if invalid_count:
            warnings.append(f"Excluded {invalid_count} invalid assessment records.")
        frame = frame.loc[valid].copy()

    topic_mastery: list[TopicMasteryPoint] = []
    performance_trend: list[PerformanceTrendPoint] = []
    score_distribution: list[ScoreDistributionPoint] = []
    textbook_comparison: list[TextbookComparisonPoint] = []
    total_students = 0
    average_score = None
    if not frame.empty:
        total_students = int(frame["student_id"].nunique())
        average_score = round(float(frame["score"].sum() / frame["max_score"].sum() * 100), 2)

        for name, group in frame.groupby("topic", sort=True):
            topic_mastery.append(TopicMasteryPoint(
                topic=str(name), score=round(float(group["score"].sum() / group["max_score"].sum() * 100), 2),
                student_count=int(group["student_id"].nunique()),
            ))
        for (book, name), group in frame.groupby(["textbook", "topic"], sort=True):
            textbook_comparison.append(TextbookComparisonPoint(
                textbook=str(book), topic=str(name),
                average_score=round(float(group["score"].sum() / group["max_score"].sum() * 100), 2),
                student_count=int(group["student_id"].nunique()),
            ))

        dated = frame.loc[frame["assessment_date"].notna()]
        if len(dated) < len(frame):
            warnings.append(f"Excluded {len(frame) - len(dated)} undated records from performance_trend.")
        for day, group in dated.groupby("assessment_date", sort=True):
            performance_trend.append(PerformanceTrendPoint(
                assessment_date=day.isoformat(),
                score=round(float(group["score"].sum() / group["max_score"].sum() * 100), 2),
                student_count=int(group["student_id"].nunique()),
            ))

        # Each observation belongs to one bin. A student with multiple assessments
        # may appear in several bins; count distinct students within each bin.
        percentages = frame["score"] / frame["max_score"] * 100
        bins = pd.cut(percentages, bins=[-0.001, 20, 40, 60, 80, 100],
                      labels=["0-20", "20-40", "40-60", "60-80", "80-100"],
                      include_lowest=True)
        for label in bins.cat.categories:
            count = int(frame.loc[bins == label, "student_id"].nunique())
            if count:
                score_distribution.append(ScoreDistributionPoint(score_range=str(label), students_count=count))
        if frame["student_id"].duplicated().any():
            warnings.append("A student may appear in multiple score ranges when they have multiple assessments.")

    return DatasetAnalyticsOut(
        dataset_id=dataset_id, generated_at=datetime.now(timezone.utc),
        overview=DashboardOverview(
            total_students=total_students, average_score=average_score,
            total_topics=len(topic_mastery),
            critical_topics=sum(item.score < 60 for item in topic_mastery),
        ),
        topic_mastery=topic_mastery, performance_trend=performance_trend,
        score_distribution=score_distribution, textbook_comparison=textbook_comparison,
        topic_performance=[], data_quality_warnings=warnings, available_filters=filters,
    )
