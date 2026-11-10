"""Dataset-scoped descriptive analytics.

Mastery uses the ratio of total earned points to total possible points.
"""

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.contracts import OverviewOut, TextbookMetric, TextbooksOut, TopicMetric, TopicsOut
from app.storage.models import Assessment
from app.storage.repository import resolve_dataset


def _mastery(earned: float | None, possible: float | None) -> float | None:
    if possible is None or possible <= 0:
        return None
    return min(1.0, max(0.0, float(earned or 0) / float(possible)))


def overview(session: Session, dataset_id: int | None = None) -> OverviewOut:
    dataset = resolve_dataset(session, dataset_id)
    if dataset is None:
        return OverviewOut(dataset_id=None, observation_count=0, student_count=0,
                           topic_count=0, textbook_count=0, overall_mastery=None)

    row = session.execute(
        select(
            func.count(Assessment.id),
            func.count(distinct(Assessment.student_id)),
            func.count(distinct(Assessment.topic)),
            func.count(distinct(Assessment.textbook)),
            func.sum(Assessment.score),
            func.sum(Assessment.max_score),
        ).where(Assessment.dataset_id == dataset.id)
    ).one()
    return OverviewOut(
        dataset_id=dataset.id,
        observation_count=row[0], student_count=row[1], topic_count=row[2],
        textbook_count=row[3], overall_mastery=_mastery(row[4], row[5]),
    )


def topics(session: Session, dataset_id: int | None = None,
           weak_threshold: float = 0.6) -> TopicsOut:
    if not 0 <= weak_threshold <= 1:
        raise ValueError("weak_threshold must be between 0 and 1")
    dataset = resolve_dataset(session, dataset_id)
    if dataset is None:
        return TopicsOut(dataset_id=None, weak_threshold=weak_threshold, topics=[])

    rows = session.execute(
        select(
            Assessment.topic,
            func.sum(Assessment.score),
            func.sum(Assessment.max_score),
            func.count(Assessment.id),
            func.count(distinct(Assessment.student_id)),
        ).where(Assessment.dataset_id == dataset.id).group_by(Assessment.topic)
    ).all()
    metrics = [
        TopicMetric(topic=name, mastery=_mastery(earned, possible) or 0.0,
                    sample_size=count, student_count=students,
                    is_weak=(_mastery(earned, possible) or 0.0) < weak_threshold)
        for name, earned, possible, count, students in rows
    ]
    metrics.sort(key=lambda metric: (metric.mastery, metric.topic))
    return TopicsOut(dataset_id=dataset.id, weak_threshold=weak_threshold, topics=metrics)


def textbooks(session: Session, dataset_id: int | None = None) -> TextbooksOut:
    dataset = resolve_dataset(session, dataset_id)
    if dataset is None:
        return TextbooksOut(dataset_id=None, textbooks=[])

    rows = session.execute(
        select(
            Assessment.textbook,
            func.sum(Assessment.score),
            func.sum(Assessment.max_score),
            func.count(Assessment.id),
            func.count(distinct(Assessment.student_id)),
            func.count(distinct(Assessment.topic)),
        ).where(Assessment.dataset_id == dataset.id).group_by(Assessment.textbook)
    ).all()
    metrics = [
        TextbookMetric(textbook=name, mastery=_mastery(earned, possible) or 0.0,
                       sample_size=count, student_count=students, topic_count=topic_count)
        for name, earned, possible, count, students, topic_count in rows
    ]
    metrics.sort(key=lambda metric: (metric.mastery, metric.textbook))
    return TextbooksOut(dataset_id=dataset.id, textbooks=metrics)
